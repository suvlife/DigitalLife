from __future__ import annotations

from datetime import datetime

import peewee

from constants import TaskRunStatus
from .base import DbModelBase, EnumField, JsonField


class GtTaskRun(DbModelBase):
    """一次用户问题对应的可恢复运行实例。"""

    team_id: int = peewee.IntegerField(index=True)
    root_room_id: int = peewee.IntegerField(index=True)
    user_message_id: int | None = peewee.IntegerField(null=True, unique=True)
    owner_user_id: int | None = peewee.IntegerField(null=True, index=True)
    title: str = peewee.TextField(default="")
    query: str = peewee.TextField(default="")
    status: TaskRunStatus = EnumField(TaskRunStatus, default=TaskRunStatus.QUEUED)
    progress_percent: int = peewee.IntegerField(default=0)
    total_rooms: int = peewee.IntegerField(default=0)
    active_rooms: int = peewee.IntegerField(default=0)
    completed_rooms: int = peewee.IntegerField(default=0)
    failed_rooms: int = peewee.IntegerField(default=0)
    total_agents: int = peewee.IntegerField(default=0)
    active_agents: int = peewee.IntegerField(default=0)
    started_at: datetime | None = peewee.DateTimeField(null=True)
    finished_at: datetime | None = peewee.DateTimeField(null=True)
    final_message_id: int | None = peewee.IntegerField(null=True)
    final_answer: str = peewee.TextField(default="")
    blog_publish_status: str = peewee.CharField(default="NOT_STARTED")
    blog_post_id: str | None = peewee.CharField(null=True)
    blog_post_url: str | None = peewee.TextField(null=True)
    error_message: str | None = peewee.TextField(null=True)
    metadata: dict = JsonField(default=dict)

    # owner_user_id 属于服务端权限元数据，不向 WebSocket/REST 客户端暴露。
    JSON_EXCLUDE = ["owner_user_id"]

    class Meta:
        table_name = "task_runs"
        indexes = (
            (("team_id", "status", "id"), False),
            (("root_room_id", "id"), False),
        )


__all__ = ["GtTaskRun"]
