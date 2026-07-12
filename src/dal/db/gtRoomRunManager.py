from __future__ import annotations

from typing import Any

from constants import RoomRunStatus
from model.dbModel.gtRoomRun import GtRoomRun


_UPDATABLE_FIELDS = {
    "status", "progress_percent", "current_agent_id", "current_activity", "started_at",
    "finished_at", "message_count", "expected_contributors", "completed_contributors",
    "last_activity_at", "error_message", "metadata", "dept_id",
}


async def create_room_run(room_run: GtRoomRun) -> GtRoomRun:
    await room_run.aio_save()
    return room_run


async def get_room_run(run_id: int, room_id: int) -> GtRoomRun | None:
    return await GtRoomRun.aio_get_or_none(
        GtRoomRun.run_id == run_id,
        GtRoomRun.room_id == room_id,
    )


async def get_room_run_by_id(room_run_id: int) -> GtRoomRun | None:
    return await GtRoomRun.aio_get_or_none(GtRoomRun.id == room_run_id)


async def list_room_runs(run_id: int) -> list[GtRoomRun]:
    return list(await GtRoomRun.select().where(GtRoomRun.run_id == run_id).order_by(GtRoomRun.id).aio_execute())


async def list_active_runs_for_room(room_id: int) -> list[GtRoomRun]:
    """返回仍活跃的 run-room 关联；调用方必须处理 0/多条歧义。"""
    from constants import TaskRunStatus
    from model.dbModel.gtTaskRun import GtTaskRun

    active_statuses = (
        TaskRunStatus.QUEUED, TaskRunStatus.PLANNING, TaskRunStatus.DISPATCHING,
        TaskRunStatus.DISCUSSING, TaskRunStatus.SYNTHESIZING, TaskRunStatus.PUBLISHING,
    )
    query = (
        GtRoomRun.select(GtRoomRun)
        .join(GtTaskRun, on=(GtRoomRun.run_id == GtTaskRun.id))
        .where(GtRoomRun.room_id == room_id, GtTaskRun.status.in_(active_statuses))
        .order_by(GtRoomRun.run_id)
    )
    return list(await query.aio_execute())


async def upsert_room_run(
    *, run_id: int, team_id: int, room_id: int, dept_id: int | None = None,
    expected_contributors: int = 0, status: RoomRunStatus = RoomRunStatus.WAITING,
) -> GtRoomRun:
    existing = await get_room_run(run_id, room_id)
    if existing is not None:
        return existing
    room_run = GtRoomRun(
        run_id=run_id,
        team_id=team_id,
        room_id=room_id,
        dept_id=dept_id,
        expected_contributors=expected_contributors,
        status=status,
    )
    try:
        return await create_room_run(room_run)
    except Exception:
        # 唯一约束竞争时重新读取。
        existing = await get_room_run(run_id, room_id)
        if existing is not None:
            return existing
        raise


async def update_room_run(room_run_id: int, **fields: Any) -> GtRoomRun:
    invalid = set(fields) - _UPDATABLE_FIELDS
    if invalid:
        raise ValueError(f"不允许更新 RoomRun 字段: {sorted(invalid)}")
    if "progress_percent" in fields:
        fields["progress_percent"] = max(0, min(100, int(fields["progress_percent"])))
    if fields:
        await GtRoomRun.update(**fields).where(GtRoomRun.id == room_run_id).aio_execute()
    row = await get_room_run_by_id(room_run_id)
    if row is None:
        raise RuntimeError(f"RoomRun not found: {room_run_id}")
    return row


async def delete_room_runs_by_run(run_id: int) -> int:
    return await GtRoomRun.delete().where(GtRoomRun.run_id == run_id).aio_execute()


async def delete_room_runs_by_team(team_id: int) -> int:
    return await GtRoomRun.delete().where(GtRoomRun.team_id == team_id).aio_execute()
