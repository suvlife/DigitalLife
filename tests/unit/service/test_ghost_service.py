import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service import ghostService


def _decode_segment(value: str) -> dict:
    value += "=" * (-len(value) % 4)
    return json.loads(base64.urlsafe_b64decode(value))


def test_generate_ghost_jwt_uses_admin_audience_and_key_id() -> None:
    token = ghostService._generate_ghost_jwt("integration-id:" + "ab" * 32)
    header, payload, signature = token.split(".")
    assert _decode_segment(header)["kid"] == "integration-id"
    assert _decode_segment(payload)["aud"] == "/admin/"
    assert signature


@pytest.mark.parametrize("key", ["missing-colon", ":" + "ab" * 32, "id:not-hex"])
def test_generate_ghost_jwt_rejects_invalid_keys(key: str) -> None:
    with pytest.raises(ValueError):
        ghostService._generate_ghost_jwt(key)


def test_markdown_to_safe_html_supports_rich_content_and_escapes_raw_html() -> None:
    rendered = ghostService.markdown_to_safe_html(
        "# 标题\n\n**粗体** [链接](https://example.com) <script>alert(1)</script>\n\n"
        "- [x] 已完成\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n```python\nprint('<x>')\n```"
    )
    assert "<h1>标题</h1>" in rendered
    assert "<strong>粗体</strong>" in rendered
    assert 'rel="noopener noreferrer"' in rendered
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "<table>" in rendered
    assert 'class="language-python"' in rendered
    assert "print(&#x27;&lt;x&gt;&#x27;)" in rendered


def test_markdown_to_safe_html_blocks_javascript_links() -> None:
    rendered = ghostService.markdown_to_safe_html("[bad](javascript:alert(1))")
    assert "javascript:" not in rendered


@pytest.mark.asyncio
async def test_publish_post_uses_source_html_and_never_sends_markdown_as_lexical(monkeypatch) -> None:
    captured = {}

    async def request(method, url, *, headers, json_body, **kwargs):
        captured.update(method=method, url=url, body=json_body, headers=headers)
        return ghostService.safeHttpUtil.SafeHttpResponse(
            status=201, headers={},
            body=json.dumps({"posts": [{"id": "post-1", "url": "https://blog.example/post/"}]}).encode(),
            url=url,
        )

    monkeypatch.setattr(ghostService.safeHttpUtil, "request", request)
    monkeypatch.setattr(ghostService.safeHttpUtil, "assert_safe_http_url", lambda *args, **kwargs: None)
    result = await ghostService.publish_post(
        "报告", "# 完整结论", api_url="https://blog.example",
        admin_api_key="id:" + "ab" * 32,
    )
    assert result["success"] is True
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/ghost/api/admin/posts/?source=html")
    assert "html" in captured["body"]["posts"][0]
    assert "lexical" not in captured["body"]["posts"][0]
    assert captured["headers"]["Accept-Version"] == "v5.0"


@pytest.mark.asyncio
async def test_publish_task_ignores_non_final_tasks() -> None:
    result = await ghostService.publish_task_if_enabled(SimpleNamespace(id=1, result="fragment"))
    assert result["queued"] is False
    assert "最终结论" in result["message"]


@pytest.mark.asyncio
async def test_enqueue_final_conclusion_is_stable_and_wakes_worker(monkeypatch) -> None:
    manager = AsyncMock()
    manager.upsert_pending.return_value = SimpleNamespace(id=7, status="PENDING", post_url=None)
    monkeypatch.setitem(__import__('sys').modules, 'dal.db.gtBlogPublicationManager', manager)
    import dal.db
    monkeypatch.setattr(dal.db, 'gtBlogPublicationManager', manager, raising=False)
    config = SimpleNamespace(setting=SimpleNamespace(ghost=SimpleNamespace(
        enabled=True, auto_publish=True, api_url="https://blog.example", admin_api_key="secret"
    )))
    import util.configUtil as configUtil
    monkeypatch.setattr(configUtil, "get_app_config", lambda: config)
    wake = __import__('unittest.mock').mock.MagicMock()
    monkeypatch.setattr(ghostService, "_wake_worker", wake)

    result = await ghostService.enqueue_final_conclusion(
        source_id="room:1", publication_key="final-conclusion:room:1",
        title="报告", question="问题", conclusion="完整结论", room_id=1,
    )
    assert result["queued"] is True
    kwargs = manager.upsert_pending.await_args.kwargs
    assert kwargs["publication_key"] == "final-conclusion:room:1"
    assert "完整结论" in kwargs["markdown_content"]
    assert len(kwargs["content_hash"]) == 64


@pytest.mark.asyncio
async def test_publish_post_reconciles_existing_slug_with_update(monkeypatch) -> None:
    calls: list[tuple[str, str, dict | None]] = []

    async def request(method, url, *, json_body=None, **kwargs):
        calls.append((method, url, json_body))
        if method == "GET":
            body = {"posts": [{
                "id": "post-1", "slug": "digitallife-stable",
                "updated_at": "2026-07-12T00:00:00.000Z",
                "url": "https://blog.example/stable/",
            }]}
        else:
            body = {"posts": [{"id": "post-1", "url": "https://blog.example/stable/"}]}
        return ghostService.safeHttpUtil.SafeHttpResponse(200, {}, json.dumps(body).encode(), url)

    monkeypatch.setattr(ghostService.safeHttpUtil, "request", request)
    monkeypatch.setattr(ghostService.safeHttpUtil, "assert_safe_http_url", lambda *args, **kwargs: None)
    result = await ghostService.publish_post(
        "报告", "# 新结论", api_url="https://blog.example",
        admin_api_key="id:" + "ab" * 32, slug="digitallife-stable",
    )

    assert result["success"] is True
    assert [method for method, _, _ in calls] == ["GET", "PUT"]
    assert calls[1][2]["posts"][0]["updated_at"] == "2026-07-12T00:00:00.000Z"
    assert calls[1][2]["posts"][0]["slug"] == "digitallife-stable"


@pytest.mark.asyncio
async def test_publish_post_timeout_then_retry_finds_remote_post(monkeypatch) -> None:
    state = {"created": False, "post_calls": 0, "put_calls": 0}

    async def request(method, url, *, json_body=None, **kwargs):
        if method == "GET":
            posts = []
            if state["created"]:
                posts = [{"id": "post-1", "updated_at": "2026-07-12T00:00:00.000Z", "url": "https://blog.example/stable/"}]
            return ghostService.safeHttpUtil.SafeHttpResponse(200, {}, json.dumps({"posts": posts}).encode(), url)
        if method == "POST":
            state["post_calls"] += 1
            state["created"] = True
            raise asyncio.TimeoutError()
        state["put_calls"] += 1
        return ghostService.safeHttpUtil.SafeHttpResponse(200, {}, json.dumps({"posts": [{"id": "post-1", "url": "https://blog.example/stable/"}]}).encode(), url)

    monkeypatch.setattr(ghostService.safeHttpUtil, "request", request)
    monkeypatch.setattr(ghostService.safeHttpUtil, "assert_safe_http_url", lambda *args, **kwargs: None)
    kwargs = dict(
        api_url="https://blog.example", admin_api_key="id:" + "ab" * 32,
        slug="digitallife-stable",
    )
    first = await ghostService.publish_post("报告", "# 结论", **kwargs)
    second = await ghostService.publish_post("报告", "# 结论", **kwargs)

    assert first["success"] is False and first["retryable"] is True
    assert second["success"] is True
    assert state["post_calls"] == 1
    assert state["put_calls"] == 1
