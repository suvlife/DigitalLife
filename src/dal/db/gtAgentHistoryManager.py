from __future__ import annotations

import logging

from peewee import SQL

from constants import AgentHistoryTag
from constants import AgentHistoryStatus
from constants import OpenaiApiRole
from model.dbModel.gtAgentHistory import GtAgentHistory
from model.dbModel.historyUsage import HistoryUsage
from util import llmApiUtil
from .transaction import run_in_transaction_with_retry
from . import gtAgentManager

logger = logging.getLogger(__name__)

_UNSET = object()


async def append_agent_history_message(message: GtAgentHistory) -> GtAgentHistory:
    await (
        GtAgentHistory
        .insert(
            agent_id=message.agent_id,
            seq=message.seq,
            role=message.role,
            tool_call_id=message.tool_call_id,
            message=message.message,
            status=message.status,
            error_message=message.error_message,
            tags=message.tags,
            usage=message.usage,
        )
        .on_conflict_ignore()
        .aio_execute()
    )
    row: GtAgentHistory | None = await GtAgentHistory.aio_get_or_none(
        GtAgentHistory.agent_id == message.agent_id,
        GtAgentHistory.seq == message.seq,
    )
    if row is None:
        raise RuntimeError(f"append agent history failed: agent_id={message.agent_id}#{message.seq}")
    # M11：on_conflict_ignore 会在 (agent_id, seq) 已被占用时静默丢弃本次写入，
    # 使调用方误以为写入成功但拿到的是他人/旧行。re-select 后校验关键字段一致性，
    # 若发现分叉则告警（不硬失败，避免打断上层业务；由日志暴露并发/重入抢插）。
    if (
        row.role != message.role
        or row.tool_call_id != message.tool_call_id
        or row.status != message.status
    ):
        logger.warning(
            "[append-history] seq 冲突被 on_conflict_ignore 掩盖：agent_id=%d seq=%d "
            "已存在行(role=%s, tool_call_id=%s, status=%s) 与待写入(role=%s, tool_call_id=%s, status=%s)不一致，本次写入被丢弃",
            message.agent_id, message.seq,
            row.role, row.tool_call_id, row.status,
            message.role, message.tool_call_id, message.status,
        )
    return row


async def _shift_agent_history_seq_from_body(agent_id: int, from_seq: int, delta: int) -> None:
    """seq 平移的语句体，不自行开启事务。

    由调用方（``shift_agent_history_seq_from`` / ``insert_agent_history_message_at_seq``）
    在事务级重试封装内统一提供事务边界，避免嵌套 savepoint 使外层 COMMIT BUSY 兜不到。
    """
    if delta == 0:
        return
    rows = await (
        GtAgentHistory
        .select()
        .where(
            GtAgentHistory.agent_id == agent_id,
            GtAgentHistory.seq >= from_seq,
        )
        .order_by(
            GtAgentHistory.seq.desc() if delta > 0 else GtAgentHistory.seq.asc()  # type: ignore[attr-defined]
        )
        .aio_execute()
    )
    for row in rows:
        await (
            GtAgentHistory
            .update(seq=row.seq + delta)
            .where(GtAgentHistory.id == row.id)
            .aio_execute()
        )


async def shift_agent_history_seq_from(agent_id: int, from_seq: int, delta: int) -> None:
    """将指定 agent 下 seq >= from_seq 的历史整体平移。

    为避免唯一索引(agent_id, seq)冲突，delta>0 时按 seq 降序更新。
    整个操作在事务中执行，保证中途失败不会留下 seq 半平移的不一致状态。

    多语句事务，套用事务级重试（H8）：COMMIT 期 BUSY 会整体回滚并重跑，
    平移幂等且无外部副作用，重跑安全。
    """
    if delta == 0:
        return

    async def _op() -> None:
        await _shift_agent_history_seq_from_body(agent_id, from_seq, delta)

    await run_in_transaction_with_retry(_op)


async def insert_agent_history_message_at_seq(message: GtAgentHistory) -> GtAgentHistory:
    """在指定 seq 插入历史消息，并将其后的消息整体后移。

    shift + insert 并入同一事务（H7），避免"已平移未插入"的 seq 空洞与内存/DB 分叉；
    整块事务套用事务级重试（H8），COMMIT 期 BUSY 整体回滚后重跑（幂等、无外部副作用）。
    """
    async def _op() -> GtAgentHistory:
        await _shift_agent_history_seq_from_body(message.agent_id, message.seq, 1)
        return await append_agent_history_message(message)

    return await run_in_transaction_with_retry(_op)


