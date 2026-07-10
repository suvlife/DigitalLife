from __future__ import annotations

from datetime import datetime

import peewee

from constants import RoomRunStatus
from .base import DbModelBase, EnumField, JsonField


class GtRoomRun(DbModelBase):
    """TaskRun 内单个房间的持久化进度快照。"""

    run_id: int = peewee.IntegerField(index=True)
    team_id: int = peewee.IntegerField(index=True)
    room_id: int = peewee.IntegerField(index=True)
    dept_id: int | None = peewee.IntegerField(null=True)
    status: RoomRunStatus = EnumField(RoomRunStatus, default=RoomRunStatus.WAITING)
    progress_percent: int = peewee.IntegerField(default=0)
    current_agent_id: int | None = peewee.IntegerField(null=True)
    current_activity: str | None = peewee.CharField(null=True)
    started_at: datetime | None = peewee.DateTimeField(null=True)
    finished_at: datetime | None = peewee.DateTimeField(null=True)
    message_count: int = peewee.IntegerField(default=0)
    expected_contributors: int = peewee.IntegerField(default=0)
    completed_contributors: int = peewee.IntegerField(default=0)
    last_activity_at: datetime | None = peewee.DateTimeField(null=True)
    error_message: str | None = peewee.TextField(null=True)
    metadata: dict = JsonField(default=dict)

    class Meta:
        table_name = "room_runs"
        indexes = (
            (("run_id", "room_id"), True),
            (("run_id", "status", "id"), False),
        )


__all__ = ["GtRoomRun"]
