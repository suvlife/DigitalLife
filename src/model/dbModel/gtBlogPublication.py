from __future__ import annotations

import datetime
import peewee

from .base import DbModelBase, JsonField


class GtBlogPublication(DbModelBase):
    """Ghost publication outbox row.

    publication_key is the idempotency key for one final conclusion. The full
    Markdown is retained so a failed publish can resume after process restart.
    """

    publication_key: str = peewee.CharField(unique=True)
    source_type: str = peewee.CharField(default="FINAL_CONCLUSION")
    source_id: str = peewee.CharField()
    team_id: int | None = peewee.IntegerField(null=True)
    room_id: int | None = peewee.IntegerField(null=True)
    run_id: int | None = peewee.IntegerField(null=True, index=True)
    title: str = peewee.TextField()
    markdown_content: str = peewee.TextField()
    content_hash: str = peewee.CharField()
    tags: list[str] = JsonField(default=list)
    status: str = peewee.CharField(default="PENDING")
    attempt_count: int = peewee.IntegerField(default=0)
    next_retry_at: datetime.datetime | None = peewee.DateTimeField(null=True)
    ghost_post_id: str | None = peewee.CharField(null=True)
    post_url: str | None = peewee.TextField(null=True)
    last_error: str = peewee.TextField(default="")

    class Meta:
        table_name = "blog_publications"
        indexes = (
            (("status", "next_retry_at", "id"), False),
            (("source_type", "source_id"), False),
        )
