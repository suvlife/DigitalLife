"""AgentTurnRunner: Turn 内部逻辑 — 消息同步、host loop、推理、工具调用编排。

同时实现 AgentDriverHost 协议，作为 Driver 的宿主。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, List

from constants import (
    AgentActivityStatus, AgentActivityType,
    AgentHistoryStatus, AgentHistoryTag,
    AgentTaskType, DriverType, OpenaiApiRole, RoomState, TurnStepResult,
)
from model.coreModel.gtCoreChatModel import GtCoreAgentDialogContext
from model.dbModel.gtRoomMessage import GtRoomMessage
from model.dbModel.gtAgent import GtAgent
from model.dbModel.gtAgentHistory import GtAgentHistory
from model.dbModel.gtScheculeTask import GtScheculeTask
from model.dbModel.historyUsage import CompactStage, HistoryUsage
from service import agentActivityService, llmService, roomService
from service.agentActivityService import AgentActivityMeta
from service.agentService.agentHistoryStore import AgentHistoryStore
from service.agentService import compact, promptBuilder
from service.agentService.compactManager import CompactManager
from service.agentService.toolExecutor import ToolExecutor
from service.agentService.driver import AgentDriverConfig, AgentTurnSetup
from service.agentService.driver.factory import build_agent_driver
from service.agentService.toolRegistry import AgentToolRegistry, RegisteredTool, ToolExecutionResult
from service.agentService import toolResultUtils
from service.roomService import ChatRoom, ToolCallContext
from util import configUtil, llmApiUtil
from util.configTypes import LlmServiceConfig
from util.assertUtil import assertNotNull
from dal.db import gtAgentTaskManager, gtAgentHistoryManager

logger = logging.getLogger(__name__)


# 单轮硬性步数上限：统计一轮内所有 step（推理 + 工具执行），防止行为异常/对抗性
# 模型反复调用非 finish 工具而永不结束，导致单轮无限推进、烧尽 API 配额（审计 C2）。
# 超限时以受控方式结束（标 ROOM_TURN_FINISH），而非抛 RuntimeError 走 FAILED→重试放大。
_MAX_TURN_STEPS = 80


class AgentTurnRunner:
    """负责 Turn 内部逻辑：消息同步、host loop 执行、推理、工具调用编排。

    同时实现 AgentDriverHost 协议，是 Driver 的宿主（host）。
    自行构建 driver / tool_registry / history，不持有 Agent 引用。
    """

    def __init__(
        self,
        *,
        gt_agent: GtAgent,
        system_prompt: str,
        agent_workdir: str = "",
        driver_config: AgentDriverConfig | None = None,
    ):
        self.gt_agent: GtAgent = gt_agent
        self.system_prompt: str = system_prompt
        self.agent_workdir: str = agent_workdir
        self._history: AgentHistoryStore = AgentHistoryStore(gt_agent.id or 0)
        self.tool_registry: AgentToolRegistry = AgentToolRegistry()
        self.driver = build_agent_driver(self, driver_config or AgentDriverConfig(driver_type=DriverType.NATIVE))
        self._current_room: ChatRoom | None = None
        self._current_task: GtScheculeTask | None = None
        # 团队级配置缓存（含 llm_service_name），由 _resolve_compact_config 懒加载
        self._team_config: dict | None = None
        self._team_config_loaded: bool = False
        # CompactManager：compact 职责协作组件（拆分 #18 P2）。
        # _compact_lock 随其私有化；主类的 _resolve_compact_config/_execute_compact 等
        # 保留为 delegate 转发到这里，保持既有调用方与测试契约不变。
        self._compact_manager = CompactManager(
            gt_agent=self.gt_agent,
            system_prompt=self.system_prompt,
            # 延迟解析：调用时才取当前 _history/_finish_activity/agentActivityService，
            # 兼容测试在构造后替换 runner._history / patch agentActivityService 的用法。
            history_provider=lambda: self._history,
            tool_registry=self.tool_registry,
            base_metadata=self._base_metadata,
            finish_activity=self._finish_activity,
            team_config_provider=self._get_team_config_async,
            add_activity_provider=lambda: agentActivityService.add_activity,
        )
        # ToolExecutor：工具执行职责协作组件（拆分 #18 P3）。
        # _run_tool_to_item / execute_pending_tools 保留为 delegate（后者是 host 协议入口）。
        self._tool_executor = ToolExecutor(
            gt_agent=self.gt_agent,
            history_provider=lambda: self._history,
            tool_registry=self.tool_registry,
            base_metadata=self._base_metadata,
            finish_activity=self._finish_activity,
            add_activity_provider=lambda: agentActivityService.add_activity,
            current_task_provider=lambda: self._current_task,
        )

    def _base_metadata(self, **extra) -> AgentActivityMeta:
        """构建活动记录 metadata，自动附加 task_room_id（本次 turn 所在的任务房间）。"""
        meta = AgentActivityMeta(
            task_room_id=self._current_room.room_id if self._current_room is not None else None,
            **extra,
        )
        return meta

    async def _finish_activity(
        self,
        activity_id: int | None,
        *,
        status: AgentActivityStatus,
        detail: str | None = None,
        error_message: str | None = None,
        metadata_patch: AgentActivityMeta | None = None,
    ) -> None:
        """更新 activity 终态。"""
        if activity_id is None:
            return
        await agentActivityService.update_activity_progress(activity_id, status=status, detail=detail, error_message=error_message, metadata_patch=metadata_patch)

    # ─── Turn 运行方法 ──────────────────────────────────────

    async def handle_cancel_turn(self) -> None:
        """人工取消当前 turn 的收尾逻辑：driver 清理 → history 清理。"""
        await self.driver.cancel_turn()
        if self._current_room is not None:
            self._current_room.cancel_current_turn()
        await self._history.finalize_cancel_turn()
        await agentActivityService.fail_started_activities(self.gt_agent.id, error_message="cancelled by user")

    async def run_task_turn(self, task: GtScheculeTask) -> None:
        """执行一个完整 chat turn：同步消息 → 推理 → 工具调用循环。

        支持两种模式：
        - ROOM_MESSAGE：从房间同步消息后运行 turn loop，完成后刷新房间消息队列。
        - TODO_TASK：向 history 注入任务通知 prompt 后运行 turn loop，无房间依赖。
        若存在未完成 turn，则走续跑路径。
        """
        is_todo_task = task.task_type == AgentTaskType.TODO_TASK

        if is_todo_task:
            agent_task_id = task.task_data.get("agent_task_id")
            assertNotNull(agent_task_id, error_message=f"task 缺少 agent_task_id, agent_id={self.gt_agent.id}, task_id={task.id}")
            agent_task = await gtAgentTaskManager.get_task(agent_task_id)
            assertNotNull(agent_task, error_message=f"agent_task_id={agent_task_id} 不存在, agent_id={self.gt_agent.id}")
            logger.info(f"协作任务 turn 开始: {self.gt_agent.name}(agent_id={self.gt_agent.id}), agent_task_id={agent_task_id}, title={agent_task.title!r}")
            room = None
        else:
            room_id = task.task_data.get("room_id")
            assertNotNull(room_id, error_message=f"task 缺少 room_id, agent_id={self.gt_agent.id}, task_id={task.id}")
            room = roomService.get_room(room_id)
            assertNotNull(room, error_message=f"room_id={room_id} 不存在, agent_id={self.gt_agent.id}")
            assert room.state != RoomState.INIT, (
                f"Agent 不应在 INIT 状态下收到任务: agent_id={self.gt_agent.id}, room={room.name}, state={room.state}"
            )

        self._current_room = room
        self._current_task = task
        try:
            if self.driver.host_managed_turn_loop:
                assert self.driver.started is True, f"driver 尚未启动: agent_id={self.gt_agent.id}"

                if not self._history.has_active_turn():
                    if is_todo_task:
                        task_prompt = promptBuilder.build_todo_task_turn_prompt(
                            title=agent_task.title,
                            description=agent_task.description,
                            status_value=agent_task.status.value,
                        )
                        await self._history.append_history_message(GtAgentHistory.build(
                            llmApiUtil.OpenAIMessage.text(OpenaiApiRole.USER, task_prompt),
                            tags=[AgentHistoryTag.ROOM_TURN_BEGIN],
                        ))
                        await agentActivityService.add_activity(
                            gt_agent=self.gt_agent,
                            activity_type=AgentActivityType.TASK_RECEIVED,
                            status=AgentActivityStatus.SUCCEEDED,
                            detail=agent_task.title,
                            metadata=self._base_metadata(),
                        )
                    else:
                        synced_count = await self.pull_room_messages_to_history(room)
                        if synced_count == 0:
                            logger.info(f"无新消息，自动跳过本轮: {self.gt_agent.name}(agent_id={self.gt_agent.id}), room={room.name}")
                            await room.handle_finish_request(self.gt_agent.id)
                            await room.flush_queued_messages()
                            return

                await self._run_turn_loop(room)
                if room is not None:
                    await room.flush_queued_messages()

            else:
                synced_count = 1 if is_todo_task else await self.pull_room_messages_to_history(room)
                await self.driver.run_task_turn(task, synced_count)

        except asyncio.CancelledError:
            if not is_todo_task and room is not None:
                room.cancel_current_turn()
            raise
        finally:
            self._current_room = None
            self._current_task = None

    async def pull_room_messages_to_history(self, room: ChatRoom) -> int:
        """从房间拉取未读消息并追加到 history。返回追加的消息条目数（0 或 1）。"""
        new_msgs: List[GtRoomMessage] = await room.get_unread_messages(self.gt_agent.id)

        own_count = sum(1 for msg in new_msgs if msg.sender_id == self.gt_agent.id)
        logger.info(f"同步房间消息: agent={self.gt_agent.name}(agent_id={self.gt_agent.id}), room={room.name}, raw={len(new_msgs)}, own={own_count}, others={len(new_msgs) - own_count}")

        if len(new_msgs) == own_count:
            return 0

        turn_prompt = promptBuilder.build_turn_begin_prompt_from_messages(
            room.name, new_msgs, self.gt_agent.id
        )
        await self._history.append_history_message(GtAgentHistory.build(
            llmApiUtil.OpenAIMessage.text(llmApiUtil.OpenaiApiRole.USER, turn_prompt),
            tags=[AgentHistoryTag.ROOM_TURN_BEGIN],
        ))
        other_msgs = [m for m in new_msgs if m.sender_id != self.gt_agent.id]
        meta = self._base_metadata(messages=[{"sender": m.sender_display_name, "content": m.content} for m in other_msgs])
        await agentActivityService.add_activity(
            gt_agent=self.gt_agent,
            activity_type=AgentActivityType.MESSAGE_RECEIVED,
            status=AgentActivityStatus.SUCCEEDED,
            metadata=meta,
        )
        return 1

    async def _inject_immediate_messages(self, room: ChatRoom) -> None:
        """在安全边界将待注入的 immediately 消息移入主消息列表，并通知 Agent。"""
        await room.flush_pending_immediate_messages()

        new_msgs: List[GtRoomMessage] = await room.get_unread_messages(self.gt_agent.id)
        others = [m for m in new_msgs if m.sender_id != self.gt_agent.id]
        if not others:
            logger.debug(
                "即时插入检查：无新消息: agent=%s(agent_id=%d), room=%s",
                self.gt_agent.name, self.gt_agent.id, room.name,
            )
            return

        update_prompt = promptBuilder.build_turn_update_prompt(
            room.name, new_msgs, self.gt_agent.id
        )
        await self._history.append_history_message(GtAgentHistory.build(
            llmApiUtil.OpenAIMessage.text(llmApiUtil.OpenaiApiRole.USER, update_prompt),
        ))
        logger.info(
            "即时插入新消息: agent=%s(agent_id=%d), room=%s, msgs=%d",
            self.gt_agent.name, self.gt_agent.id, room.name, len(others),
        )
        meta = self._base_metadata(messages=[{"sender": m.sender_display_name, "content": m.content} for m in others])
        await agentActivityService.add_activity(
            gt_agent=self.gt_agent,
            activity_type=AgentActivityType.MESSAGE_RECEIVED,
            status=AgentActivityStatus.SUCCEEDED,
            metadata=meta,
        )

    async def _run_turn_loop(self, room: ChatRoom | None) -> None:
        """基于 history 状态推进的统一循环。room 为 None 时跳过房间相关操作（协作任务模式）。"""
        tools = self.tool_registry.export_openai_tools()
        turn_setup: AgentTurnSetup = self.driver.turn_setup
        failed_action_count = 0
        total_step_count = 0
        next_tool_choice: str | None = None

        while True:
            # 检查 operator 私聊控制房间是否有待即时插入或未读的消息
            if self._history.is_safe_for_immediate_insert():
                ctrl_room = await roomService.get_control_room_for_agent(self.gt_agent.team_id, self.gt_agent.id)
                if ctrl_room is not None and (
                    ctrl_room.has_pending_immediate_messages(self.gt_agent.id) or
                    ctrl_room.has_unread_messages(self.gt_agent.id)
                ):
                    await self._inject_immediate_messages(ctrl_room)

            result = await self._advance_step(room, tools, tool_choice=next_tool_choice)
            next_tool_choice = None
            total_step_count += 1

            if result == TurnStepResult.TURN_DONE:
                return

            if result == TurnStepResult.TOOL_EXECUTE_SUCCESS:
                failed_action_count = 0
                # 硬性步数上限仅在干净边界（最后一条为已完成的 TOOL 结果）检查，
                # 保证受控收尾不会遗留悬空 tool_call。
                if total_step_count >= _MAX_TURN_STEPS:
                    await self._force_finish_turn(room, total_step_count)
                    return
                continue

            if result == TurnStepResult.LLM_OUTPUT_TOOL_CALLS:
                # 推理成功生成了 tool_calls，但尚未执行，不重置计数器
                continue

            if result == TurnStepResult.LLM_OUTPUT_NO_ACTION:
                failed_action_count += 1
                failure_kind = "no_action"
                if len(turn_setup.hint_prompt) > 0 and failed_action_count <= turn_setup.max_retries:
                    logger.warning(f"检测到失败行动，准备重试: agent_id={self.gt_agent.id}, kind={failure_kind}, retry={failed_action_count}/{turn_setup.max_retries}")
                    await self._history.append_history_message(GtAgentHistory.build(
                        llmApiUtil.OpenAIMessage.text(llmApiUtil.OpenaiApiRole.USER, turn_setup.hint_prompt),
                    ))
                    continue
                raise RuntimeError(
                    f"达到失败行动重试上限仍未完成行动: agent_id={self.gt_agent.id}, "
                    f"kind={failure_kind}, failed_actions={failed_action_count}, max_retries={turn_setup.max_retries}"
                )

            if result == TurnStepResult.LLM_OUTPUT_ERROR:
                failed_action_count += 1
                hint = turn_setup.hint_prompt_error_action or turn_setup.hint_prompt
                if len(hint) > 0 and failed_action_count <= turn_setup.max_retries:
                    logger.warning(f"检测到 JSON 写入 content 异常，准备重试: agent_id={self.gt_agent.id}, retry={failed_action_count}/{turn_setup.max_retries}")
                    await self._history.append_history_message(GtAgentHistory.build(
                        llmApiUtil.OpenAIMessage.text(llmApiUtil.OpenaiApiRole.USER, hint),
                    ))
                    next_tool_choice = "required"
                    continue
                raise RuntimeError(
                    f"达到 ERROR_ACTION 重试上限: agent_id={self.gt_agent.id}, "
                    f"failed_actions={failed_action_count}, max_retries={turn_setup.max_retries}"
                )

            if result == TurnStepResult.TOOL_EXECUTE_FAILED_FINISH:
                failed_action_count += 1
                if failed_action_count <= turn_setup.max_retries:
                    logger.warning(f"finish 类工具执行失败，准备重试: agent_id={self.gt_agent.id}, retry={failed_action_count}/{turn_setup.max_retries}")
                    # 不注入 hint：tool_result 已包含具体失败原因，LLM 可直接据此调整行为
                    next_tool_choice = "required"
                    continue
                raise RuntimeError(
                    f"达到 finish 失败重试上限: agent_id={self.gt_agent.id}, "
                    f"failed_actions={failed_action_count}, max_retries={turn_setup.max_retries}"
                )

    async def _force_finish_turn(self, room: ChatRoom | None, total_step_count: int) -> None:
        """轮次步数达到硬上限时的受控收尾（审计 C2）。

        仅在干净边界调用（最后一条为已完成的 TOOL 结果，无悬空 tool_call）：
        追加一条 ROOM_TURN_FINISH 标记消息关闭当前轮次，并触发房间收尾，
        避免抛 RuntimeError 走 FAILED→重试放大。
        """
        logger.warning(
            "轮次步数达到硬上限，强制受控结束: %s(agent_id=%d), steps=%d, max=%d",
            self.gt_agent.name, self.gt_agent.id, total_step_count, _MAX_TURN_STEPS,
        )
        finish_text = (
            f"本轮已达到系统步数上限（{_MAX_TURN_STEPS} 步），为控制成本已自动结束本轮。"
            "请以下一条新消息为起点重新出发。"
        )
        await self._history.append_history_message(GtAgentHistory.build(
            llmApiUtil.OpenAIMessage.text(OpenaiApiRole.USER, finish_text),
            tags=[AgentHistoryTag.ROOM_TURN_FINISH],
        ))
        await agentActivityService.add_activity(
            gt_agent=self.gt_agent,
            activity_type=AgentActivityType.AGENT_STATE,
            status=AgentActivityStatus.SUCCEEDED,
            detail=f"轮次达到步数上限({_MAX_TURN_STEPS})，自动结束",
            metadata=self._base_metadata(),
        )
        if room is not None:
            await room.handle_finish_request(self.gt_agent.id)

    async def _advance_step(self, room: ChatRoom | None, tools: list[llmApiUtil.OpenAITool], tool_choice: str | None = None) -> TurnStepResult:
        """根据当前 history 状态推进一个 step。

        返回:
            `TURN_DONE`：finish 类工具执行成功，turn 已结束
            `TOOL_EXECUTE_SUCCESS`：非 finish 工具执行成功，turn 继续推进
            `TOOL_EXECUTE_FAILED_FINISH`：finish 类工具执行失败
            `LLM_OUTPUT_NO_ACTION`：模型输出纯文本，无工具调用
            `LLM_OUTPUT_ERROR`：模型输出格式异常（如将 tool call 写入 content 字段）
            `LLM_OUTPUT_TOOL_CALLS`：模型生成了 tool_calls，待执行
        """
        last_item = self._history.last()
        if last_item is None:
            raise RuntimeError(f"history 为空，无法推进: agent_id={self.gt_agent.id}")

        role, status = last_item.role, last_item.status

        if role == OpenaiApiRole.ASSISTANT:
            if status == AgentHistoryStatus.SUCCESS:
                first_tc = (last_item.tool_calls or [None])[0]
                if first_tc is None:
                    return TurnStepResult.LLM_OUTPUT_NO_ACTION
                output_item = await self._history.append_history_init_item(
                    role=OpenaiApiRole.TOOL,
                    tool_call_id=first_tc.id,
                )
                return await self._run_tool_to_item(first_tc, output_item, room)
            elif status in (AgentHistoryStatus.INIT, AgentHistoryStatus.FAILED):
                return await self._infer_and_classify(last_item, tools, tool_choice=tool_choice)
            else:
                raise RuntimeError(f"无法推进: agent_id={self.gt_agent.id}, role={role}, status={status}")

        elif role == OpenaiApiRole.TOOL:
            if status == AgentHistoryStatus.INIT:
                tool_call = self._history.find_tool_call_by_id(last_item.tool_call_id)
                if tool_call is None:
                    raise RuntimeError(f"工具调用不存在: agent_id={self.gt_agent.id}, tool_call_id={last_item.tool_call_id}")
                return await self._run_tool_to_item(tool_call, last_item, room)
            elif status == AgentHistoryStatus.SUCCESS:
                pending_tc = self._history.get_first_pending_tool_call()
                if pending_tc is not None:
                    await self._history.append_history_init_item(
                        role=OpenaiApiRole.TOOL,
                        tool_call_id=pending_tc.id,
                    )
                    return TurnStepResult.TOOL_EXECUTE_SUCCESS
                output_item = await self._history.append_history_init_item(role=OpenaiApiRole.ASSISTANT)
                return await self._infer_and_classify(output_item, tools, tool_choice=tool_choice)
            elif status in (AgentHistoryStatus.FAILED, AgentHistoryStatus.CANCELLED):
                # FAILED/CANCELLED 的 tool 不重试，跳过并检查下一个 pending tool call
                pending_tc = self._history.get_first_pending_tool_call()
                if pending_tc is not None:
                    await self._history.append_history_init_item(
                        role=OpenaiApiRole.TOOL,
                        tool_call_id=pending_tc.id,
                    )
                    return TurnStepResult.TOOL_EXECUTE_SUCCESS
                output_item = await self._history.append_history_init_item(role=OpenaiApiRole.ASSISTANT)
                return await self._infer_and_classify(output_item, tools, tool_choice=tool_choice)
            else:
                raise RuntimeError(f"无法推进: agent_id={self.gt_agent.id}, role={role}, status={status}")

        elif role in (OpenaiApiRole.USER, OpenaiApiRole.SYSTEM):
            output_item = await self._history.append_history_init_item(role=OpenaiApiRole.ASSISTANT)
            return await self._infer_and_classify(output_item, tools, tool_choice=tool_choice)

        else:
            raise RuntimeError(f"无法推进: agent_id={self.gt_agent.id}, role={role}, status={status}")

    async def _infer_and_classify(
        self,
        output_item: GtAgentHistory,
        tools: list[llmApiUtil.OpenAITool],
        tool_choice: str | None = None,
    ) -> TurnStepResult:
        """执行推理并按结果分类返回。"""
        assistant_message = await self._infer_to_item(output_item, tools, tool_choice=tool_choice)
        if toolResultUtils.detect_json_tool_call_in_content(assistant_message.content):
            for tc in (assistant_message.tool_calls or []):
                await self._history.append_history_message(GtAgentHistory.build(
                    llmApiUtil.OpenAIMessage.tool_result(tc.id, '{"success": false, "message": "工具调用被跳过：模型输出格式异常"}'),
                    status=AgentHistoryStatus.FAILED,
                    error_message="工具调用被跳过：模型输出格式异常",
                ))
            return TurnStepResult.LLM_OUTPUT_ERROR
        elif assistant_message.tool_calls:
            return TurnStepResult.LLM_OUTPUT_TOOL_CALLS
        else:
            return TurnStepResult.LLM_OUTPUT_NO_ACTION

    async def _infer_to_item(
        self,
        output_item: GtAgentHistory,
        tools: list[llmApiUtil.OpenAITool],
        tool_choice: str | None = None,
    ) -> llmApiUtil.OpenAIMessage:
        """执行推理，结果写入 output_item。"""
        history = self._history
        assert history.is_infer_ready(), (
            f"[agent_id={self.gt_agent.id}] infer 前历史状态非法，"
            f"末尾角色: {history._last_role() or 'empty'}"
        )

        resolved_model, _, trigger_tokens, hard_limit_tokens = self._resolve_compact_config()
        estimated_tokens = 0
        compact_stage: CompactStage = "none"
        overflow_retry = False
        usage: llmApiUtil.OpenAIUsage | None = None
        assistant_committed = False
        activity_id: int | None = None
        request_retry_state: dict[str, bool | int | str | None] = {
            "seen": False,
            "attempt": None,
            "max_attempts": None,
            "last_retry_error": None,
        }

        try:
            messages = history.build_infer_messages()
            estimated_tokens = await compact.estimate_tokens_async(resolved_model, messages, self.system_prompt)

            messages, estimated_tokens, pre_compact_triggered = await self._check_compact(
                messages,
                trigger_prompt_tokens=estimated_tokens,
                estimated_tokens=estimated_tokens,
                check_stage="pre-check",
            )
            if pre_compact_triggered:
                compact_stage = "pre"

            # 活动记录：LLM_INFER STARTED（pre-check compact 已完成，不会与 COMPACT 并行）
            activity = await agentActivityService.add_activity(
                gt_agent=self.gt_agent, activity_type=AgentActivityType.LLM_INFER,
                metadata=self._base_metadata(model=resolved_model, estimated_prompt_tokens=estimated_tokens),
            )
            activity_id = activity.id

            ctx = GtCoreAgentDialogContext(system_prompt=self.system_prompt, messages=messages, tools=tools, tool_choice=tool_choice)

            # 流式推理 + 节流更新
            last_progress_time = time.monotonic()
            chunk_count_since_update = 0
            _THROTTLE_INTERVAL = 0.2  # 200ms
            _THROTTLE_CHUNK_COUNT = 10

            async def _on_progress(progress: llmService.InferStreamProgress) -> None:
                nonlocal last_progress_time, chunk_count_since_update
                chunk_count_since_update += 1
                now = time.monotonic()
                if chunk_count_since_update >= _THROTTLE_CHUNK_COUNT or (now - last_progress_time) >= _THROTTLE_INTERVAL:
                    patch = AgentActivityMeta()
                    patch.apply_progress(progress)
                    await agentActivityService.update_activity_progress(activity_id, metadata_patch=patch)
                    last_progress_time = now
                    chunk_count_since_update = 0

            async def _on_status_event(event: llmService.InferRequestStatusEvent) -> None:
                request_retry_state["seen"] = True
                request_retry_state["attempt"] = event.attempt
                request_retry_state["max_attempts"] = event.max_attempts
                request_retry_state["last_retry_error"] = event.error_message
                patch = AgentActivityMeta()
                patch.apply_request_status_event(event)
                await agentActivityService.update_activity_progress(activity_id, metadata_patch=patch)

            def _build_request_retry_meta_for_terminal() -> AgentActivityMeta | None:
                if request_retry_state["seen"] is not True:
                    return None
                patch = AgentActivityMeta(
                    request_state="",
                    retry_delay_seconds=0,
                    retry_attempt=int(request_retry_state["attempt"]) if request_retry_state["attempt"] is not None else 0,
                    retry_max_attempts=int(request_retry_state["max_attempts"]) if request_retry_state["max_attempts"] is not None else 0,
                    last_retry_error=str(request_retry_state["last_retry_error"]) if request_retry_state["last_retry_error"] is not None else "",
                )
                return patch

            infer_result: llmService.InferResult = await self._call_infer_stream(
                ctx, on_progress=_on_progress, on_status_event=_on_status_event,
            )

            # overflow retry
            if infer_result.ok is False or infer_result.response is None:
                error = infer_result.error
                if (
                    error is not None
                    and compact.is_context_overflow_error(error)
                    and compact_stage != "pre"
                ):
                    logger.info(f"overflow retry 触发: {self.gt_agent.name}(agent_id={self.gt_agent.id}), error={infer_result.error_message}")
                    overflow_retry = True

                    # 标记当前 infer 活动为 FAILED
                    overflow_meta = AgentActivityMeta(error_kind="context_overflow")
                    request_retry_meta = _build_request_retry_meta_for_terminal()
                    if request_retry_meta is not None:
                        overflow_meta.request_state = request_retry_meta.request_state
                        overflow_meta.retry_attempt = request_retry_meta.retry_attempt
                        overflow_meta.retry_max_attempts = request_retry_meta.retry_max_attempts
                        overflow_meta.retry_delay_seconds = request_retry_meta.retry_delay_seconds
                        overflow_meta.last_retry_error = request_retry_meta.last_retry_error
                    await self._finish_activity(activity_id, status=AgentActivityStatus.FAILED, error_message=infer_result.error_message, metadata_patch=overflow_meta)

                    await self._execute_compact()
                    messages = history.build_infer_messages()
                    estimated_tokens = await compact.estimate_tokens_async(resolved_model, messages, self.system_prompt)
                    if estimated_tokens >= hard_limit_tokens:
                        raise RuntimeError(f"overflow compact 后仍超限: agent_id={self.gt_agent.id}") from error

                    # 新建 infer 活动记录
                    retry_metadata = self._base_metadata(
                        model=resolved_model, estimated_prompt_tokens=estimated_tokens, overflow_retry=True,
                    )
                    activity = await agentActivityService.add_activity(
                        gt_agent=self.gt_agent, activity_type=AgentActivityType.LLM_INFER,
                        detail="overflow 重试", metadata=retry_metadata,
                    )
                    activity_id = activity.id
                    request_retry_state = {
                        "seen": False,
                        "attempt": None,
                        "max_attempts": None,
                        "last_retry_error": None,
                    }
                    last_progress_time = time.monotonic()
                    chunk_count_since_update = 0

                    ctx = GtCoreAgentDialogContext(system_prompt=self.system_prompt, messages=messages, tools=tools, tool_choice=tool_choice)
                    infer_result = await self._call_infer_stream(
                        ctx, on_progress=_on_progress, on_status_event=_on_status_event,
                    )

                    # 标记已 compact（用 "post" 表示 compact 后的推理），
                    # 防止二次失败时 except 分支重复触发 post-compact usage 写入
                    compact_stage = "post"

                if infer_result.ok is False or infer_result.response is None:
                    error_message = infer_result.error_message or "unknown inference error"
                    raise RuntimeError(error_message) from infer_result.error

            usage = infer_result.usage
            choice = infer_result.response.choices[0]
            if choice.finish_reason == "length":
                raise RuntimeError(
                    f"LLM 输出被截断（finish_reason=length），max_tokens 不足以完成本次推理: "
                    f"agent_id={self.gt_agent.id}, completion_tokens={usage.completion_tokens if usage else '?'}"
                )
            assistant_message = choice.message
            usage_data = toolResultUtils.build_usage(
                estimated_prompt_tokens=estimated_tokens,
                prompt_tokens=usage.prompt_tokens if usage else None,
                completion_tokens=usage.completion_tokens if usage else None,
                total_tokens=usage.total_tokens if usage else None,
                compact_stage=compact_stage,
                overflow_retry=overflow_retry,
            )
            await history.finalize_history_item(
                history_id=output_item.id,
                message=assistant_message,
                status=AgentHistoryStatus.SUCCESS,
                usage=usage_data,
            )
            assistant_committed = True

            # 活动记录：LLM_INFER SUCCEEDED
            final_meta = AgentActivityMeta()
            final_meta.apply_usage(usage)
            final_meta.queue_wait_ms = infer_result.performance.queue_wait_ms
            final_meta.rate_limit_wait_ms = infer_result.performance.rate_limit_wait_ms
            final_meta.infer_duration_ms = infer_result.performance.infer_duration_ms
            final_meta.retry_wait_ms = infer_result.performance.retry_wait_ms
            final_meta.infer_attempts = infer_result.performance.attempts
            request_retry_meta = _build_request_retry_meta_for_terminal()
            if request_retry_meta is not None:
                final_meta.request_state = request_retry_meta.request_state
                final_meta.retry_attempt = request_retry_meta.retry_attempt
                final_meta.retry_max_attempts = request_retry_meta.retry_max_attempts
                final_meta.retry_delay_seconds = request_retry_meta.retry_delay_seconds
                final_meta.last_retry_error = request_retry_meta.last_retry_error
            await self._finish_activity(activity_id, status=AgentActivityStatus.SUCCEEDED, metadata_patch=final_meta)

            # 活动记录：思考内容和直接发言
            if assistant_message.reasoning_content and assistant_message.reasoning_content.strip():
                await agentActivityService.add_activity(
                    gt_agent=self.gt_agent, activity_type=AgentActivityType.REASONING,
                    status=AgentActivityStatus.SUCCEEDED, detail=assistant_message.reasoning_content,
                    metadata=self._base_metadata(),
                )
            if assistant_message.content and assistant_message.content.strip():
                await agentActivityService.add_activity(
                    gt_agent=self.gt_agent, activity_type=AgentActivityType.CHAT_REPLY,
                    status=AgentActivityStatus.SUCCEEDED, detail=assistant_message.content,
                    metadata=self._base_metadata(),
                )

            post_check_messages = history.build_infer_messages()
            _, _, post_check_triggered = await self._check_compact(
                post_check_messages,
                trigger_prompt_tokens=usage.prompt_tokens if usage and usage.prompt_tokens is not None else estimated_tokens,
                estimated_tokens=estimated_tokens,
                check_stage="post-check",
            )
            if post_check_triggered and compact_stage == "none":
                compact_stage = "post"
                await history.finalize_history_item(
                    history_id=output_item.id,
                    message=None,
                    status=AgentHistoryStatus.SUCCESS,
                    usage=toolResultUtils.build_usage(
                        estimated_prompt_tokens=estimated_tokens,
                        prompt_tokens=usage.prompt_tokens if usage else None,
                        completion_tokens=usage.completion_tokens if usage else None,
                        total_tokens=usage.total_tokens if usage else None,
                        compact_stage=compact_stage,
                        overflow_retry=overflow_retry,
                    ),
                )
            return assistant_message
        except Exception as e:
            if assistant_committed:
                if compact_stage == "none" and usage and usage.prompt_tokens is not None and usage.prompt_tokens >= trigger_tokens:
                    compact_stage = "post"
                    await history.finalize_history_item(
                        history_id=output_item.id,
                        message=None,
                        status=AgentHistoryStatus.SUCCESS,
                        usage=toolResultUtils.build_usage(
                            estimated_prompt_tokens=estimated_tokens,
                            prompt_tokens=usage.prompt_tokens,
                            completion_tokens=usage.completion_tokens,
                            total_tokens=usage.total_tokens,
                            compact_stage=compact_stage,
                            overflow_retry=overflow_retry,
                        ),
                    )
                raise

            usage_data = toolResultUtils.build_usage(
                estimated_prompt_tokens=estimated_tokens or None,
                prompt_tokens=usage.prompt_tokens if usage else None,
                completion_tokens=usage.completion_tokens if usage else None,
                total_tokens=usage.total_tokens if usage else None,
                compact_stage=compact_stage,
                overflow_retry=overflow_retry,
            )
            await history.finalize_history_item(
                history_id=output_item.id,
                message=None,
                status=AgentHistoryStatus.FAILED,
                error_message=str(e),
                usage=usage_data,
            )
            # 活动记录：LLM_INFER FAILED（pre-check compact 失败时 activity_id 为 None，无需更新）
            if activity_id is not None:
                await self._finish_activity(
                    activity_id,
                    status=AgentActivityStatus.FAILED,
                    error_message=str(e),
                    metadata_patch=_build_request_retry_meta_for_terminal(),
                )
            raise

    async def _run_tool_to_item(self, tool_call: llmApiUtil.OpenAIToolCall, output_item: GtAgentHistory, room: ChatRoom | None) -> TurnStepResult:
        """执行单个工具调用（delegate → ToolExecutor，拆分 #18 P3）。

        保留同名方法以保持既有调用方与测试契约不变；实际逻辑在 ToolExecutor。
        """
        return await self._tool_executor.run_tool_to_item(tool_call, output_item, room)


    async def execute_pending_tools(self) -> None:
        """执行最后一条 assistant 消息中的所有 tool calls。

        AgentDriverHost 协议方法，通过 _current_room 获取房间上下文，
        由 run_task_turn 在调用前设置。协作任务模式下 _current_room 为 None。
        """
        room = self._current_room  # may be None for TODO_TASK

        last_msg: llmApiUtil.OpenAIMessage | None = self._history.get_last_assistant_message()
        if last_msg is None or last_msg.tool_calls is None or len(last_msg.tool_calls) == 0:
            return

        for tool_call in last_msg.tool_calls:
            output_item = await self._history.append_history_init_item(
                role=OpenaiApiRole.TOOL,
                tool_call_id=tool_call.id,
            )
            await self._run_tool_to_item(tool_call, output_item, room)

    # ─── 内部辅助方法 ─────────────────────────────

    def _resolve_compact_config(self) -> tuple[str, LlmServiceConfig, int, int]:
        """获取 compact 相关配置（delegate → CompactManager，拆分 #18 P2）。"""
        return self._compact_manager.resolve_compact_config()

    async def _get_team_config_async(self) -> dict | None:
        """异步获取团队配置（含 DB 查询）。失败时返回 None（降级到全局默认服务）。

        结果按实例缓存（_team_config/_team_config_loaded），避免 pre-check/post-check/
        overflow 多条 compact 路径与每次推理都重复查询同一团队配置（N+1）。
        """
        if self._team_config_loaded:
            return self._team_config
        self._team_config_loaded = True
        if self.gt_agent.team_id <= 0:
            self._team_config = None
            return None
        try:
            from dal.db import gtTeamManager
            team = await gtTeamManager.get_team_by_id(self.gt_agent.team_id)
            self._team_config = team.config if team else None
        except Exception:
            self._team_config = None
        return self._team_config

    async def _call_infer_stream(self, ctx: GtCoreAgentDialogContext, **kwargs) -> llmService.InferResult:
        """Call infer_stream while remaining compatible with narrow test/mocking handlers.

        Production ``llmService.infer_stream`` accepts ``team_config``. Some integrations
        replace it with a small two-argument coroutine; only pass the optional keyword
        when the active callable declares it or accepts ``**kwargs``.
        """
        infer_callable = llmService.infer_stream
        # The real service function accepts team_config. Mock wrappers often expose
        # ``*args, **kwargs`` but forward to a narrower handler, so identity is a
        # more reliable compatibility check than wrapper signature introspection.
        if infer_callable is llmService.core.infer_stream:
            kwargs["team_config"] = await self._get_team_config_async()
        return await infer_callable(self.gt_agent.model, ctx, **kwargs)

    async def _check_compact(
        self,
        messages: list[llmApiUtil.OpenAIMessage],
        *,
        trigger_prompt_tokens: int,
        estimated_tokens: int,
        check_stage: str,
    ) -> tuple[list[llmApiUtil.OpenAIMessage], int, bool]:
        """在指定检查阶段检测 prompt token，必要时执行 compact。

        Returns: (messages, estimated_tokens, compact_triggered)
        """
        resolved_model, _, trigger_tokens, hard_limit_tokens = self._resolve_compact_config()
        if trigger_prompt_tokens < trigger_tokens:
            return messages, estimated_tokens, False

        logger.info(
            f"{check_stage} compact 触发: {self.gt_agent.name}(agent_id={self.gt_agent.id}), "
            f"prompt_tokens={trigger_prompt_tokens}, trigger={trigger_tokens}"
        )
        await self._execute_compact()

        messages = self._history.build_infer_messages()
        msg_summary = ", ".join(f"{m.role}:{len(m.content or '') if not m.tool_calls else 'TC'}" for m in messages)
        logger.info(
            "[compact-recheck] agent_id=%d, message_count=%d, messages=[%s]",
            self.gt_agent.id, len(messages), msg_summary,
        )
        estimated_tokens = await compact.estimate_tokens_async(resolved_model, messages, self.system_prompt)
        if estimated_tokens >= hard_limit_tokens:
            raise RuntimeError(
                f"{check_stage} compact 后仍超限: agent_id={self.gt_agent.id}, "
                f"estimated={estimated_tokens}, hard_limit={hard_limit_tokens}"
            )

        return messages, estimated_tokens, True

    async def _execute_compact(self) -> None:
        """执行一次 compact（delegate → CompactManager，拆分 #18 P2）。

        保留同名方法以保持既有调用方与测试契约不变；实际逻辑在 CompactManager。
        """
        await self._compact_manager.execute_compact()
