from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service import ghostService


@pytest.mark.asyncio
async def test_worker_marks_publication_and_run_published(monkeypatch) -> None:
    import dal.db
    manager = SimpleNamespace(ensure_ghost_slug=AsyncMock(), mark_published=AsyncMock(return_value=True), mark_retry=AsyncMock(return_value=True))
    monkeypatch.setattr(dal.db, "gtBlogPublicationManager", manager, raising=False)
    config = SimpleNamespace(setting=SimpleNamespace(ghost=SimpleNamespace(
        api_url="https://blog.example", admin_api_key="secret",
        publish_status="published", max_retry_attempts=3, skip_ssl_verify=False,
    )))
    import util.configUtil as configUtil
    monkeypatch.setattr(configUtil, "get_app_config", lambda: config)
    monkeypatch.setattr(ghostService, "_publish_to_ghost", AsyncMock(return_value={
        "success": True, "post_id": "post-1", "post_url": "https://blog.example/post/"
    }))
    import service.runService as runService
    update = AsyncMock()
    monkeypatch.setattr(runService, "update_blog_publish_status", update)

    row = SimpleNamespace(
        id=9, publication_key="final-conclusion:run:5", ghost_slug="digitallife-stable",
        worker_token="worker-a", title="报告", markdown_content="# 结论", tags=[], run_id=5,
        attempt_count=1,
    )
    await ghostService._process_publication(row)

    manager.mark_published.assert_awaited_once_with(
        9, worker_token="worker-a", ghost_post_id="post-1", post_url="https://blog.example/post/"
    )
    update.assert_awaited_once_with(
        run_id=5, status="PUBLISHED", post_id="post-1", post_url="https://blog.example/post/"
    )


@pytest.mark.asyncio
async def test_worker_persists_retry_and_run_status(monkeypatch) -> None:
    import dal.db
    manager = SimpleNamespace(ensure_ghost_slug=AsyncMock(), mark_published=AsyncMock(return_value=True), mark_retry=AsyncMock(return_value=True))
    monkeypatch.setattr(dal.db, "gtBlogPublicationManager", manager, raising=False)
    config = SimpleNamespace(setting=SimpleNamespace(ghost=SimpleNamespace(
        api_url="https://blog.example", admin_api_key="secret",
        publish_status="published", max_retry_attempts=3, skip_ssl_verify=False,
    )))
    import util.configUtil as configUtil
    monkeypatch.setattr(configUtil, "get_app_config", lambda: config)
    monkeypatch.setattr(ghostService, "_publish_to_ghost", AsyncMock(return_value={
        "success": False, "retryable": True, "message": "temporary"
    }))
    import service.runService as runService
    update = AsyncMock()
    monkeypatch.setattr(runService, "update_blog_publish_status", update)

    row = SimpleNamespace(
        id=9, publication_key="final-conclusion:run:5", ghost_slug="digitallife-stable",
        worker_token="worker-a", title="报告", markdown_content="# 结论", tags=[], run_id=5,
        attempt_count=1,
    )
    await ghostService._process_publication(row)

    assert manager.mark_retry.await_args.kwargs["terminal"] is False
    update.assert_awaited_once()
    assert update.await_args.kwargs["status"] == "RETRY_WAITING"


@pytest.mark.asyncio
async def test_worker_lost_local_mark_converges_on_retry_without_second_create(monkeypatch) -> None:
    """A post created before a local DB failure is reconciled by stable slug."""
    import dal.db
    manager = SimpleNamespace(
        ensure_ghost_slug=AsyncMock(),
        mark_published=AsyncMock(side_effect=[RuntimeError("database is locked"), True]),
        mark_retry=AsyncMock(return_value=True),
    )
    monkeypatch.setattr(dal.db, "gtBlogPublicationManager", manager, raising=False)
    config = SimpleNamespace(setting=SimpleNamespace(ghost=SimpleNamespace(
        api_url="https://blog.example", admin_api_key="secret",
        publish_status="published", max_retry_attempts=3, skip_ssl_verify=False,
    )))
    import util.configUtil as configUtil
    monkeypatch.setattr(configUtil, "get_app_config", lambda: config)
    publish = AsyncMock(return_value={
        "success": True, "post_id": "post-1", "post_url": "https://blog.example/post/"
    })
    monkeypatch.setattr(ghostService, "_publish_to_ghost", publish)

    first = SimpleNamespace(
        id=9, publication_key="final:9", ghost_slug="digitallife-stable",
        worker_token="worker-a", title="报告", markdown_content="# 结论", tags=[],
        run_id=None, attempt_count=1,
    )
    with pytest.raises(RuntimeError, match="database is locked"):
        await ghostService._process_publication(first)

    retry = SimpleNamespace(**{**first.__dict__, "worker_token": "worker-b", "attempt_count": 2})
    await ghostService._process_publication(retry)

    assert publish.await_count == 2
    assert all(call.kwargs["slug"] == "digitallife-stable" for call in publish.await_args_list)
    assert manager.mark_published.await_args_list[-1].kwargs["worker_token"] == "worker-b"