async def update_agent_history_by_id(
    history_id: int,
    *,
    role: OpenaiApiRole | object = _UNSET,
    tool_call_id: str | None | object = _UNSET,
    message: llmApiUtil.OpenAIMessage | None | object = _UNSET,
    status: AgentHistoryStatus | object = _UNSET,
    error_message: str | None | object = _UNSET,
    tags: list[AgentHistoryTag] | None | object = _UNSET,
    usage: HistoryUsage | None | object = _UNSET,
) -> GtAgentHistory:
    update_fields: dict = {}
    if role is not _UNSET:
        update_fields["role"] = role
    if tool_call_id is not _UNSET:
        update_fields["tool_call_id"] = tool_call_id
    if message is not _UNSET:
        update_fields["message"] = message
    if status is not _UNSET:
        update_fields["status"] = status
    if error_message is not _UNSET:
        update_fields["error_message"] = error_message
    if tags is not _UNSET:
        update_fields["tags"] = tags
    if usage is not _UNSET:
        update_fields["usage"] = usage
    if not update_fields:
        raise ValueError(f"update agent history by id has no fields to update: id={history_id}")

    await (
        GtAgentHistory
        .update(**update_fields)
        .where(
            GtAgentHistory.id == history_id,
        )
        .aio_execute()
    )
    row: GtAgentHistory | None = await GtAgentHistory.aio_get_or_none(
        GtAgentHistory.id == history_id,
    )
    if row is None:
        raise RuntimeError(f"update agent history status failed: id={history_id}")
    return row


async def get_agent_history(agent_id: int) -> list[GtAgentHistory]:
    return await (
        GtAgentHistory
        .select()
        .where(GtAgentHistory.agent_id == agent_id)
        .order_by(GtAgentHistory.seq.asc())  # type: ignore[attr-defined]
        .aio_execute()
    )


async def get_agent_history_after_compact(agent_id: int) -> list[GtAgentHistory]:
    """获取 COMPACT_SUMMARY 之后的历史数据。

    若存在 COMPACT_SUMMARY，只返回 seq >= COMPACT_SUMMARY.seq 的数据；
    否则返回全部历史数据。

    这样可以避免加载已被 compact 压缩的旧数据到内存。
    """
    # SQLite 没有 json_contains，使用 json_each 展开数组查询。
    # 取 seq 最大（最新）的一条 COMPACT_SUMMARY：历史可能经历多轮 compact，
    # 恢复应基于最近一次压缩视图，与 persistenceService._trim_to_latest_compact 语义一致。
    compact_summaries = await (
        GtAgentHistory
        .select()
        .where(
            GtAgentHistory.agent_id == agent_id,
            SQL("EXISTS (SELECT 1 FROM json_each(tags) WHERE value = 'COMPACT_SUMMARY')"),
        )
        .order_by(GtAgentHistory.seq.desc())  # type: ignore[attr-defined]
        .limit(1)
        .aio_execute()
    )

    if not compact_summaries:
        # 没有 compact，返回全部数据
        return await get_agent_history(agent_id)

    compact_seq = compact_summaries[0].seq
    return await (
        GtAgentHistory
        .select()
        .where(
            GtAgentHistory.agent_id == agent_id,
            GtAgentHistory.seq >= compact_seq,  # type: ignore[attr-defined]
        )
        .order_by(GtAgentHistory.seq.asc())
        .aio_execute()
    )


async def delete_history_by_team(team_id: int) -> int:
    """删除 Team 下所有 Agent 的历史记录，返回删除数量。"""
    agents = await gtAgentManager.get_team_all_agents(team_id)
    agent_ids = [agent.id for agent in agents if agent.id is not None]
    if not agent_ids:
        return 0
    return await (
        GtAgentHistory
        .delete()
        .where(GtAgentHistory.agent_id.in_(agent_ids))  # type: ignore[attr-defined]
        .aio_execute()
    )


async def delete_history_by_agent(agent_id: int) -> int:
    """删除指定 Agent 的所有历史记录，返回删除数量。"""
    return await (
        GtAgentHistory
        .delete()
        .where(GtAgentHistory.agent_id == agent_id)
        .aio_execute()
    )


async def delete_history_before_seq(agent_id: int, seq: int) -> int:
    """删除指定 Agent 在 seq 之前（不含 COMPACT_SUMMARY 自身）的旧前缀消息。

    compact 成功后调用，物理清理 DB 中已被压缩的旧消息，防止 DB 持续膨胀。
    仅删除 seq < 参数 seq 的记录（COMPACT_SUMMARY 在该 seq 或之后）。
    """
    return await (
        GtAgentHistory
        .delete()
        .where(
            GtAgentHistory.agent_id == agent_id,
            GtAgentHistory.seq < seq,
        )
        .aio_execute()
    )
