from __future__ import annotations

import datetime

import pytest

from db import migrate_database
from dal.db import gtBlogPublicationManager as manager
from model.dbModel.base import bind_database
from model.dbModel.gtBlogPublication import GtBlogPublication
from service.ormService import AioSqliteDatabase


@pytest.fixture
async def publication_db(tmp_path):
    path = tmp_path / "claims.db"
    migrate_database(path)
    database = AioSqliteDatabase(str(path), timeout=1)
    bind_database(database)
    await database.aio_connect()
    try:
        yield database
    finally:
        await database.aio_close()


async def _create_row(key: str = "final:1") -> GtBlogPublication:
    return await GtBlogPublication.aio_create(
        publication_key=key,
        source_type="FINAL_CONCLUSION",
        source_id="1",
        title="报告",
        markdown_content="# 结论",
        content_hash="a" * 64,
        tags=[],
        ghost_slug="digitallife-stable",
        status="PENDING",
    )


@pytest.mark.asyncio
async def test_two_workers_cannot_claim_same_publication(publication_db) -> None:
    await _create_row()
    first = await manager.claim_due(worker_token="worker-a", limit=1, lease_seconds=120)
    second = await manager.claim_due(worker_token="worker-b", limit=1, lease_seconds=120)

    assert [row.worker_token for row in first] == ["worker-a"]
    assert second == []


@pytest.mark.asyncio
async def test_recovery_only_releases_expired_lease(publication_db) -> None:
    now = datetime.datetime.now()
    live = await _create_row("final:live")
    expired = await _create_row("final:expired")
    await (
        GtBlogPublication.update(
            status="PUBLISHING", worker_token="live-worker",
            lease_expires_at=now + datetime.timedelta(minutes=1),
        ).where(GtBlogPublication.id == live.id).aio_execute()
    )
    await (
        GtBlogPublication.update(
            status="PUBLISHING", worker_token="dead-worker",
            lease_expires_at=now - datetime.timedelta(seconds=1),
        ).where(GtBlogPublication.id == expired.id).aio_execute()
    )

    assert await manager.recover_interrupted(now=now) == 1
    live = await GtBlogPublication.aio_get(GtBlogPublication.id == live.id)
    expired = await GtBlogPublication.aio_get(GtBlogPublication.id == expired.id)
    assert live.status == "PUBLISHING"
    assert live.worker_token == "live-worker"
    assert expired.status == "RETRY_WAITING"
    assert expired.worker_token is None


@pytest.mark.asyncio
async def test_stale_worker_cannot_finalize_after_lease_reclaimed(publication_db) -> None:
    row = await _create_row()
    claimed = await manager.claim_due(worker_token="worker-a", limit=1, lease_seconds=1)
    assert claimed
    await (
        GtBlogPublication.update(lease_expires_at=datetime.datetime.now() - datetime.timedelta(seconds=1))
        .where(GtBlogPublication.id == row.id).aio_execute()
    )
    reclaimed = await manager.claim_due(worker_token="worker-b", limit=1, lease_seconds=120)
    assert reclaimed and reclaimed[0].worker_token == "worker-b"

    stale_saved = await manager.mark_published(
        row.id, worker_token="worker-a", ghost_post_id="old", post_url="old"
    )
    current_saved = await manager.mark_published(
        row.id, worker_token="worker-b", ghost_post_id="post-1", post_url="https://blog/post/"
    )
    assert stale_saved is False
    assert current_saved is True
    stored = await GtBlogPublication.aio_get(GtBlogPublication.id == row.id)
    assert stored.status == "PUBLISHED"
    assert stored.ghost_post_id == "post-1"
