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


def _get_search_api_key() -> tuple[str | None, str]:
    """获取搜索 API Key 和引擎类型。

    优先级：Brave（环境变量 BRAVE_API_KEY）> Brave（setting.json provider_params.brave_api_key）
    > Tavily（环境变量 TAVILY_API_KEY）> Tavily（setting.json provider_params.tavily_api_key）

    Returns:
        (api_key, engine) — engine 为 "brave" 或 "tavily"
    """
    # 1. Brave Search（环境变量）
    brave_key = os.environ.get("BRAVE_API_KEY")
    if brave_key:
        return brave_key, "brave"

    try:
        from util import configUtil

        setting = configUtil.get_app_config().setting
        for svc in setting.llm_services:
            params = svc.provider_params or {}
            # Brave（provider_params）
            brave = params.get("brave_api_key")
            if brave:
                return str(brave), "brave"
            # Tavily（provider_params，兼容旧配置）
            tavily = params.get("tavily_api_key")
            if tavily:
                return str(tavily), "tavily"
    except Exception:
        pass

    # 2. Tavily（环境变量，兼容旧配置）
    tavily_key = os.environ.get("TAVILY_API_KEY")
    if tavily_key:
        return tavily_key, "tavily"

    return None, ""


def _strip_html(html: str) -> str:
    """简单的 HTML 标签清洗，提取纯文本。"""
    # 移除 script/style 标签及内容
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # 移除所有 HTML 标签
    text = re.sub(r"<[^>]+>", "", html)
    # 清理多余空白
    text = re.sub(r"\s+", " ", text).strip()
    return text


async def _brave_search(query: str, count: int, api_key: str) -> dict:
    """使用 Brave Search API 搜索。"""
    headers = {
        "X-Subscription-Token": api_key,
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    }
    params = {
        "q": query,
        "count": min(count, 20),
    }

    try:
        session = _get_session()
        async with session.get(_BRAVE_SEARCH_URL, headers=headers, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                return {
                    "success": False,
                    "message": f"Brave 搜索失败 (HTTP {resp.status}): {text[:200]}",
                }
            data = await resp.json()
    except Exception as e:
        logger.warning("Brave 搜索异常: %s", e)
        return {"success": False, "message": f"Brave 搜索请求异常: {e}"}

    # 解析 Brave Search 响应
    web_results = data.get("web", {}).get("results", [])
    simplified = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("description", "") or r.get("extra_snippets", [""])[0] if isinstance(r.get("extra_snippets"), list) else r.get("description", ""),
            "score": 0,
        }
        for r in web_results
    ]

    # Brave 不提供综合答案，用第一条结果的描述作为参考
    answer = simplified[0]["content"] if simplified else ""

    return {
        "success": True,
        "message": f"搜索到 {len(simplified)} 条结果",
        "query": query,
        "answer": answer,
        "results": simplified,
    }


async def _tavily_search(query: str, count: int, api_key: str) -> dict:
    """使用 Tavily API 搜索（兼容旧配置）。"""
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
        async with session.post(_TAVILY_SEARCH_URL, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                return {
                    "success": False,
                    "message": f"Tavily 搜索失败 (HTTP {resp.status}): {text[:200]}",
                }
            data = await resp.json()
    except Exception as e:
        logger.warning("Tavily 搜索异常: %s", e)
        return {"success": False, "message": f"Tavily 搜索请求异常: {e}"}

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
    _context: Optional[ToolCallContext] = None,
) -> dict:
    """搜索网络信息。自动选择 Brave Search 或 Tavily 引擎。

    Args:
        query: 搜索关键词
        count: 返回结果数量，默认 5，最大 20
        search_depth: 搜索深度（Tavily 专用，basic 或 advanced）
        include_answer: 是否返回综合答案
    """
    api_key, engine = _get_search_api_key()
    if not api_key:
        return {
            "success": False,
            "message": "未配置搜索 API Key。请在环境变量 BRAVE_API_KEY 或 setting.json 的 llm_services[].provider_params.brave_api_key 中配置 Brave Search API Key。",
        }

    count = max(1, min(int(count), 20))

    if engine == "brave":
        return await _brave_search(query, count, api_key)
    else:
        return await _tavily_search(query, count, api_key)


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
    api_key, engine = _get_search_api_key()

    # 如果有 Tavily Key，优先用 Tavily Extract
    if api_key and engine == "tavily":
        payload = {
            "api_key": api_key,
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
