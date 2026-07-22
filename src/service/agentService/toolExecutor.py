"""ToolExecutor：Agent 工具执行的协作组件（拆分 #18 P3）。

从 AgentTurnRunner 抽离的工具执行职责：单工具执行、未注册/自中断/命令审批网关、
结果截断与落 history、活动上报。持有对 history / tool_registry / turn 级上下文的
延迟解析引用（构造注入 provider，兼容测试在构造后替换 runner._history / patch
agentActivityService 的用法）。

对外契约：AgentTurnRunner 保留 _run_tool_to_item / execute_pending_tools 为
delegate（后者是 AgentDriverHost 协议强制入口，必须留在 host 上），转发到这里。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

from constants import (
    AgentActivityStatus, AgentActivityType, AgentHistoryStatus, AgentHistoryTag,
    OpenaiApiRole, TurnStepResult,
)
from model.dbModel.gtAgent import GtAgent
from model.dbModel.gtAgentHistory import GtAgentHistory
from model.dbModel.gtScheculeTask import GtScheculeTask
from service import agentActivityService
from service.agentActivityService import AgentActivityMeta
from service.agentService import toolResultUtils
from service.agentService.agentHistoryStore import AgentHistoryStore
from service.agentService.toolRegistry import AgentToolRegistry, RegisteredTool, ToolExecutionResult
from service.roomService import ChatRoom, ToolCallContext
from util import llmApiUtil

logger = logging.getLogger(__name__)

# 延迟解析回调签名（见 CompactManager 同款模式）
HistoryProviderFn = Callable[[], AgentHistoryStore]
BaseMetadataFn = Callable[..., AgentActivityMeta]
FinishActivityFn = Callable[..., Awaitable[None]]
AddActivityProviderFn = Callable[[], Callable[..., Awaitable[Any]]]
CurrentTaskProviderFn = Callable[[], GtScheculeTask | None]


class ToolExecutor:
    """Agent 工具执行器。

    构造注入延迟解析的共享协作者（history / tool_registry / activity reporter /
    当前任务提供者），不复制其状态。turn 级易变状态（当前房间）经调用参数传入。
    """

    def __init__(
        self,
        *,
        gt_agent: GtAgent,
        history_provider: HistoryProviderFn,
        tool_registry: AgentToolRegistry,
        base_metadata: BaseMetadataFn,
        finish_activity: FinishActivityFn,
        add_activity_provider: AddActivityProviderFn,
        current_task_provider: CurrentTaskProviderFn,
    ):
        self._gt_agent = gt_agent
        self._history_provider = history_provider
        self._tool_registry = tool_registry
        self._base_metadata = base_metadata
        self._finish_activity = finish_activity
        self._add_activity_provider = add_activity_provider
        self._current_task_provider = current_task_provider

    @property
    def _history(self) -> AgentHistoryStore:
        return self._history_provider()

    async def run_tool_to_item(
        self,
        tool_call: llmApiUtil.OpenAIToolCall,
        output_item: GtAgentHistory,
        room: ChatRoom | None,
    ) -> TurnStepResult:
        """执行单个工具调用，结果写入 output_item。

        返回：
            `TURN_DONE`：turn 结束类工具（marks_turn_finish）执行成功。
            `TOOL_EXECUTE_FAILED_FINISH`：turn 结束类工具执行失败，触发 failed_action_count（防止死循环）。
            `TOOL_EXECUTE_SUCCESS`：普通工具执行完毕，继续下一步。
        """
        tool_name = tool_call.function_name
        tool_metadata = self._base_metadata(
            tool_name=tool_name,
            tool_arguments=toolResultUtils.extract_tool_arguments(tool_call),
            tool_call_id=tool_call.id,
            command=toolResultUtils.extract_tool_command(tool_call),
        )
        tool_activity = await self._add_activity_provider()(
            gt_agent=self._gt_agent, activity_type=AgentActivityType.TOOL_CALL,
            detail=tool_name, metadata=tool_metadata,
        )
        registered_tool: RegisteredTool | None = self._tool_registry.get_registered_tool(tool_name)
        if registered_tool is None:
            error_msg = f"工具 '{tool_name}' 未找到，请使用已有工具完成行动。"
            logger.warning("tool not registered: agent_id=%d, tool=%s", self._gt_agent.id, tool_name)

            final_message = llmApiUtil.OpenAIMessage.tool_result(
                output_item.tool_call_id or "", json.dumps({"success": False, "message": error_msg}, ensure_ascii=False)
            )

            await self._history.finalize_history_item(
                history_id=output_item.id, message=final_message, status=AgentHistoryStatus.FAILED, error_message=error_msg
            )
            await self._finish_activity(tool_activity.id, status=AgentActivityStatus.FAILED, error_message=error_msg)
            return TurnStepResult.TOOL_EXECUTE_FAILED_FINISH

        if registered_tool.self_interrupt:
            if AgentHistoryTag.SELF_INTERRUPT in output_item.tags:
                # 重启后：output_item 已有 SELF_INTERRUPT tag，说明上次已触发过，直接自动成功。
                logger.info(
                    "[self-interrupt] 重启后自动完成自中断工具: agent_id=%d, tool=%s",
                    self._gt_agent.id, tool_name,
                )
                auto_result = {"success": True, "message": f"已完成重启，并恢复原历史任务运行"}
                final_message = llmApiUtil.OpenAIMessage.tool_result(
                    output_item.tool_call_id or "",
                    json.dumps(auto_result, ensure_ascii=False),
                )
                await self._history.finalize_history_item(
                    history_id=output_item.id,
                    message=final_message,
                    status=AgentHistoryStatus.SUCCESS,
                )
                await self._finish_activity(
                    tool_activity.id,
                    status=AgentActivityStatus.SUCCEEDED,
                    metadata_patch=AgentActivityMeta(tool_result=auto_result),
                )
                return TurnStepResult.TOOL_EXECUTE_SUCCESS
            else:
                # 第一次执行：写入 tag 后继续执行 handler。
                # handler 会触发 agent 中断（CancelledError），item 以 INIT+tag 留在 DB。
                await self._history.mark_self_interrupt_tag(output_item.id)

        team_id = room.team_id if room is not None else self._gt_agent.team_id
        context = ToolCallContext(
            agent_id=self._gt_agent.id,
            team_id=team_id,
            chat_room=room,
            schedule_task=self._current_task_provider(),
        )

        # 命令审批网关：拦截 execute_bash 中的高危命令
        if tool_name == "execute_bash":
            command = toolResultUtils.extract_tool_command(tool_call)
            if command and toolResultUtils.is_dangerous_command(command):
                error_msg = f"命令被安全网关拦截（含高危操作）: {command[:100]}"
                logger.warning("命令审批拦截: agent_id=%d, command=%s", self._gt_agent.id, command[:100])
                final_message = llmApiUtil.OpenAIMessage.tool_result(
                    output_item.tool_call_id or "",
                    json.dumps({"success": False, "message": error_msg}, ensure_ascii=False),
                )
                await self._history.finalize_history_item(
                    history_id=output_item.id, message=final_message,
                    status=AgentHistoryStatus.FAILED, error_message=error_msg,
                )
                await self._finish_activity(
                    tool_activity.id, status=AgentActivityStatus.FAILED, error_message=error_msg,
                )
                return TurnStepResult.TOOL_EXECUTE_FAILED_FINISH

        exec_result: ToolExecutionResult = await self._tool_registry.execute_tool_call(tool_call, context)

        # 工具结果截断：过长的原始内容会显著增加后续 prompt token，按策略截断后存入 history
        # 完整结果保留在 activity 记录中备查
        history_result = toolResultUtils.truncate_tool_result_for_history(exec_result.result, tool_name=tool_name)
        final_message = llmApiUtil.OpenAIMessage.tool_result(
            exec_result.tool_call_id,
            json.dumps(history_result, ensure_ascii=False),
        )
        await self._history.finalize_history_item(
            history_id=output_item.id,
            message=final_message,
            status=AgentHistoryStatus.SUCCESS if exec_result.success else AgentHistoryStatus.FAILED,
            error_message=exec_result.error_message,
            tags=[AgentHistoryTag.ROOM_TURN_FINISH] if (registered_tool.marks_turn_finish and exec_result.success) else None,
        )

        # 活动记录：TOOL_CALL SUCCEEDED / FAILED
        await self._finish_activity(
            tool_activity.id,
            status=AgentActivityStatus.SUCCEEDED if exec_result.success else AgentActivityStatus.FAILED,
            error_message=exec_result.error_message,
            metadata_patch=AgentActivityMeta(tool_result=exec_result.result),
        )

        if registered_tool.marks_turn_finish:
            if exec_result.success:
                return TurnStepResult.TURN_DONE
            # finish 类工具失败：触发 failed_action_count，防止 LLM 反复重试导致死循环
            return TurnStepResult.TOOL_EXECUTE_FAILED_FINISH
        return TurnStepResult.TOOL_EXECUTE_SUCCESS
