from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service import ghostService


@pytest.mark.asyncio
async def test_worker_marks_publication_and_run_published(monkeypatch) -> None:
    import dal.db
    manager = SimpleNamespace(mark_published=AsyncMock(), mark_retry=AsyncMock())
    monkeypatch.setattr(dal.db, "gtBlogPublicationManager", manager, raising=False)
    config = SimpleNamespace(setting=SimpleNamespace(ghost=SimpleNamespace(
        api_url="https://blog.example", admin_api_key="secret",
        publish_status="published", max_retry_attempts=3,
    )))
    import util.configUtil as configUtil
    monkeypatch.setattr(configUtil, "get_app_config", lambda: config)
    monkeypatch.setattr(ghostService, "publish_post", AsyncMock(return_value={
        "success": True, "post_id": "post-1", "post_url": "https://blog.example/post/"
    }))
    import service.runService as runService
    update = AsyncMock()
    monkeypatch.setattr(runService, "update_blog_publish_status", update)

    row = SimpleNamespace(
        id=9, title="报告", markdown_content="# 结论", tags=[], run_id=5,
        attempt_count=1,
    )
    await ghostService._process_publication(row)

    manager.mark_published.assert_awaited_once_with(
        9, ghost_post_id="post-1", post_url="https://blog.example/post/"
    )
    update.assert_awaited_once_with(
        run_id=5, status="PUBLISHED", post_id="post-1", post_url="https://blog.example/post/"
    )


@pytest.mark.asyncio
async def test_worker_persists_retry_and_run_status(monkeypatch) -> None:
    import dal.db
    manager = SimpleNamespace(mark_published=AsyncMock(), mark_retry=AsyncMock())
    monkeypatch.setattr(dal.db, "gtBlogPublicationManager", manager, raising=False)
    config = SimpleNamespace(setting=SimpleNamespace(ghost=SimpleNamespace(
        api_url="https://blog.example", admin_api_key="secret",
        publish_status="published", max_retry_attempts=3,
    )))
    import util.configUtil as configUtil
    monkeypatch.setattr(configUtil, "get_app_config", lambda: config)
    monkeypatch.setattr(ghostService, "publish_post", AsyncMock(return_value={
        "success": False, "retryable": True, "message": "temporary"
    }))
    import service.runService as runService
    update = AsyncMock()
    monkeypatch.setattr(runService, "update_blog_publish_status", update)

    row = SimpleNamespace(
        id=9, title="报告", markdown_content="# 结论", tags=[], run_id=5,
        attempt_count=1,
    )
    await ghostService._process_publication(row)

    assert manager.mark_retry.await_args.kwargs["terminal"] is False
    update.assert_awaited_once()
    assert update.await_args.kwargs["status"] == "RETRY_WAITING"
