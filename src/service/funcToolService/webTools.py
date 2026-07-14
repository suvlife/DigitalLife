"""Web 搜索与网页抓取工具。

支持两种搜索引擎（按优先级自动选择）：
1. Brave Search API（推荐）— 从环境变量 BRAVE_API_KEY 或 setting.json 读取
2. Tavily API（兼容旧配置）— 从环境变量 TAVILY_API_KEY 或 setting.json 读取

web_fetch 使用 Brave Search 的 URL 内容提取或直接 HTTP 抓取 + HTML 清洗。
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

import aiohttp

from service.roomService import ToolCallContext

from util import safeHttpUtil

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)
_BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
_TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"

# 模块级共享 ClientSession，复用 TCP 连接池
_shared_session: aiohttp.ClientSession | None = None


def _get_session() -> aiohttp.ClientSession:
    """获取共享的 aiohttp ClientSession（lazy init）。"""
    global _shared_session
    if _shared_session is None or _shared_session.closed:
        _shared_session = aiohttp.ClientSession(timeout=_DEFAULT_TIMEOUT)
    return _shared_session


def _get_search_config():
    """读取 setting.search 配置（不可用时返回 None）。"""
    try:
        from util import configUtil
        return configUtil.get_app_config().setting.search
    except Exception:
        return None


# 每个引擎的轮询起始偏移（模块级，多次调用负载分散 + 失败自动切换）
_search_rotation: dict[str, int] = {}


def _rotate(keys: list[str], provider: str) -> list[str]:
    """按轮询顺序返回 keys（每次调用起点前移一位），单 key 时原样返回。"""
    if len(keys) <= 1:
        return list(keys)
    idx = _search_rotation.get(provider, 0) % len(keys)
    _search_rotation[provider] = (idx + 1) % len(keys)
    return keys[idx:] + keys[:idx]


def _collect_provider_keys() -> dict[str, list[str]]:
    """收集每个引擎的所有可用 key（保序去重）。

    来源优先级：setting.search.providers（用户配置）> llm_services.provider_params（旧配置）
              > 环境变量 > 内置默认 key。
    """
    result: dict[str, list[str]] = {}

    def add(provider: str, key: Any) -> None:
        if not provider or not key:
            return
        provider = str(provider).strip().lower()
        key = str(key).strip()
        if not provider or not key:
            return
        lst = result.setdefault(provider, [])
        if key not in lst:
            lst.append(key)

    cfg = _get_search_config()
    if cfg is not None:
        for p in cfg.providers:
            if not getattr(p, "enable", True):
                continue
            for k in p.api_keys:
                add(p.provider, k)

    # 兼容旧配置：llm_services.provider_params
    try:
        from util import configUtil
        setting = configUtil.get_app_config().setting
        for svc in setting.llm_services:
            params = svc.provider_params or {}
            add("tavily", params.get("tavily_api_key"))
            add("brave", params.get("brave_api_key"))
    except Exception:
        pass

    # 环境变量
    add("tavily", os.environ.get("TAVILY_API_KEY"))
    add("brave", os.environ.get("BRAVE_API_KEY"))

    # 内置默认 key（优先级最低）
    try:
        from util import configUtil
        for engine, key in configUtil.get_builtin_search_keys().items():
            add(engine, key)
    except Exception:
        pass

    return result


def _build_search_attempts() -> list[tuple[str, str]]:
    """构造有序的 (provider, key) 尝试列表，支持多 key 轮询与失败自动切换。

    引擎顺序优先采用用户 providers 配置顺序，否则默认 tavily > brave；
    每个引擎内部按轮询顺序展开其全部 key。
    """
    provider_keys = _collect_provider_keys()
    cfg = _get_search_config()

    order: list[str] = []
    if cfg is not None:
        order = [p.provider for p in cfg.providers if getattr(p, "enable", True) and p.provider in provider_keys]
    for eng in ("tavily", "brave"):
        if eng in provider_keys and eng not in order:
            order.append(eng)

    attempts: list[tuple[str, str]] = []
    for provider in order:
        for key in _rotate(provider_keys[provider], provider):
            attempts.append((provider, key))
    return attempts


def _strip_html(html: str) -> str:
    """简单的 HTML 标签清洗，提取纯文本。"""
    # 移除 script/style 标签及内容
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # 移除所有 HTML 标签
    text = re.sub(r"<[^>]+>", "", html)
    # 清理多余空白
    text = re.sub(r"\s+", " ", text).strip()
    return text


async def _brave_search(query: str, count: int, api_key: str, freshness: str = "") -> dict:
    """使用 Brave Search API 搜索。失败时抛出异常供上层轮询下一个 key/引擎。"""
    headers = {
        "X-Subscription-Token": api_key,
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    }
    # 自动在查询词中加入当前年份，确保搜索到最新数据
    from datetime import datetime
    current_year = str(datetime.now().year)
    enhanced_query = query
    if current_year not in query and not freshness:
        freshness = "py"

    params = {
        "q": enhanced_query,
        "count": min(count, 20),
    }
    if freshness:
        params["freshness"] = freshness

    session = _get_session()
    async with session.get(_BRAVE_SEARCH_URL, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise Exception(f"Brave HTTP {resp.status}: {text[:200]}")
        data = await resp.json()

    web_results = data.get("web", {}).get("results", [])
    simplified = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("description", "") or (r.get("extra_snippets", [""])[0] if isinstance(r.get("extra_snippets"), list) else ""),
            "score": 0,
        }
        for r in web_results
    ]
    answer = simplified[0]["content"] if simplified else ""
    return {
        "success": True,
        "message": f"搜索到 {len(simplified)} 条结果（Brave Search）",
        "query": query,
        "answer": answer,
        "results": simplified,
    }


async def _bing_search(query: str, count: int) -> dict:
    """使用 Bing 搜索（直接抓取 HTML 解析结果，无需 API Key）。"""
    from datetime import datetime
    # 在查询词中加入当前年份
    current_year = str(datetime.now().year)
    if current_year not in query:
        enhanced_query = f"{query} {current_year}"
    else:
        enhanced_query = query

    url = "https://www.bing.com/search"
    params = {"q": enhanced_query, "count": str(min(count, 10))}
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    try:
        session = _get_session()
        async with session.get(url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return {"success": False, "message": f"Bing 搜索失败 (HTTP {resp.status})"}
            html = await resp.text(errors="replace")
    except Exception as e:
        logger.warning("Bing 搜索异常: %s", e)
        return {"success": False, "message": f"Bing 搜索请求异常: {e}"}

    # 解析 Bing 搜索结果 HTML
    results = []
    # 匹配搜索结果块
    import re
    # Bing 搜索结果在 <li class="b_algo"> 中
    blocks = re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', html, re.DOTALL)
    for block in blocks[:count]:
        # 提取标题和链接
        title_match = re.search(r'<h2[^>]*><a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.DOTALL)
        if not title_match:
            continue
        link = title_match.group(1)
        title_html = title_match.group(2)
        title = _strip_html(title_html)
        # 提取摘要
        snippet_match = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL)
        snippet = _strip_html(snippet_match.group(1)) if snippet_match else ""
        results.append({
            "title": title,
            "url": link,
            "content": snippet,
            "score": 0,
        })

    answer = results[0]["content"] if results else ""
    engine_name = "Bing" if results else "Bing（无结果）"
    return {
        "success": True,
        "message": f"搜索到 {len(results)} 条结果（{engine_name}）",
        "query": query,
        "answer": answer,
        "results": results,
    }


async def _tavily_search(query: str, count: int, api_key: str) -> dict:
    """使用 Tavily API 搜索。失败时抛出异常供上层回退。"""
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": count,
        "include_answer": True,
        "include_images": False,
        "include_raw_content": False,
    }

    try:
        session = _get_session()
        async with session.post(_TAVILY_SEARCH_URL, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"Tavily HTTP {resp.status}: {text[:200]}")
            data = await resp.json()
    except Exception as e:
        logger.warning("Tavily 搜索异常: %s", e)
        raise

    answer = data.get("answer", "")
    results = data.get("results", [])
    simplified = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
            "score": r.get("score", 0),
        }
        for r in results
    ]

    return {
        "success": True,
        "message": f"搜索到 {len(simplified)} 条结果",
        "query": query,
        "answer": answer,
        "results": simplified,
    }


async def web_search(
    query: str,
    count: int = 5,
    search_depth: str = "basic",
    include_answer: bool = True,
    freshness: str = "",
    _context: Optional[ToolCallContext] = None,
) -> dict:
    """搜索网络信息。三级引擎自动回退：Tavily > Brave > Bing。

    Args:
        query: 搜索关键词
        count: 返回结果数量，默认 5，最大 20
        search_depth: 搜索深度（Tavily 专用，basic 或 advanced）
        include_answer: 是否返回综合答案
        freshness: 时间过滤（Brave 专用）。pd=过去24小时, pw=过去一周, pm=过去一个月,
                   py=过去一年, 空字符串=默认过去一年。
    """
    count = max(1, min(int(count), 20))

    cfg = _get_search_config()
    if cfg is not None and not cfg.enabled:
        return {"success": False, "message": "搜索功能已在系统配置中禁用"}

    # 构造 (provider, key) 尝试序列：多引擎 + 多 key 轮询，失败自动切换
    attempts = _build_search_attempts()

    errors: list[str] = []
    for provider, api_key in attempts:
        try:
            if provider == "tavily":
                result = await _tavily_search(query, count, api_key)
            elif provider == "brave":
                result = await _brave_search(query, count, api_key, freshness)
            else:
                continue
            if result.get("success"):
                logger.info("web_search 成功（引擎=%s）: query=%s", provider, query[:50])
                return result
            errors.append(f"{provider}: {result.get('message', 'unknown')}")
        except Exception as e:
            errors.append(f"{provider}: {e}")
            logger.warning("web_search 引擎 %s 失败，尝试下一个 key/引擎: %s", provider, e)
            continue

    # 所有 API 引擎/key 都失败，回退到 Bing（无需 Key）
    logger.info("web_search 所有 API key 失败，回退到 Bing: query=%s", query[:50])
    result = await _bing_search(query, count)
    if result.get("success"):
        return result

    return {
        "success": False,
        "message": f"所有搜索引擎均失败。错误详情: {'; '.join(errors)}" if errors else "未配置任何搜索引擎 key，且 Bing 兜底失败",
    }


async def web_fetch(
    url: str,
    extract_depth: str = "basic",
    _context: Optional[ToolCallContext] = None,
) -> dict:
    """抓取指定网页的文本内容。

    优先使用 Tavily Extract（如配置了 Tavily Key），否则直接 HTTP GET + HTML 清洗。

    Args:
        url: 要抓取的网页 URL
        extract_depth: 提取深度（Tavily 专用）
    """
    if not url or not url.startswith(("http://", "https://")):
        return {"success": False, "message": "URL 格式不正确，必须以 http:// 或 https:// 开头"}

    # SSRF 防护：校验 URL 不指向内网/元数据地址，防止 Agent 访问内部服务
    try:
        safeHttpUtil.assert_safe_http_url(url, field_name="网页 URL")
    except safeHttpUtil.UnsafeUrlError as e:
        logger.warning("web_fetch SSRF 拦截: url=%s, error=%s", url, e)
        return {"success": False, "message": f"网页 URL 不安全，已拦截: {e}"}

    # 检查是否有 Tavily Key（用于 Extract API），支持多 key 轮询
    cfg = _get_search_config()
    provider_keys = _collect_provider_keys()
    tavily_keys = _rotate(provider_keys.get("tavily", []), "tavily")
    max_content_length = cfg.max_content_length if cfg is not None else 8000
    max_fetch_bytes = cfg.max_fetch_bytes if cfg is not None else 5 * 1024 * 1024

    # 如果有 Tavily Key，优先用 Tavily Extract（逐个 key 轮询）
    for tavily_key in tavily_keys:
        payload = {
            "api_key": tavily_key,
            "urls": [url],
            "extract_depth": extract_depth,
        }
        try:
            session = _get_session()
            async with session.post(_TAVILY_EXTRACT_URL, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    extraction = (data.get("results") or [{}])[0]
                    raw_content = extraction.get("raw_content", "") or extraction.get("content", "")
                    if raw_content:
                        truncated = len(raw_content) > max_content_length
                        display_content = raw_content[:max_content_length] + (
                            "\n\n[内容已截断，完整内容请访问原网页]" if truncated else ""
                        )
                        return {
                            "success": True,
                            "message": "网页抓取成功（Tavily Extract）",
                            "url": url,
                            "title": extraction.get("title", ""),
                            "content": display_content,
                            "truncated": truncated,
                        }
                    break  # 有 key 但无内容，转直接抓取
        except Exception as e:
            logger.warning("Tavily Extract 异常，尝试下一个 key / 回退直接抓取: %s", e)
            continue

    # 直接 HTTP GET + HTML 清洗（适用于 Brave 或无 Tavily 的场景）
    # 使用 safeHttpUtil 进行 SSRF 防护：DNS pinning、内网/元数据地址拦截、重定向逐跳验证
    # 并通过 max_bytes 限制响应体大小，防止超大响应耗尽内存（审计 H2）
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; DigitalLifeBot/1.0)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        response = await safeHttpUtil.request(
            "GET",
            url,
            headers=headers,
            timeout=30,
            field_name="网页 URL",
            max_bytes=max_fetch_bytes,
        )
        if response.status != 200:
            return {
                "success": False,
                "message": f"网页抓取失败 (HTTP {response.status}): {response.text[:200]}",
            }
        html = response.text
    except safeHttpUtil.UnsafeUrlError as e:
        logger.warning("web_fetch SSRF 拦截（直接抓取）: url=%s, error=%s", url, e)
        return {"success": False, "message": f"网页 URL 不安全，已拦截: {e}"}
    except Exception as e:
        logger.warning("直接抓取网页异常: %s", e)
        return {"success": False, "message": f"网页抓取请求异常: {e}"}

    # HTML 清洗为纯文本
    raw_content = _strip_html(html)

    # 截断过长的内容
    truncated = len(raw_content) > max_content_length
    display_content = raw_content[:max_content_length] + (
        "\n\n[内容已截断，完整内容请访问原网页]" if truncated else ""
    )

    # 尝试从 HTML 中提取 title
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title = title_match.group(1).strip() if title_match else ""

    return {
        "success": True,
        "message": "网页抓取成功",
        "url": url,
        "title": title,
        "content": display_content,
        "truncated": truncated,
    }
