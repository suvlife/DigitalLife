from __future__ import annotations

import datetime

from model.dbModel.gtBlogPublication import GtBlogPublication


async def get_by_key(publication_key: str) -> GtBlogPublication | None:
    return await GtBlogPublication.aio_get_or_none(
        GtBlogPublication.publication_key == publication_key
    )


async def upsert_pending(
    *,
    publication_key: str,
    source_type: str,
    source_id: str,
    title: str,
    markdown_content: str,
    content_hash: str,
    tags: list[str],
    team_id: int | None = None,
    room_id: int | None = None,
    run_id: int | None = None,
) -> GtBlogPublication:
    row = await get_by_key(publication_key)
    if row is None:
        return await GtBlogPublication.aio_create(
            publication_key=publication_key,
            source_type=source_type,
            source_id=source_id,
            title=title,
            markdown_content=markdown_content,
            content_hash=content_hash,
            tags=tags,
            team_id=team_id,
            room_id=room_id,
            run_id=run_id,
            status="PENDING",
        )

    # A published idempotency key never creates a second post automatically.
    # Explicit post-update support can be added later with Ghost's updated_at CAS.
    if row.status == "PUBLISHED":
        return row

    row.source_type = source_type
    row.source_id = source_id
    row.title = title
    row.markdown_content = markdown_content
    row.content_hash = content_hash
    row.tags = tags
    row.team_id = team_id
    row.room_id = room_id
    row.run_id = run_id
    row.status = "PENDING"
    row.attempt_count = 0
    row.next_retry_at = None
    row.last_error = ""
    row.updated_at = datetime.datetime.now()
    await row.aio_save()
    return row


async def claim_due(limit: int = 10) -> list[GtBlogPublication]:
    now = datetime.datetime.now()
    query = (
        GtBlogPublication.select()
        .where(
            (GtBlogPublication.status.in_(["PENDING", "RETRY_WAITING"]))  # type: ignore[attr-defined]
            & (
                GtBlogPublication.next_retry_at.is_null(True)  # type: ignore[union-attr]
                | (GtBlogPublication.next_retry_at <= now)  # type: ignore[operator]
            )
        )
        .order_by(GtBlogPublication.id.asc())
        .limit(limit)
    )
    rows = list(await query.aio_execute())
    claimed: list[GtBlogPublication] = []
    for row in rows:
        affected = await (
            GtBlogPublication.update(
                status="PUBLISHING",
                attempt_count=row.attempt_count + 1,
                updated_at=now,
            )
            .where(
                GtBlogPublication.id == row.id,
                GtBlogPublication.status.in_(["PENDING", "RETRY_WAITING"]),  # type: ignore[attr-defined]
            )
            .aio_execute()
        )
        if affected:
            row.status = "PUBLISHING"
            row.attempt_count += 1
            claimed.append(row)
    return claimed


async def recover_interrupted() -> int:
    return await (
        GtBlogPublication.update(
            status="RETRY_WAITING",
            next_retry_at=datetime.datetime.now(),
            last_error="publish interrupted by process restart",
            updated_at=datetime.datetime.now(),
        )
        .where(GtBlogPublication.status == "PUBLISHING")
        .aio_execute()
    )


async def mark_published(
    row_id: int, *, ghost_post_id: str | None, post_url: str | None
) -> None:
    await (
        GtBlogPublication.update(
            status="PUBLISHED",
            ghost_post_id=ghost_post_id,
            post_url=post_url,
            next_retry_at=None,
            last_error="",
            updated_at=datetime.datetime.now(),
        )
        .where(GtBlogPublication.id == row_id)
        .aio_execute()
    )


async def mark_retry(
    row_id: int, *, error: str, next_retry_at: datetime.datetime, terminal: bool
) -> None:
    await (
        GtBlogPublication.update(
            status="FAILED" if terminal else "RETRY_WAITING",
            last_error=error[:2000],
            next_retry_at=None if terminal else next_retry_at,
            updated_at=datetime.datetime.now(),
        )
        .where(GtBlogPublication.id == row_id)
        .aio_execute()
    )
