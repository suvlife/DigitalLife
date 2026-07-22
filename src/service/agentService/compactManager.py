"""CompactManager：Agent 上下文压缩（compact）的协作组件（拆分 #18 P2）。

从 AgentTurnRunner 抽离的 compact 职责：token 估算、trigger 判定、执行压缩、
DB 旧前缀清理、压缩互斥。持有对 AgentHistoryStore / AgentToolRegistry 的共享引用
（构造注入，不独占），activity 上报经注入的 reporter 回调完成。

对外契约：AgentTurnRunner 保留 _resolve_compact_config / _execute_compact 等
同名 delegate 方法转发到这里，既有调用方与测试无感知。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from constants import AgentActivityStatus, AgentActivityType
from model.dbModel.gtAgent import GtAgent
from service.agentService import compact
from service.agentActivityService import AgentActivityMeta
from service.agentService.agentHistoryStore import AgentHistoryStore
from service.agentService.toolRegistry import AgentToolRegistry
from util import configUtil, llmApiUtil
from util.configTypes import LlmServiceConfig
from dal.db import gtAgentHistoryManager

logger = logging.getLogger(__name__)

# reporter 回调签名：构建活动 metadata / activity 终态上报 / 创建活动
BaseMetadataFn = Callable[..., AgentActivityMeta]
FinishActivityFn = Callable[..., Awaitable[None]]
TeamConfigFn = Callable[[], Awaitable[dict | None]]
# add_activity 的"提供者"回调：调用时才解析当前引用（而非构造期绑定），
# 使测试在构造后 patch 主类 agentActivityService 仍能生效。
AddActivityProviderFn = Callable[[], Callable[..., Awaitable[Any]]]
# history 的"提供者"回调：调用时才取主类当前 _history（而非构造期快照），
# 兼容测试在构造后直接赋值替换 runner._history 的用法。
HistoryProviderFn = Callable[[], AgentHistoryStore]


class CompactManager:
    """Agent 上下文压缩管理器。

    构造注入共享协作者（history / tool_registry / team_config 提供者 / activity
    reporter），不复制其状态。_compact_lock 为本组件私有，随组件整体从主类搬走。
    """

    def __init__(
        self,
        *,
        gt_agent: GtAgent,
        system_prompt: str,
        history_provider: HistoryProviderFn,
        tool_registry: AgentToolRegistry,
        base_metadata: BaseMetadataFn,
        finish_activity: FinishActivityFn,
        team_config_provider: TeamConfigFn,
        add_activity_provider: AddActivityProviderFn,
    ):
        self._gt_agent = gt_agent
        self._system_prompt = system_prompt
        self._history_provider = history_provider
        self._tool_registry = tool_registry
        self._base_metadata = base_metadata
        self._finish_activity = finish_activity
        self._team_config_provider = team_config_provider
        self._add_activity_provider = add_activity_provider
        # compact 互斥锁：防止 pre-check/post-check/overflow 三条路径并发 compact
        self._lock: asyncio.Lock = asyncio.Lock()

    @property
    def _history(self) -> AgentHistoryStore:
        """当前 history（延迟解析，兼容主类 _history 被替换的场景）。"""
        return self._history_provider()

    def resolve_compact_config(self) -> tuple[str, LlmServiceConfig, int, int]:
        """获取 compact 相关配置：(resolved_model, llm_config, trigger_tokens, hard_limit_tokens)。

        优先级：agent.model + team.config.llm_service_name → 全局 current_llm_service。
        """
        llm_config = configUtil.get_app_config().setting.current_llm_service
        if llm_config is None:
            raise ValueError("未配置可用的 LLM 服务（llm_services 全部被禁用或为空）")
        resolved_model = self._gt_agent.model or llm_config.model
        trigger_tokens = compact.calc_compact_trigger_tokens(resolved_model, llm_config)
        hard_limit_tokens = compact.calc_hard_limit_tokens(resolved_model, llm_config)
        return resolved_model, llm_config, trigger_tokens, hard_limit_tokens

    async def execute_compact(self) -> None:
        """执行一次 compact：生成摘要 → 插入 COMPACT_SUMMARY → 内存裁剪 → 清理 DB 旧前缀。

        使用互斥锁防止并发 compact（pre-check/post-check/overflow 三条路径）。
        失败时 raise，不修改内存状态。
        """
        async with self._lock:
            await self._execute_compact_locked()

    async def _execute_compact_locked(self) -> None:
        resolved_model, llm_config, _, hard_limit_tokens = self.resolve_compact_config()

        compact_activity = await self._add_activity_provider()(
            gt_agent=self._gt_agent, activity_type=AgentActivityType.COMPACT, metadata=self._base_metadata(),
        )

        compact_plan = self._history.build_compact_plan()
        if compact_plan is None:
            logger.warning("compact 跳过：无可压缩消息, agent_id=%d", self._gt_agent.id)
            await self._finish_activity(compact_activity.id, status=AgentActivityStatus.FAILED, error_message="无可压缩消息")
            raise RuntimeError("compact 跳过：无可压缩消息")

        # 摘要 token 上限动态设为上下文长度的 10%，随模型配置自动伸缩
        compact_max_tokens = max(1, int(llm_config.context_window_tokens * 0.1))
        # 单条源消息 token 硬上限：防止超长单条消息使 compact 请求本身无法收敛
        per_message_max_tokens = max(1, hard_limit_tokens // 2)
        try:
            summary_text = await compact.compact_messages(
                messages=compact_plan.source_messages,
                system_prompt=self._system_prompt,
                model=resolved_model,
                tools=self._tool_registry.export_openai_tools(),
                max_tokens=compact_max_tokens,
                team_config=await self._team_config_provider(),
                per_message_max_tokens=per_message_max_tokens,
            )
        except Exception as e:
            error_detail = str(e)
            logger.warning("compact 失败: %s, agent_id=%d", error_detail, self._gt_agent.id)
            await self._finish_activity(compact_activity.id, status=AgentActivityStatus.FAILED, error_message=error_detail)
            raise

        # compact_plan 非 None 时 insert_seq 必已确定（build_compact_plan 仅在能定位
        # 插入点时返回计划），此处收窄为 int 以满足下游签名。
        old_prefix_seq = compact_plan.insert_seq
        assert old_prefix_seq is not None, "compact_plan.insert_seq 不应为 None"
        await self._history.insert_compact_summary(
            llmApiUtil.OpenAIMessage.text(llmApiUtil.OpenaiApiRole.USER, summary_text),
            seq=old_prefix_seq,
        )

        # compact 成功后物理删除 DB 中旧前缀消息，防止 DB 持续膨胀
        try:
            deleted = await gtAgentHistoryManager.delete_history_before_seq(
                self._gt_agent.id, old_prefix_seq,
            )
            if deleted > 0:
                logger.info("compact 清理 DB 旧前缀: agent_id=%d, deleted=%d, before_seq=%d",
                            self._gt_agent.id, deleted, old_prefix_seq)
        except Exception as del_err:
            # 清理失败不影响 compact 主流程（内存已正确），仅记录日志
            logger.warning("compact 清理 DB 旧前缀失败（不影响运行）: agent_id=%d, error=%s",
                           self._gt_agent.id, del_err)

        await self._finish_activity(compact_activity.id, status=AgentActivityStatus.SUCCEEDED)
