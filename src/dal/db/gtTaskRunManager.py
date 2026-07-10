from __future__ import annotations

from datetime import datetime
from typing import Any

from constants import TaskRunStatus
from model.dbModel.gtTaskRun import GtTaskRun


_UPDATABLE_FIELDS = {
    "status", "progress_percent", "total_rooms", "active_rooms", "completed_rooms",
    "failed_rooms", "total_agents", "active_agents", "started_at", "finished_at",
    "final_message_id", "final_answer", "blog_publish_status", "blog_post_id",
    "blog_post_url", "error_message", "metadata", "title", "query",
}
_ACTIVE_STATUSES = (
    TaskRunStatus.QUEUED,
    TaskRunStatus.PLANNING,
    TaskRunStatus.DISPATCHING,
    TaskRunStatus.DISCUSSING,
    TaskRunStatus.SYNTHESIZING,
    TaskRunStatus.PUBLISHING,
)


async def create_run(run: GtTaskRun) -> GtTaskRun:
    await run.aio_save()
    return run


async def get_run(run_id: int) -> GtTaskRun | None:
    return await GtTaskRun.aio_get_or_none(GtTaskRun.id == run_id)


async def get_run_by_user_message_id(message_id: int) -> GtTaskRun | None:
    return await GtTaskRun.aio_get_or_none(GtTaskRun.user_message_id == message_id)


async def get_current_run(team_id: int, owner_user_id: int | None = None) -> GtTaskRun | None:
    query = GtTaskRun.select().where(
        GtTaskRun.team_id == team_id,
        GtTaskRun.status.in_(_ACTIVE_STATUSES),  # type: ignore[attr-defined]
    )
    if owner_user_id is not None:
        query = query.where(
            (GtTaskRun.owner_user_id == owner_user_id) | GtTaskRun.owner_user_id.is_null(True)  # type: ignore[union-attr]
        )
    active = await query.order_by(GtTaskRun.id.desc()).aio_first()
    if active is not None:
        return active
    latest_query = GtTaskRun.select().where(GtTaskRun.team_id == team_id)
    if owner_user_id is not None:
        latest_query = latest_query.where(
            (GtTaskRun.owner_user_id == owner_user_id) | GtTaskRun.owner_user_id.is_null(True)  # type: ignore[union-attr]
        )
    return await latest_query.order_by(GtTaskRun.id.desc()).aio_first()


async def get_latest_run_for_room(room_id: int, *, include_terminal: bool = False) -> GtTaskRun | None:
    query = GtTaskRun.select().where(GtTaskRun.root_room_id == room_id)
    if not include_terminal:
        query = query.where(GtTaskRun.status.in_(_ACTIVE_STATUSES))  # type: ignore[attr-defined]
    return await query.order_by(GtTaskRun.id.desc()).aio_first()


async def list_runs(team_id: int, limit: int = 50, owner_user_id: int | None = None) -> list[GtTaskRun]:
    query = GtTaskRun.select().where(GtTaskRun.team_id == team_id)
    if owner_user_id is not None:
        query = query.where(
            (GtTaskRun.owner_user_id == owner_user_id) | GtTaskRun.owner_user_id.is_null(True)  # type: ignore[union-attr]
        )
    return list(await query.order_by(GtTaskRun.id.desc()).limit(limit).aio_execute())


async def update_run(run_id: int, **fields: Any) -> GtTaskRun:
    invalid = set(fields) - _UPDATABLE_FIELDS
    if invalid:
        raise ValueError(f"不允许更新 TaskRun 字段: {sorted(invalid)}")
    if "progress_percent" in fields:
        fields["progress_percent"] = max(0, min(100, int(fields["progress_percent"])))
    if not fields:
        row = await get_run(run_id)
        if row is None:
            raise RuntimeError(f"TaskRun not found: {run_id}")
        return row
    await GtTaskRun.update(**fields).where(GtTaskRun.id == run_id).aio_execute()
    row = await get_run(run_id)
    if row is None:
        raise RuntimeError(f"TaskRun not found after update: {run_id}")
    return row


async def delete_runs_by_team(team_id: int) -> int:
    return await GtTaskRun.delete().where(GtTaskRun.team_id == team_id).aio_execute()
