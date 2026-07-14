"""Unit tests for funcToolService.webTools 的多 key 轮询与 web_fetch 字节上限。"""
from types import SimpleNamespace

import pytest

from service.funcToolService import webTools


@pytest.fixture(autouse=True)
def _reset_rotation():
    webTools._search_rotation.clear()
    yield
    webTools._search_rotation.clear()


def test_rotate_single_key_returns_as_is():
    assert webTools._rotate(["only"], "tavily") == ["only"]
    assert webTools._rotate([], "tavily") == []


def test_rotate_advances_offset_each_call():
    keys = ["a", "b", "c"]
    # 每次调用起点前移一位，实现负载分散 + 失败自动切换
    assert webTools._rotate(keys, "tavily") == ["a", "b", "c"]
    assert webTools._rotate(keys, "tavily") == ["b", "c", "a"]
    assert webTools._rotate(keys, "tavily") == ["c", "a", "b"]
    assert webTools._rotate(keys, "tavily") == ["a", "b", "c"]


def test_rotate_offset_is_per_provider():
    webTools._rotate(["a", "b"], "tavily")  # tavily 计数前移一位 -> 1
    # brave 独立计数，首次仍从头开始
    assert webTools._rotate(["x", "y"], "brave") == ["x", "y"]
    # tavily 已前移一位，下一次从 b 开始
    assert webTools._rotate(["a", "b"], "tavily") == ["b", "a"]
    # brave 也前移了一位
    assert webTools._rotate(["x", "y"], "brave") == ["y", "x"]


def test_rotate_never_mutates_input():
    keys = ["a", "b", "c"]
    webTools._rotate(keys, "tavily")
    assert keys == ["a", "b", "c"]


def test_build_search_attempts_expands_all_keys_in_order(monkeypatch):
    monkeypatch.setattr(webTools, "_get_search_config", lambda: None)
    monkeypatch.setattr(
        webTools,
        "_collect_provider_keys",
        lambda: {"tavily": ["t1", "t2"], "brave": ["b1"]},
    )
    attempts = webTools._build_search_attempts()
    # 默认引擎顺序 tavily > brave；每个引擎内展开全部 key
    assert attempts == [("tavily", "t1"), ("tavily", "t2"), ("brave", "b1")]


def test_build_search_attempts_honours_configured_provider_order(monkeypatch):
    cfg = SimpleNamespace(providers=[
        SimpleNamespace(provider="brave", enable=True, api_keys=["b1"]),
        SimpleNamespace(provider="tavily", enable=True, api_keys=["t1"]),
    ])
    monkeypatch.setattr(webTools, "_get_search_config", lambda: cfg)
    monkeypatch.setattr(
        webTools,
        "_collect_provider_keys",
        lambda: {"tavily": ["t1"], "brave": ["b1"]},
    )
    attempts = webTools._build_search_attempts()
    # 用户配置把 brave 放在前面，应优先尝试 brave
    assert attempts[0][0] == "brave"
    assert set(a[0] for a in attempts) == {"brave", "tavily"}


@pytest.mark.asyncio
async def test_web_fetch_passes_max_bytes_and_truncates(monkeypatch):
    """审计 H2：web_fetch 直接抓取路径应传入 max_bytes 并对超长文本截断。"""
    captured = {}

    async def fake_request(method, url, *, headers=None, timeout=None, field_name="", max_bytes=None):
        captured["max_bytes"] = max_bytes
        big_html = "<title>T</title>" + ("A" * 10_000)
        return webTools.safeHttpUtil.SafeHttpResponse(
            status=200, headers={}, body=big_html.encode(), url=url,
        )

    # 无 Tavily key -> 走直接抓取；配置给出小上限便于断言
    monkeypatch.setattr(webTools.safeHttpUtil, "assert_safe_http_url", lambda *a, **k: None)
    monkeypatch.setattr(webTools.safeHttpUtil, "request", fake_request)
    monkeypatch.setattr(webTools, "_collect_provider_keys", lambda: {})
    monkeypatch.setattr(
        webTools, "_get_search_config",
        lambda: SimpleNamespace(max_content_length=50, max_fetch_bytes=4096, providers=[]),
    )

    result = await webTools.web_fetch("https://example.com/page")
    assert result["success"] is True
    assert captured["max_bytes"] == 4096
    assert result["truncated"] is True
    # 截断后展示内容不超过 max_content_length + 提示后缀
    assert len(result["content"]) <= 50 + len("\n\n[内容已截断，完整内容请访问原网页]")


@pytest.mark.asyncio
async def test_web_fetch_uses_default_byte_limit_when_no_config(monkeypatch):
    captured = {}

    async def fake_request(method, url, *, headers=None, timeout=None, field_name="", max_bytes=None):
        captured["max_bytes"] = max_bytes
        return webTools.safeHttpUtil.SafeHttpResponse(
            status=200, headers={}, body=b"<title>t</title>short", url=url,
        )

    monkeypatch.setattr(webTools.safeHttpUtil, "assert_safe_http_url", lambda *a, **k: None)
    monkeypatch.setattr(webTools.safeHttpUtil, "request", fake_request)
    monkeypatch.setattr(webTools, "_collect_provider_keys", lambda: {})
    monkeypatch.setattr(webTools, "_get_search_config", lambda: None)

    result = await webTools.web_fetch("https://example.com/page")
    assert result["success"] is True
    assert captured["max_bytes"] == 5 * 1024 * 1024
