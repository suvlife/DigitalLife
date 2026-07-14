"""TaskRun/RoomRun 生命周期、快照及 MessageBus 集成。"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from constants import (
    AgentActivityStatus,
    AgentActivityType,
    MessageBusTopic,
    RoomRunStatus,
    RoomState,
    SpecialAgent,
    TaskRunStatus,
    TaskStatus,
)
from dal.db import (
    atomic_transaction,
    gtRoomManager,
    gtRoomMessageManager,
    gtRoomRunManager,
    gtTaskRunManager,
    gtTeamManager,
)
from model.dbModel.gtAgentActivity import GtAgentActivity
from model.dbModel.gtAgentTask import GtAgentTask
from model.dbModel.gtRoom import GtRoom
from model.dbModel.gtRoomMessage import GtRoomMessage
from model.dbModel.gtRoomRun import GtRoomRun
from model.dbModel.gtTaskRun import GtTaskRun
from service import messageBus, progressService, ormService
from service.messageBus import EventBusMessage

logger = logging.getLogger(__name__)

_TERMINAL_RUN_STATUSES = {
    TaskRunStatus.COMPLETED,
    TaskRunStatus.PARTIAL_FAILED,
    TaskRunStatus.FAILED,
    TaskRunStatus.CANCELLED,
}
_STARTED_ACTIVITY_TYPES = {
    AgentActivityType.MESSAGE_RECEIVED,
    AgentActivityType.TASK_RECEIVED,
    AgentActivityType.LLM_INFER,
    AgentActivityType.REASONING,
    AgentActivityType.CHAT_REPLY,
    AgentActivityType.TOOL_CALL,
    AgentActivityType.COMPACT,
}
_subscribed = False


def _run_payload(run: GtTaskRun) -> dict[str, Any]:
    return run.to_json()


def _room_run_payload(room_run: GtRoomRun) -> dict[str, Any]:
    return room_run.to_json()


def _title_from_query(query: str) -> str:
    compact = " ".join(query.strip().split())
    return compact[:80] or "新任务"


def _dept_id_from_room(room: GtRoom) -> int | None:
    biz_id = room.biz_id or ""
    if biz_id.startswith("DEPT:"):
        try:
            return int(biz_id.split(":", 1)[1])
        except (ValueError, IndexError):
            return None
    return None


def _fallback_conclusion(messages: list[GtRoomMessage], query: str) -> str:
    """当 root leader 未调用 submit_conclusion 时，仍生成可交付的最低限度报告。

    这不是替代 Agent 综合，而是防止调度已完成却把用户留在空白页面；原始
    发言按时间保留，便于用户继续追问和人工复核。
    """
    substantive = [m for m in messages if m.sender_id > 0 and m.content.strip()]
    if not substantive:
        return ""
    lines = ["# 综合分析报告", "", f"## 问题", query.strip() or "（未记录问题）", "", "## 讨论结论",
             "本轮未收到规范化的综合结论工具调用，以下为各研究室已完成的有效研判记录：", ""]
    for message in substantive:
        speaker = message.sender_display_name or f"Agent {message.sender_id}"
        lines.extend([f"### {speaker}", message.content.strip(), ""])
    lines.extend(["## 后续建议", "请根据上述分组研判结果继续追问，或在下一轮要求首席负责人形成统一决策与行动清单。", ""])
    return "\n".join(lines).strip()


async def _fallback_conclusion_for_run(run: GtTaskRun, room_runs: list[GtRoomRun]) -> str:
    messages: list[GtRoomMessage] = []
    for room_run in room_runs:
        rows, _ = await gtRoomMessageManager.get_room_messages(room_run.room_id)
        messages.extend(rows)
    messages.sort(key=lambda item: (item.send_time or datetime.min, item.id or 0))
    return _fallback_conclusion(messages, run.query)


async def _write_final_report_artifact(run: GtTaskRun, content: str) -> str | None:
    """将最终 Markdown 报告保存到团队 outputs，供 V2/旧版下载。"""
    try:
        from util import configUtil, fileUtil
        team = await gtTeamManager.get_team_by_id(run.team_id)
        if team is None:
            return None
        root = configUtil.get_app_config().setting.workspace_root
        if not root:
            return None
        workdir = Path((team.config or {}).get("working_directory") or os.path.join(root, team.name)).resolve()
        output_dir = (workdir / "outputs").resolve()
        fileUtil.assert_path_within_sandbox(str(output_dir), str(workdir))
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"综合分析报告-run-{run.id}.md"
        target = (output_dir / filename).resolve()
        fileUtil.assert_path_within_sandbox(str(target), str(workdir))
        # Deterministic path + atomic replace makes retries safe and prevents
        # readers from observing a partially written report.
        temp_target = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        temp_target.write_text(content.rstrip() + "\n", encoding="utf-8")
        os.replace(temp_target, target)
        return f"outputs/{filename}"
    except Exception:
        logger.exception("Failed to write final report artifact: run_id=%s", run.id)
        return None


async def startup() -> None:
    global _subscribed
    if _subscribed:
        return
    messageBus.subscribe(MessageBusTopic.ROOM_STATUS_CHANGED, _on_room_status_changed)
    messageBus.subscribe(MessageBusTopic.ROOM_MSG_ADDED, _on_room_message_added)
    messageBus.subscribe(MessageBusTopic.AGENT_ACTIVITY_CHANGED, _on_agent_activity_changed)
    messageBus.subscribe(MessageBusTopic.TASK_CREATED, _on_collaboration_task_changed)
    messageBus.subscribe(MessageBusTopic.TASK_CHANGED, _on_collaboration_task_changed)
    _subscribed = True


def shutdown() -> None:
    global _subscribed
    if not _subscribed:
        return
    messageBus.unsubscribe(MessageBusTopic.ROOM_STATUS_CHANGED, _on_room_status_changed)
    messageBus.unsubscribe(MessageBusTopic.ROOM_MSG_ADDED, _on_room_message_added)
    messageBus.unsubscribe(MessageBusTopic.AGENT_ACTIVITY_CHANGED, _on_agent_activity_changed)
    messageBus.unsubscribe(MessageBusTopic.TASK_CREATED, _on_collaboration_task_changed)
    messageBus.unsubscribe(MessageBusTopic.TASK_CHANGED, _on_collaboration_task_changed)
    _subscribed = False


async def create_run_for_user_message(
    *,
    team_id: int,
    root_room_id: int,
    user_message_id: int,
    query: str,
    owner_user_id: int | None = None,
) -> GtTaskRun:
    existing = await gtTaskRunManager.get_run_by_user_message_id(user_message_id)
    if existing is not None:
        return existing

    now = datetime.now()
    run = GtTaskRun(
        team_id=team_id,
        root_room_id=root_room_id,
        user_message_id=user_message_id,
        owner_user_id=owner_user_id,
        title=_title_from_query(query),
        query=query,
        status=TaskRunStatus.QUEUED,
        progress_percent=0,
        started_at=now,
    )
    created_room_runs: list[GtRoomRun] = []
    try:
        async with atomic_transaction():
            run = await gtTaskRunManager.create_run(run)
            # 初始只绑定真实根房间。周边房间在被该 Run 明确调度/产生带
            # run_id 的事件时再建立关联，避免同团队并发 Run 预先共享全部房间。
            root_room = await gtRoomManager.get_room_by_id(root_room_id)
            if root_room is None or root_room.team_id != team_id:
                raise ValueError(f"root room {root_room_id} does not belong to team {team_id}")
            created_room_runs.append(await gtRoomRunManager.upsert_room_run(
                run_id=run.id,
                team_id=team_id,
                room_id=root_room.id,
                dept_id=_dept_id_from_room(root_room),
                expected_contributors=len([
                    aid for aid in (root_room.agent_ids or []) if SpecialAgent.value_of(aid) is None
                ]),
                status=RoomRunStatus.QUEUED,
            ))
    except Exception:
        # user_message_id 唯一索引保证重复请求幂等。
        existing = await gtTaskRunManager.get_run_by_user_message_id(user_message_id)
        if existing is not None:
            return existing
        raise

    # 事务提交后再广播，订阅方永远只能看到完整快照。
    for room_run in created_room_runs:
        messageBus.publish(MessageBusTopic.ROOM_RUN_CHANGED, run_id=run.id, room_run=_room_run_payload(room_run))
    messageBus.publish(MessageBusTopic.RUN_CREATED, run=_run_payload(run))
    return await refresh_run_progress(run.id)


async def get_run(run_id: int) -> GtTaskRun | None:
    return await gtTaskRunManager.get_run(run_id)


async def get_current_run(team_id: int, owner_user_id: int | None = None) -> GtTaskRun | None:
    return await gtTaskRunManager.get_current_run(team_id, owner_user_id=owner_user_id)


async def list_runs(team_id: int, *, limit: int = 50, owner_user_id: int | None = None) -> list[GtTaskRun]:
    return await gtTaskRunManager.list_runs(team_id, limit=limit, owner_user_id=owner_user_id)


async def list_room_runs(run_id: int) -> list[GtRoomRun]:
    return await gtRoomRunManager.list_room_runs(run_id)


async def get_run_snapshot(run_id: int) -> dict[str, Any] | None:
    run = await get_run(run_id)
    if run is None:
        return None
    room_runs = await list_room_runs(run_id)
    return {
        "run": _run_payload(run),
        "rooms": [_room_run_payload(room_run) for room_run in room_runs],
    }


async def get_timeline(run_id: int, *, limit: int = 200) -> list[dict[str, Any]]:
    room_runs = await list_room_runs(run_id)
    room_ids = [room.room_id for room in room_runs]
    if not room_ids:
        return []
    run = await get_run(run_id)
    if run is None:
        return []
    query = GtRoomMessage.select().where(
        GtRoomMessage.room_id.in_(room_ids),  # type: ignore[attr-defined]
        GtRoomMessage.send_time >= (run.started_at or run.created_at),
    )
    if run.finished_at is not None:
        query = query.where(GtRoomMessage.send_time <= run.finished_at)
    rows = await (
        query
        .order_by(GtRoomMessage.id.desc())
        .limit(max(1, min(limit, 500)))
        .aio_execute()
    )
    return [row.to_json() for row in reversed(rows)]


async def refresh_run_progress(run_id: int, *, publish: bool = True) -> GtTaskRun:
    run = await gtTaskRunManager.get_run(run_id)
    if run is None:
        raise RuntimeError(f"TaskRun not found: {run_id}")
    if run.status in _TERMINAL_RUN_STATUSES and run.final_answer:
        # 同一 Run 的最终结论是幂等终态；重复消息/迟到回调不能再次入队发布。
        return run
    room_runs = await gtRoomRunManager.list_room_runs(run_id)
    snapshot = progressService.calculate_run_snapshot(run, room_runs)
    changed = any(getattr(run, key) != value for key, value in snapshot.items())
    if changed:
        run = await gtTaskRunManager.update_run(run_id, **snapshot)
    if publish and changed:
        messageBus.publish(MessageBusTopic.RUN_PROGRESS_CHANGED, run=_run_payload(run))
    return run


async def set_run_status(
    run_id: int,
    status: TaskRunStatus,
    *,
    error_message: str | None = None,
    publish: bool = True,
) -> GtTaskRun:
    fields: dict[str, Any] = {"status": status}
    run = await gtTaskRunManager.get_run(run_id)
    if run is None:
        raise RuntimeError(f"TaskRun not found: {run_id}")
    if run.started_at is None:
        fields["started_at"] = datetime.now()
    if status in _TERMINAL_RUN_STATUSES:
        fields["finished_at"] = datetime.now()
        fields["progress_percent"] = 100
    if error_message is not None:
        fields["error_message"] = error_message
    run = await gtTaskRunManager.update_run(run_id, **fields)
    run = await refresh_run_progress(run_id, publish=False)
    if publish:
        messageBus.publish(MessageBusTopic.RUN_PROGRESS_CHANGED, run=_run_payload(run))
    return run


async def update_room_status(
    *,
    run_id: int,
    room: GtRoom,
    status: RoomRunStatus,
    current_agent_id: int | None = None,
    current_activity: str | None = None,
    error_message: str | None = None,
) -> GtRoomRun:
    room_run = await gtRoomRunManager.upsert_room_run(
        run_id=run_id,
        team_id=room.team_id,
        room_id=room.id,
        dept_id=_dept_id_from_room(room),
        expected_contributors=len([aid for aid in (room.agent_ids or []) if SpecialAgent.value_of(aid) is None]),
        status=status,
    )
    fields: dict[str, Any] = {
        "status": status,
        "current_agent_id": current_agent_id,
        "current_activity": current_activity,
        "last_activity_at": datetime.now(),
        "progress_percent": progressService.room_progress_for_status(
            status,
            completed_contributors=room_run.completed_contributors,
            expected_contributors=room_run.expected_contributors,
        ),
    }
    if status in (RoomRunStatus.QUEUED, RoomRunStatus.DISCUSSING, RoomRunStatus.SYNTHESIZING) and room_run.started_at is None:
        fields["started_at"] = datetime.now()
    if status in (RoomRunStatus.COMPLETED, RoomRunStatus.FAILED, RoomRunStatus.SKIPPED):
        fields["finished_at"] = datetime.now()
        fields["current_agent_id"] = None
        fields["current_activity"] = None
    if error_message is not None:
        fields["error_message"] = error_message
    room_run = await gtRoomRunManager.update_room_run(room_run.id, **fields)
    messageBus.publish(MessageBusTopic.ROOM_RUN_CHANGED, run_id=run_id, room_run=_room_run_payload(room_run))
    await refresh_run_progress(run_id)
    return room_run


async def complete_final_answer(
    *,
    run_id: int,
    final_answer: str,
    final_message_id: int | None = None,
) -> GtTaskRun:
    """Persist a final answer as a recoverable, re-entrant transition.

    The report file has a deterministic name and is atomically replaced. All
    TaskRun/RoomRun mutations commit in one SQLite transaction and the bounded
    retry contains database work only. Event delivery is at-least-once snapshot
    delivery; the full conclusion is auto-published to Ghost (source=html, no
    truncation) after the terminal snapshot commits.
    """
    run = await gtTaskRunManager.get_run(run_id)
    if run is None:
        raise RuntimeError(f"TaskRun not found: {run_id}")

    artifact_path = await _write_final_report_artifact(run, final_answer)

    async def persist_terminal_snapshot() -> tuple[GtTaskRun, list[GtRoomRun]]:
        async with atomic_transaction():
            current = await gtTaskRunManager.get_run(run_id)
            if current is None:
                raise RuntimeError(f"TaskRun not found: {run_id}")
            room_runs = await gtRoomRunManager.list_room_runs(run_id)
            metadata = dict(current.metadata or {})
            if artifact_path:
                metadata["final_report_path"] = artifact_path
            failed_rooms = sum(1 for room in room_runs if room.status == RoomRunStatus.FAILED)
            final_status = TaskRunStatus.PARTIAL_FAILED if failed_rooms else TaskRunStatus.COMPLETED
            finished_at = current.finished_at or datetime.now()
            updated_run = await gtTaskRunManager.update_run(
                run_id,
                final_answer=final_answer,
                final_message_id=final_message_id if final_message_id is not None else current.final_message_id,
                status=final_status,
                progress_percent=100,
                finished_at=finished_at,
                metadata=metadata,
            )
            completed_room_runs: list[GtRoomRun] = []
            for room_run in room_runs:
                if room_run.status in (
                    RoomRunStatus.QUEUED, RoomRunStatus.DISCUSSING, RoomRunStatus.SYNTHESIZING
                ):
                    room_run = await gtRoomRunManager.update_room_run(
                        room_run.id,
                        status=RoomRunStatus.COMPLETED,
                        progress_percent=100,
                        current_agent_id=None,
                        current_activity=None,
                        finished_at=room_run.finished_at or finished_at,
                    )
                    completed_room_runs.append(room_run)
            return updated_run, completed_room_runs

    run, completed_room_runs = await ormService.retry_sqlite_locked(persist_terminal_snapshot)

    # Publish only after commit. Consumers receive complete snapshots. Re-entry
    # may deliver the final snapshot again, which is intentional at-least-once
    # delivery and cannot expose a partially committed terminal state.
    for completed_room_run in completed_room_runs:
        messageBus.publish(
            MessageBusTopic.ROOM_RUN_CHANGED,
            run_id=run.id,
            room_run=_room_run_payload(completed_room_run),
        )
    messageBus.publish(
        MessageBusTopic.FINAL_ANSWER_COMPLETED,
        run=_run_payload(run),
        final_answer=final_answer,
    )
    messageBus.publish(MessageBusTopic.RUN_PROGRESS_CHANGED, run=_run_payload(run))

    # 自动发布完整结论到博客（#6）：Ghost 启用且开启自动发布时，把本次 Run 的
    # 完整汇总结论交给 ghostService.publish_run_conclusion，内部以 source=html 整体
    # 提交、全文无截断。发布是终态之后的副作用，失败只记录 blog_publish_status，
    # 不回滚 Run 终态。
    try:
        from service import ghostService
        from util import configUtil
        ghost = configUtil.get_app_config().setting.ghost
        if ghost.enabled and ghost.auto_publish:
            team = await gtTeamManager.get_team_by_id(run.team_id)
            published = await ghostService.publish_run_conclusion(
                run_id=run.id,
                team_name=team.name if team is not None else "",
                title=run.title or "综合分析报告",
                content_markdown=final_answer,
            )
            if published.get("success"):
                run = await update_blog_publish_status(
                    run_id=run.id, status="PUBLISHED", post_url=published.get("url"),
                )
            else:
                run = await update_blog_publish_status(
                    run_id=run.id, status="FAILED",
                    error_message=str(published.get("error") or "Ghost 发布失败"),
                )
    except Exception as exc:
        logger.exception("Failed to auto-publish run conclusion to Ghost: run_id=%s", run.id)
        run = await update_blog_publish_status(run_id=run.id, status="FAILED", error_message=str(exc))
    return run


async def update_blog_publish_status(
    *, run_id: int, status: str, post_id: str | None = None,
    post_url: str | None = None, error_message: str | None = None,
) -> GtTaskRun:
    """Ghost worker 可调用的薄接口；本模块不实现 Ghost 逻辑。"""
    current = await gtTaskRunManager.get_run(run_id)
    if current is None:
        raise RuntimeError(f"TaskRun not found: {run_id}")
    metadata = dict(current.metadata or {})
    if error_message is not None:
        metadata["blog_publish_error"] = error_message
    elif status == "PUBLISHED":
        metadata.pop("blog_publish_error", None)
    fields: dict[str, Any] = {"blog_publish_status": status, "metadata": metadata}
    if post_id is not None:
        fields["blog_post_id"] = post_id
    if post_url is not None:
        fields["blog_post_url"] = post_url
    run = await gtTaskRunManager.update_run(run_id, **fields)
    messageBus.publish(
        MessageBusTopic.BLOG_PUBLISH_CHANGED,
        run_id=run_id,
        status=status,
        post_id=post_id,
        post_url=post_url,
        error_message=error_message,
    )
    return run


async def _find_active_run_for_room(room: GtRoom, *, run_id: int | None = None) -> GtTaskRun | None:
    """按明确 run-room 关联定位 Run，绝不按团队“最新 Run”猜测。

    新事件应携带 run_id。为兼容旧的单 Run 事件源：若房间已有且仅有一个
    活动关联，或团队当前只有一个活动 Run，允许确定性绑定；出现两个及以上
    候选时返回 None，宁可忽略无法归属的事件，也不能把数据串入另一 Run。
    """
    if run_id is not None:
        run = await gtTaskRunManager.get_run(int(run_id))
        if run is None or run.team_id != room.team_id or run.status in _TERMINAL_RUN_STATUSES:
            return None
        await gtRoomRunManager.upsert_room_run(
            run_id=run.id, team_id=room.team_id, room_id=room.id,
            dept_id=_dept_id_from_room(room),
            expected_contributors=len([
                aid for aid in (room.agent_ids or []) if SpecialAgent.value_of(aid) is None
            ]),
            status=RoomRunStatus.WAITING,
        )
        return run

    associations = await gtRoomRunManager.list_active_runs_for_room(room.id)
    if len(associations) == 1:
        return await gtTaskRunManager.get_run(associations[0].run_id)
    if len(associations) > 1:
        logger.warning("Ambiguous active Run for room_id=%s; event ignored", room.id)
        return None

    active_runs = await gtTaskRunManager.list_active_runs_for_team(room.team_id)
    if len(active_runs) != 1:
        if active_runs:
            logger.warning("Missing explicit run_id for room_id=%s with %s active Runs", room.id, len(active_runs))
        return None
    run = active_runs[0]
    await gtRoomRunManager.upsert_room_run(
        run_id=run.id, team_id=room.team_id, room_id=room.id,
        dept_id=_dept_id_from_room(room),
        expected_contributors=len([
            aid for aid in (room.agent_ids or []) if SpecialAgent.value_of(aid) is None
        ]),
        status=RoomRunStatus.WAITING,
    )
    return run


async def _on_room_status_changed(msg: EventBusMessage) -> None:
    room: GtRoom = msg.payload["gt_room"]
    run = await _find_active_run_for_room(room, run_id=msg.payload.get("run_id"))
    if run is None or run.status in _TERMINAL_RUN_STATUSES:
        return
    state = msg.payload.get("state")
    current_agent_id = msg.payload.get("current_turn_agent_id")
    if state == RoomState.SCHEDULING:
        if run.status in (TaskRunStatus.QUEUED, TaskRunStatus.PLANNING, TaskRunStatus.DISPATCHING):
            await set_run_status(run.id, TaskRunStatus.DISCUSSING)
        await update_room_status(
            run_id=run.id,
            room=room,
            status=RoomRunStatus.DISCUSSING,
            current_agent_id=current_agent_id,
            current_activity="WAITING" if current_agent_id is not None else "DISCUSSING",
        )
    elif state == RoomState.IDLE:
        room_run = await gtRoomRunManager.get_room_run(run.id, room.id)
        if room_run is not None and room_run.started_at is not None:
            # 根房间必须等待明确最终结论；普通房间 IDLE 即表示该讨论周期结束。
            status = RoomRunStatus.SYNTHESIZING if room.id == run.root_room_id and not run.final_answer else RoomRunStatus.COMPLETED
            await update_room_status(run_id=run.id, room=room, status=status)
            if room.id == run.root_room_id and not run.final_answer:
                # 根房间已经完成用户提问的接收，但尚未产生最终报告。先进入
                # 合议态；若 Agent 没有调用 submit_conclusion，则用实际发言生成
                # 最低限度可交付报告，避免任务永远停在“完成但无输出”。
                await set_run_status(run.id, TaskRunStatus.SYNTHESIZING)
                latest_room_runs = await gtRoomRunManager.list_room_runs(run.id)
                other_active = any(
                    item.room_id != run.root_room_id
                    and item.status in (RoomRunStatus.QUEUED, RoomRunStatus.DISCUSSING, RoomRunStatus.SYNTHESIZING)
                    for item in latest_room_runs
                )
                if not other_active:
                    fallback = await _fallback_conclusion_for_run(run, latest_room_runs)
                    if fallback:
                        await complete_final_answer(run_id=run.id, final_answer=fallback)


async def _on_room_message_added(msg: EventBusMessage) -> None:
    room: GtRoom = msg.payload["gt_room"]
    message: GtRoomMessage = msg.payload["gt_message"]
    run = await _find_active_run_for_room(room, run_id=msg.payload.get("run_id"))
    if run is None or run.status in _TERMINAL_RUN_STATUSES or message.send_time < (run.started_at or run.created_at):
        return
    room_run = await gtRoomRunManager.upsert_room_run(
        run_id=run.id,
        team_id=room.team_id,
        room_id=room.id,
        dept_id=_dept_id_from_room(room),
        expected_contributors=len([aid for aid in (room.agent_ids or []) if SpecialAgent.value_of(aid) is None]),
        status=RoomRunStatus.DISCUSSING,
    )
    room_run = await gtRoomRunManager.update_room_run(
        room_run.id,
        message_count=room_run.message_count + 1,
        last_activity_at=datetime.now(),
    )
    messageBus.publish(MessageBusTopic.ROOM_RUN_CHANGED, run_id=run.id, room_run=_room_run_payload(room_run))
    # 兼容现有 submit_conclusion 文本协议；正式结论入口也可直接调用 complete_final_answer。
    if message.content.startswith("【综合结论】") and message.sender_id != SpecialAgent.OPERATOR.value:
        await complete_final_answer(run_id=run.id, final_answer=message.content, final_message_id=message.id)


def _activity_label(activity: GtAgentActivity) -> str:
    if activity.activity_type == AgentActivityType.MESSAGE_RECEIVED:
        return "READING"
    if activity.activity_type in (AgentActivityType.LLM_INFER, AgentActivityType.REASONING):
        meta = activity.metadata or {}
        return "RETRY_WAITING" if meta.get("request_state") == "RETRY_SCHEDULED" else "THINKING"
    if activity.activity_type == AgentActivityType.CHAT_REPLY:
        return "SPEAKING"
    if activity.activity_type == AgentActivityType.TOOL_CALL:
        tool_name = (activity.metadata or {}).get("tool_name", "")
        if tool_name in ("web_search", "web_fetch"):
            return "SEARCHING"
        if tool_name in ("write_file", "edit_file"):
            return "WRITING"
        return "USING_TOOL"
    if activity.activity_type == AgentActivityType.COMPACT:
        return "REVIEWING"
    return "WORKING"


async def _on_agent_activity_changed(msg: EventBusMessage) -> None:
    activity: GtAgentActivity = msg.payload["activity"]
    if activity.activity_type not in _STARTED_ACTIVITY_TYPES:
        return
    room_id = (activity.metadata or {}).get("task_room_id")
    if not room_id:
        return
    room = await gtRoomManager.get_room_by_id(int(room_id))
    if room is None:
        return
    run = await _find_active_run_for_room(room, run_id=msg.payload.get("run_id"))
    if run is None or run.status in _TERMINAL_RUN_STATUSES:
        return
    if run.status in (TaskRunStatus.QUEUED, TaskRunStatus.PLANNING, TaskRunStatus.DISPATCHING):
        run = await set_run_status(run.id, TaskRunStatus.DISCUSSING)
    room_run = await gtRoomRunManager.upsert_room_run(
        run_id=run.id,
        team_id=room.team_id,
        room_id=room.id,
        dept_id=_dept_id_from_room(room),
        expected_contributors=len([aid for aid in (room.agent_ids or []) if SpecialAgent.value_of(aid) is None]),
        status=RoomRunStatus.DISCUSSING,
    )
    fields: dict[str, Any] = {"last_activity_at": datetime.now()}
    if activity.status == AgentActivityStatus.STARTED:
        fields.update(
            status=RoomRunStatus.DISCUSSING,
            current_agent_id=activity.agent_id,
            current_activity=_activity_label(activity),
            started_at=room_run.started_at or datetime.now(),
        )
    else:
        metadata = dict(room_run.metadata or {})
        completed_agent_ids = {int(agent_id) for agent_id in metadata.get("completed_agent_ids", [])}
        if activity.status == AgentActivityStatus.SUCCEEDED and activity.activity_type == AgentActivityType.CHAT_REPLY:
            completed_agent_ids.add(activity.agent_id)
        completed = len(completed_agent_ids)
        if room_run.expected_contributors:
            completed = min(room_run.expected_contributors, completed)
        metadata["completed_agent_ids"] = sorted(completed_agent_ids)
        fields["metadata"] = metadata
        fields.update(
            completed_contributors=completed,
            current_agent_id=None if room_run.current_agent_id == activity.agent_id else room_run.current_agent_id,
            current_activity=None if room_run.current_agent_id == activity.agent_id else room_run.current_activity,
        )
        if activity.status == AgentActivityStatus.FAILED:
            fields["error_message"] = activity.error_message
    progress = progressService.room_progress_for_status(
        RoomRunStatus.DISCUSSING,
        completed_contributors=int(fields.get("completed_contributors", room_run.completed_contributors)),
        expected_contributors=room_run.expected_contributors,
    )
    fields["progress_percent"] = progress
    room_run = await gtRoomRunManager.update_room_run(room_run.id, **fields)
    messageBus.publish(MessageBusTopic.ROOM_RUN_CHANGED, run_id=run.id, room_run=_room_run_payload(room_run))
    await refresh_run_progress(run.id)


async def _on_collaboration_task_changed(msg: EventBusMessage) -> None:
    """将结构化协作任务的真实完成比例折算到对应 RoomRun。"""
    task: GtAgentTask = msg.payload["task"]
    if task.room_id is None:
        return
    room = await gtRoomManager.get_room_by_id(task.room_id)
    if room is None:
        return
    run = await _find_active_run_for_room(room, run_id=msg.payload.get("run_id"))
    if run is None or run.status in _TERMINAL_RUN_STATUSES or task.created_at < (run.started_at or run.created_at):
        return
    room_run = await gtRoomRunManager.upsert_room_run(
        run_id=run.id, team_id=room.team_id, room_id=room.id,
        dept_id=_dept_id_from_room(room),
        expected_contributors=len([aid for aid in (room.agent_ids or []) if SpecialAgent.value_of(aid) is None]),
        status=RoomRunStatus.DISCUSSING,
    )
    tasks = list(await GtAgentTask.select().where(
        GtAgentTask.team_id == run.team_id,
        GtAgentTask.room_id == room.id,
        GtAgentTask.created_at >= (run.started_at or run.created_at),
    ).aio_execute())
    completed = sum(1 for item in tasks if item.status in (TaskStatus.DONE, TaskStatus.CANCELLED))
    failed_or_blocked = sum(1 for item in tasks if item.status == TaskStatus.ON_HOLD)
    ratio = completed / len(tasks) if tasks else 0.0
    progress = min(85, 20 + round(ratio * 65))
    metadata = dict(room_run.metadata or {})
    metadata.update(
        task_total=len(tasks),
        task_completed=completed,
        task_blocked=failed_or_blocked,
    )
    room_run = await gtRoomRunManager.update_room_run(
        room_run.id,
        status=RoomRunStatus.DISCUSSING,
        progress_percent=max(room_run.progress_percent, progress),
        metadata=metadata,
        last_activity_at=datetime.now(),
    )
    if run.status in (TaskRunStatus.QUEUED, TaskRunStatus.PLANNING, TaskRunStatus.DISPATCHING):
        await set_run_status(run.id, TaskRunStatus.DISCUSSING)
    messageBus.publish(MessageBusTopic.ROOM_RUN_CHANGED, run_id=run.id, room_run=_room_run_payload(room_run))
    await refresh_run_progress(run.id)
