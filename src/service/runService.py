"""TaskRun/RoomRun 生命周期、快照及 MessageBus 集成。"""
from __future__ import annotations

import logging
from datetime import datetime
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
from dal.db import gtRoomManager, gtRoomRunManager, gtTaskRunManager
from model.dbModel.gtAgentActivity import GtAgentActivity
from model.dbModel.gtAgentTask import GtAgentTask
from model.dbModel.gtRoom import GtRoom
from model.dbModel.gtRoomMessage import GtRoomMessage
from model.dbModel.gtRoomRun import GtRoomRun
from model.dbModel.gtTaskRun import GtTaskRun
from service import messageBus, progressService
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
    try:
        run = await gtTaskRunManager.create_run(run)
    except Exception:
        # user_message_id 唯一索引保证重复请求幂等。
        existing = await gtTaskRunManager.get_run_by_user_message_id(user_message_id)
        if existing is not None:
            return existing
        raise

    # 预建团队所有可见房间快照，断线恢复时院落能立即展示 WAITING；
    # 根房间进入 QUEUED，其余房间在收到真实消息/状态/活动前保持 WAITING。
    team_rooms = await gtRoomManager.get_rooms_by_team(team_id)
    for team_room in team_rooms:
        room_status = RoomRunStatus.QUEUED if team_room.id == root_room_id else RoomRunStatus.WAITING
        room_run = await gtRoomRunManager.upsert_room_run(
            run_id=run.id,
            team_id=team_id,
            room_id=team_room.id,
            dept_id=_dept_id_from_room(team_room),
            expected_contributors=len([aid for aid in (team_room.agent_ids or []) if SpecialAgent.value_of(aid) is None]),
            status=room_status,
        )
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
    run = await gtTaskRunManager.get_run(run_id)
    if run is None:
        raise RuntimeError(f"TaskRun not found: {run_id}")
    room_runs = await gtRoomRunManager.list_room_runs(run_id)
    failed_rooms = sum(1 for room in room_runs if room.status == RoomRunStatus.FAILED)
    final_status = TaskRunStatus.PARTIAL_FAILED if failed_rooms else TaskRunStatus.COMPLETED
    run = await gtTaskRunManager.update_run(
        run_id,
        final_answer=final_answer,
        final_message_id=final_message_id,
        status=final_status,
        progress_percent=100,
        finished_at=datetime.now(),
    )
    messageBus.publish(
        MessageBusTopic.FINAL_ANSWER_COMPLETED,
        run=_run_payload(run),
        final_answer=final_answer,
    )
    messageBus.publish(MessageBusTopic.RUN_PROGRESS_CHANGED, run=_run_payload(run))

    # Final answer is the only blog publication trigger. Persisting the answer
    # happens before enqueue, so a publish failure never hides or loses it.
    try:
        from service import ghostService
        queued = await ghostService.enqueue_final_conclusion(
            source_id=f"run:{run.id}",
            publication_key=f"final-conclusion:run:{run.id}",
            title=run.title or "综合分析报告",
            question=run.query,
            conclusion=final_answer,
            team_id=run.team_id,
            room_id=run.root_room_id,
            run_id=run.id,
        )
        if queued.get("success"):
            run = await update_blog_publish_status(run_id=run.id, status="PENDING")
    except Exception:
        logger.exception("Failed to enqueue final answer for Ghost publication: run_id=%s", run.id)
    return run


async def update_blog_publish_status(
    *, run_id: int, status: str, post_id: str | None = None,
    post_url: str | None = None, error_message: str | None = None,
) -> GtTaskRun:
    """Ghost worker 可调用的薄接口；本模块不实现 Ghost 逻辑。"""
    fields: dict[str, Any] = {"blog_publish_status": status}
    if post_id is not None:
        fields["blog_post_id"] = post_id
    if post_url is not None:
        fields["blog_post_url"] = post_url
    if error_message is not None:
        fields["error_message"] = error_message
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


async def _find_active_run_for_room(room: GtRoom) -> GtTaskRun | None:
    # 根房间直接匹配；周边房间使用同团队最新活动 Run，支持 Agent 跨房间协作。
    run = await gtTaskRunManager.get_latest_run_for_room(room.id)
    if run is not None:
        return run
    return await gtTaskRunManager.get_current_run(room.team_id)


async def _on_room_status_changed(msg: EventBusMessage) -> None:
    room: GtRoom = msg.payload["gt_room"]
    run = await _find_active_run_for_room(room)
    if run is None:
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
                await set_run_status(run.id, TaskRunStatus.SYNTHESIZING)


async def _on_room_message_added(msg: EventBusMessage) -> None:
    room: GtRoom = msg.payload["gt_room"]
    message: GtRoomMessage = msg.payload["gt_message"]
    run = await _find_active_run_for_room(room)
    if run is None or message.send_time < (run.started_at or run.created_at):
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
    run = await _find_active_run_for_room(room)
    if run is None:
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
        completed = room_run.completed_contributors
        if activity.status == AgentActivityStatus.SUCCEEDED and activity.activity_type == AgentActivityType.CHAT_REPLY:
            completed = min(room_run.expected_contributors, completed + 1) if room_run.expected_contributors else completed + 1
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
    run = await _find_active_run_for_room(room)
    if run is None or task.created_at < (run.started_at or run.created_at):
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
