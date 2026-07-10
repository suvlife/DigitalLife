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

    class Response:
        status = 201
        async def text(self):
            return json.dumps({"posts": [{"id": "post-1", "url": "https://blog.example/post/"}]})
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False

    class Session:
        def __init__(self, **kwargs): pass
        def post(self, url, *, json, headers):
            captured.update(url=url, body=json, headers=headers)
            return Response()
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False

    monkeypatch.setattr(ghostService.aiohttp, "ClientSession", Session)
    result = await ghostService.publish_post(
        "报告", "# 完整结论", api_url="https://blog.example",
        admin_api_key="id:" + "ab" * 32,
    )
    assert result["success"] is True
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
