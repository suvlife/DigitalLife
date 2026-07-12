from __future__ import annotations

import datetime

from peewee import IntegrityError
from model.dbModel.gtBlogPublication import GtBlogPublication


def _now() -> datetime.datetime:
    return datetime.datetime.now()


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
    ghost_slug: str | None = None,
    team_id: int | None = None,
    room_id: int | None = None,
    run_id: int | None = None,
) -> GtBlogPublication:
    row = await get_by_key(publication_key)
    if row is None:
        try:
            return await GtBlogPublication.aio_create(
                publication_key=publication_key,
                source_type=source_type,
                source_id=source_id,
                title=title,
                markdown_content=markdown_content,
                content_hash=content_hash,
                tags=tags,
                ghost_slug=ghost_slug,
                team_id=team_id,
                room_id=room_id,
                run_id=run_id,
                status="PENDING",
            )
        except IntegrityError:
            row = await get_by_key(publication_key)
            if row is None:
                raise

    # Published and actively leased rows must not be reset by duplicate enqueue.
    if row.status in {"PUBLISHED", "PUBLISHING"}:
        return row

    row.source_type = source_type
    row.source_id = source_id
    row.title = title
    row.markdown_content = markdown_content
    row.content_hash = content_hash
    row.tags = tags
    row.ghost_slug = row.ghost_slug or ghost_slug
    row.team_id = team_id
    row.room_id = room_id
    row.run_id = run_id
    row.status = "PENDING"
    row.attempt_count = 0
    row.next_retry_at = None
    row.worker_token = None
    row.lease_expires_at = None
    row.last_error = ""
    row.updated_at = _now()
    await row.aio_save()
    return row


async def ensure_ghost_slug(row_id: int, ghost_slug: str) -> None:
    await (
        GtBlogPublication.update(ghost_slug=ghost_slug, updated_at=_now())
        .where(
            GtBlogPublication.id == row_id,
            GtBlogPublication.ghost_slug.is_null(True),  # type: ignore[union-attr]
        )
        .aio_execute()
    )


async def claim_due(
    *, worker_token: str, limit: int = 10, lease_seconds: int = 120
) -> list[GtBlogPublication]:
    now = _now()
    lease_expires_at = now + datetime.timedelta(seconds=max(1, lease_seconds))
    due = (
        (GtBlogPublication.status.in_(["PENDING", "RETRY_WAITING"]))  # type: ignore[attr-defined]
        & (
            GtBlogPublication.next_retry_at.is_null(True)  # type: ignore[union-attr]
            | (GtBlogPublication.next_retry_at <= now)  # type: ignore[operator]
        )
    ) | (
        (GtBlogPublication.status == "PUBLISHING")
        & (
            GtBlogPublication.lease_expires_at.is_null(True)  # type: ignore[union-attr]
            | (GtBlogPublication.lease_expires_at <= now)  # type: ignore[operator]
        )
    )
    rows = list(
        await GtBlogPublication.select()
        .where(due)
        .order_by(GtBlogPublication.id.asc())
        .limit(limit)
        .aio_execute()
    )
    claimed: list[GtBlogPublication] = []
    for row in rows:
        # CAS includes the state observed by this worker. This prevents two
        # processes selecting the same row from both owning it.
        predicate = GtBlogPublication.id == row.id
        if row.status == "PUBLISHING":
            predicate &= GtBlogPublication.status == "PUBLISHING"
            if row.lease_expires_at is None:
                predicate &= GtBlogPublication.lease_expires_at.is_null(True)  # type: ignore[union-attr]
            else:
                predicate &= GtBlogPublication.lease_expires_at == row.lease_expires_at
        else:
            predicate &= GtBlogPublication.status == row.status
            predicate &= (
                GtBlogPublication.worker_token.is_null(True)  # type: ignore[union-attr]
                | (GtBlogPublication.worker_token == "")
            )
        affected = await (
            GtBlogPublication.update(
                status="PUBLISHING",
                attempt_count=row.attempt_count + 1,
                worker_token=worker_token,
                lease_expires_at=lease_expires_at,
                updated_at=now,
            )
            .where(predicate)
            .aio_execute()
        )
        if affected:
            row.status = "PUBLISHING"
            row.attempt_count += 1
            row.worker_token = worker_token
            row.lease_expires_at = lease_expires_at
            claimed.append(row)
    return claimed


async def recover_interrupted(*, now: datetime.datetime | None = None) -> int:
    """Release only expired claims; live workers retain their leases."""
    current = now or _now()
    return await (
        GtBlogPublication.update(
            status="RETRY_WAITING",
            next_retry_at=current,
            worker_token=None,
            lease_expires_at=None,
            last_error="publish lease expired before local completion",
            updated_at=current,
        )
        .where(
            (GtBlogPublication.status == "PUBLISHING")
            & (
                GtBlogPublication.lease_expires_at.is_null(True)  # type: ignore[union-attr]
                | (GtBlogPublication.lease_expires_at <= current)  # type: ignore[operator]
            )
        )
        .aio_execute()
    )


async def mark_published(
    row_id: int,
    *,
    worker_token: str,
    ghost_post_id: str | None,
    post_url: str | None,
) -> bool:
    affected = await (
        GtBlogPublication.update(
            status="PUBLISHED",
            ghost_post_id=ghost_post_id,
            post_url=post_url,
            next_retry_at=None,
            worker_token=None,
            lease_expires_at=None,
            last_error="",
            updated_at=_now(),
        )
        .where(
            GtBlogPublication.id == row_id,
            GtBlogPublication.status == "PUBLISHING",
            GtBlogPublication.worker_token == worker_token,
        )
        .aio_execute()
    )
    return bool(affected)


async def mark_retry(
    row_id: int,
    *,
    worker_token: str,
    error: str,
    next_retry_at: datetime.datetime,
    terminal: bool,
) -> bool:
    affected = await (
        GtBlogPublication.update(
            status="FAILED" if terminal else "RETRY_WAITING",
            last_error=error[:2000],
            next_retry_at=None if terminal else next_retry_at,
            worker_token=None,
            lease_expires_at=None,
            updated_at=_now(),
        )
        .where(
            GtBlogPublication.id == row_id,
            GtBlogPublication.status == "PUBLISHING",
            GtBlogPublication.worker_token == worker_token,
        )
        .aio_execute()
    )
    return bool(affected)


async def delete_publications_by_team(team_id: int) -> int:
    return await GtBlogPublication.delete().where(GtBlogPublication.team_id == team_id).aio_execute()
