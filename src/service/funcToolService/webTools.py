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


def _get_all_search_keys() -> dict[str, str]:
    """获取所有已配置的搜索 API Key。

    返回 {engine: api_key} 字典，engine 为 "tavily" 或 "brave"。
    同时从环境变量和 setting.json provider_params 收集。
    """
    keys: dict[str, str] = {}

    # 环境变量
    tavily_env = os.environ.get("TAVILY_API_KEY")
    if tavily_env:
        keys["tavily"] = tavily_env
    brave_env = os.environ.get("BRAVE_API_KEY")
    if brave_env:
        keys["brave"] = brave_env

    # setting.json provider_params
    try:
        from util import configUtil
        setting = configUtil.get_app_config().setting
        for svc in setting.llm_services:
            params = svc.provider_params or {}
            tavily = params.get("tavily_api_key")
            if tavily and "tavily" not in keys:
                keys["tavily"] = str(tavily)
            brave = params.get("brave_api_key")
            if brave and "brave" not in keys:
                keys["brave"] = str(brave)
    except Exception:
        pass

    return keys


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
    """使用 Brave Search API 搜索。失败时回退到 Bing。"""
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

    try:
        session = _get_session()
        async with session.get(_BRAVE_SEARCH_URL, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
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
            logger.warning("Brave 搜索返回 HTTP %d，回退到 Bing", resp.status)
    except Exception as e:
        logger.warning("Brave 搜索异常，回退到 Bing: %s", e)

    # 回退到 Bing 搜索
    return await _bing_search(query, count)


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
    all_keys = _get_all_search_keys()

    # 引擎优先级：Tavily（有综合答案，质量最好）> Brave > Bing（无需 Key）
    engines_to_try: list[tuple[str, str]] = []
    if "tavily" in all_keys:
        engines_to_try.append(("tavily", all_keys["tavily"]))
    if "brave" in all_keys:
        engines_to_try.append(("brave", all_keys["brave"]))

    # 依次尝试每个引擎
    errors: list[str] = []
    for engine_name, api_key in engines_to_try:
        try:
            if engine_name == "tavily":
                result = await _tavily_search(query, count, api_key)
            else:
                result = await _brave_search(query, count, api_key, freshness)
            if result.get("success"):
                logger.info("web_search 成功（引擎=%s）: query=%s", engine_name, query[:50])
                return result
            errors.append(f"{engine_name}: {result.get('message', 'unknown')}")
        except Exception as e:
            errors.append(f"{engine_name}: {e}")
            logger.warning("web_search 引擎 %s 失败: %s", engine_name, e)
            continue

    # 所有 API 引擎都失败，回退到 Bing（无需 Key）
    logger.info("web_search 所有 API 引擎失败，回退到 Bing: query=%s", query[:50])
    result = await _bing_search(query, count)
    if result.get("success"):
        return result

    return {
        "success": False,
        "message": f"所有搜索引擎均失败。错误详情: {'; '.join(errors)}",
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

    # 检查是否有 Tavily Key（用于 Extract API）
    all_keys = _get_all_search_keys()
    tavily_key = all_keys.get("tavily")

    # 如果有 Tavily Key，优先用 Tavily Extract
    if tavily_key:
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
                        MAX_CONTENT_LENGTH = 8000
                        truncated = len(raw_content) > MAX_CONTENT_LENGTH
                        display_content = raw_content[:MAX_CONTENT_LENGTH] + (
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
        except Exception as e:
            logger.warning("Tavily Extract 异常，回退到直接抓取: %s", e)

    # 直接 HTTP GET + HTML 清洗（适用于 Brave 或无 Tavily 的场景）
    try:
        session = _get_session()
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; DigitalLifeBot/1.0)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                text = await resp.text()
                return {
                    "success": False,
                    "message": f"网页抓取失败 (HTTP {resp.status}): {text[:200]}",
                }
            html = await resp.text(errors="replace")
    except Exception as e:
        logger.warning("直接抓取网页异常: %s", e)
        return {"success": False, "message": f"网页抓取请求异常: {e}"}

    # HTML 清洗为纯文本
    raw_content = _strip_html(html)

    # 截断过长的内容
    MAX_CONTENT_LENGTH = 8000
    truncated = len(raw_content) > MAX_CONTENT_LENGTH
    display_content = raw_content[:MAX_CONTENT_LENGTH] + (
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
