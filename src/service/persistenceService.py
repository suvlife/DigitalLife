"""持久化服务：负责运行时状态的恢复。

写入操作由各业务模块直接调用 dal manager 完成，本模块仅提供恢复相关的加载方法。
"""
from __future__ import annotations

import asyncio

from dal.db import gtAgentHistoryManager, gtScheculeTaskManager, gtRoomMessageManager, gtRoomManager, run_in_transaction_with_retry
from model.dbModel.gtAgentHistory import GtAgentHistory
from model.dbModel.gtRoomMessage import GtRoomMessage
from constants import AgentHistoryTag, AgentTaskStatus


async def startup() -> None:
    pass


async def shutdown() -> None:
    pass


async def load_room_runtime(room_id: int) -> tuple[list[GtRoomMessage], dict[str, int] | None, int]:
    """加载房间的聊天记录、成员读取进度和发言位索引。

    Returns:
        (room_messages, agent_read_index, speaker_index)
    """
    (gt_room_messages, _), (agent_read_index, speaker_index) = await asyncio.gather(
        gtRoomMessageManager.get_room_messages(room_id),
        gtRoomManager.get_room_state(room_id),
    )
    return gt_room_messages, agent_read_index, speaker_index


async def load_agent_history_message(agent_id: int) -> list[GtAgentHistory]:
    """加载 Agent 的对话历史，启动恢复时按 compact 规则裁剪加载范围。

    若存在 compact 记录，只返回恢复当前 compact 视图所需的最小消息窗口。
    统一走 SQL 级裁剪（get_agent_history_after_compact，取最新 compact 之后的数据），
    与 agentHistoryStore.reload_from_db 同一口径，避免全量拉取+内存裁剪的双实现分叉。
    """
    return await gtAgentHistoryManager.get_agent_history_after_compact(agent_id)


async def fail_running_tasks(
    agent_id: int,
    *,
    error_message: str = "task interrupted by process restart",
) -> None:
    """将 Agent 的 RUNNING 任务标记为 FAILED（事务内批量更新，保证原子性）。

    启动恢复阶段高竞争时可能触发 COMMIT 期 BUSY，套用事务级重试（H8）避免
    抛错阻断恢复；批量置 FAILED 幂等，整体回滚后重跑安全。
    """
    async def _op() -> None:
        tasks = await gtScheculeTaskManager.get_running_tasks(agent_id)
        for task in tasks:
            await gtScheculeTaskManager.update_task_status(
                task.id,
                AgentTaskStatus.FAILED,
                error_message=error_message,
            )

    await run_in_transaction_with_retry(_op)


def _trim_to_latest_compact(items: list[GtAgentHistory]) -> list[GtAgentHistory]:
    """按 compact 视图规则裁剪恢复窗口。从 DB 加载时 COMPACT_SUMMARY 可在任意位置，需扫描定位。

    注：主恢复路径（load_agent_history_message / agentHistoryStore.reload_from_db）
    已统一走 SQL 级裁剪（get_agent_history_after_compact）。本函数保留作语义参照与
    单元测试对照，行为与 SQL 版一致（取最新 COMPACT_SUMMARY 起的后缀）。
    """
    for idx in range(len(items) - 1, -1, -1):
        if AgentHistoryTag.COMPACT_SUMMARY in items[idx].tags:
            return items[idx:]
    return items
