"""检查 GitHub 最新版本，内存缓存 12 小时。"""

import asyncio
import logging
import re
import time
from typing import Any

import tornado.httpclient

from util import configUtil
from version import __version__

logger = logging.getLogger(__name__)

_GITHUB_RELEASES_URL = "https://api.github.com/repos/suvlife/DigitalLife/releases/latest"
_CACHE_TTL_SECONDS = 12 * 60 * 60  # 12 hours

_cached_result: dict[str, Any] | None = None
_cached_at: float = 0.0
# 防止并发 check_for_update 重复请求 GitHub
_check_lock: asyncio.Lock | None = None


def _parse_version(version_str: str) -> tuple[int, ...]:
    """将 'v0.3.8' 或 '0.3.8' 解析为可比较的元组。

    支持 pre-release 后缀（如 v0.3.8-rc1）：pre-release 排在正式版之后，
    即 (0,3,8,0) < (0,3,8)（正式版），(0,3,8,1) < (0,3,8,2)。
    解析失败返回 (0,0,0) 并记录 warning。
    """
    cleaned = version_str.strip().lstrip("vV")
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:[-+.](\w+))?", cleaned)
    if not match:
        logger.warning("无法解析版本号: %s", version_str)
        return (0, 0, 0)
    major, minor, patch, suffix = match.groups()
    base = (int(major), int(minor), int(patch))
    if suffix:
        # pre-release：用 (0, suffix) 表示，正式版无 suffix 用 (1,) 表示更大
        # (0,3,8,0,"rc1") < (0,3,8,1) 即正式版 > pre-release
        return base + (0, suffix)
    return base + (1,)


def is_newer_version(latest: str, current: str) -> bool:
    """判断 latest 是否比 current 更新。"""
    return _parse_version(latest) > _parse_version(current)


async def check_for_update(force: bool = False) -> dict[str, Any]:
    """检查是否有新版本可用。

    Args:
        force: 为 True 时跳过缓存，强制请求 GitHub。

    Returns:
        {
            "has_update": bool,
            "current_version": str,
            "latest_version": str,
            "release_url": str,
            "release_notes": str,
        }
    """
    global _cached_result, _cached_at

    # dev.latest_release 优先：手动指定版本号，跳过 GitHub API，方便测试更新 UI
    current = __version__
    setting = configUtil.get_app_config().setting
    dev_release = setting.dev.latest_release
    if dev_release:
        return {
            "has_update": is_newer_version(dev_release, current),
            "current_version": current,
            "latest_version": dev_release.lstrip("v"),
            "release_url": "",
            "release_notes": "",
        }

    now = time.time()
    if not force and _cached_result is not None and (now - _cached_at) < _CACHE_TTL_SECONDS:
        return _cached_result

    # 用锁防止并发回源重复请求 GitHub
    global _check_lock
    if _check_lock is None:
        _check_lock = asyncio.Lock()
    async with _check_lock:
        # double-check：持锁后再次检查缓存（可能已被其他协程填充）
        now = time.time()
        if not force and _cached_result is not None and (now - _cached_at) < _CACHE_TTL_SECONDS:
            return _cached_result
        result = await _fetch_github_release()
        _cached_result = result
        _cached_at = now
    return result


async def _fetch_github_release() -> dict[str, Any]:
    """从 GitHub API 获取最新 release 信息。"""
    current = __version__
    fallback = {
        "has_update": False,
        "current_version": current,
        "latest_version": current,
        "release_url": "",
        "release_notes": "",
    }

    try:
        http_client = tornado.httpclient.AsyncHTTPClient()
        request = tornado.httpclient.HTTPRequest(
            url=_GITHUB_RELEASES_URL,
            method="GET",
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "DigitalLife-UpdateChecker",
            },
            request_timeout=10,
        )
        response = await http_client.fetch(request, raise_error=False)

        if response.code != 200:
            logger.warning("GitHub releases API returned %d", response.code)
            return fallback

        import json
        data = json.loads(response.body)
        # 校验响应类型：GitHub 限流/错误时返回非标准结构
        if not isinstance(data, dict):
            logger.warning("GitHub releases API returned non-dict response: %s", type(data).__name__)
            return fallback
        tag_name = str(data.get("tag_name") or "")
        html_url = str(data.get("html_url") or "")
        body = str(data.get("body") or "")

        has_update = is_newer_version(tag_name, current)

        # 对 release_notes 做基本 HTML 转义，防止前端 v-html 渲染时 XSS。
        # GitHub release body 是 Markdown 原文，可能含任意 HTML。
        import html as html_module
        sanitized_notes = html_module.escape(body[:2000]) if body else ""

        return {
            "has_update": has_update,
            "current_version": current,
            "latest_version": tag_name.lstrip("v"),
            "release_url": html_url,
            "release_notes": sanitized_notes,
        }
    except Exception as e:
        logger.warning("Failed to check for updates: %s", e)
        return fallback
