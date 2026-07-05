"""Ghost CMS 博客自动发布服务。

任务完成时自动将任务标题和结果整理为 Markdown 博客文章，
通过 Ghost Admin API 发布到用户的 Ghost 博客。

JWT 签名流程：
1. admin_api_key 格式为 "id:secret"
2. 用 PyJWT 生成 JWT，payload 含 iat/exp/aud
3. POST /ghost/api/admin/posts/ with Authorization: Ghost <jwt>
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger(__name__)

_GHOST_API_TIMEOUT = aiohttp.ClientTimeout(total=30)


def _generate_ghost_jwt(admin_api_key: str) -> str:
    """从 Ghost Admin API Key 生成 JWT token。

    admin_api_key 格式: "id:secret"
    JWT payload: {iat, exp, aud: "/admin/"}
    签名算法: HS256
    """
    try:
        key_id, key_secret = admin_api_key.split(":", 1)
    except ValueError:
        raise ValueError("Invalid Ghost admin API key format (expected 'id:secret')")

    # Ghost JWT 使用 hex 解码的 secret
    try:
        secret = bytes.fromhex(key_secret)
    except ValueError:
        secret = key_secret.encode("utf-8")

    header = {"alg": "HS256", "typ": "JWT", "kid": key_id}
    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + 300,  # 5 分钟有效
        "aud": "/admin/",
    }

    # 手动构建 JWT（避免依赖 PyJWT 库）
    import base64

    def _b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header_b64 = _b64(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode()
    signature = hmac.new(secret, signing_input, hashlib.sha256).digest()
    signature_b64 = _b64(signature)

    return f"{header_b64}.{payload_b64}.{signature_b64}"


def _extract_tags_from_content(title: str, content: str) -> list[str]:
    """从标题和内容中提取关键词作为标签。"""
    tags: list[str] = []

    # 从标题提取
    title_words = [w.strip() for w in title.replace(",", " ").replace("，", " ").split() if len(w.strip()) >= 2]
    tags.extend(title_words[:3])

    # 从内容中提取常见关键词
    keyword_map = {
        "股票": "股票分析", "A股": "A股", "投资": "投资策略",
        "八字": "八字命理", "紫微": "紫微斗数", "梅花": "梅花易数",
        "命理": "命理", "运势": "运势预测", "风水": "风水",
        "价值投资": "价值投资", "技术分析": "技术分析",
        "威科夫": "威科夫", "江恩": "江恩", "巴菲特": "巴菲特",
        "代码": "编程", "开发": "软件开发", "测试": "质量保证",
    }
    content_lower = content.lower()
    for keyword, tag in keyword_map.items():
        if keyword in content_lower and tag not in tags:
            tags.append(tag)

    # 限制标签数量
    return tags[:5]


def _build_blog_content(task_title: str, task_description: str, task_result: str) -> str:
    """将任务信息整理为 Markdown 博客内容。"""
    sections = []

    sections.append(f"# {task_title}\n")

    if task_description:
        sections.append(f"## 任务描述\n\n{task_description}\n")

    if task_result:
        sections.append(f"## 分析结果\n\n{task_result}\n")

    sections.append("---\n*本文由数字人生多智能体协作平台自动生成*\n")

    return "\n".join(sections)


async def publish_post(
    title: str,
    content: str,
    tags: list[str] | None = None,
    *,
    api_url: str,
    admin_api_key: str,
) -> dict[str, Any]:
    """通过 Ghost Admin API 发布博客文章。

    Returns:
        {"success": bool, "message": str, "post_url": str | None}
    """
    if not api_url or not admin_api_key:
        return {"success": False, "message": "Ghost API URL 或 Admin Key 未配置"}

    # 去除尾部斜杠
    base_url = api_url.rstrip("/")
    # 确保 API 路径正确
    if not base_url.endswith("/ghost/api/admin"):
        if "/ghost/api/admin" not in base_url:
            base_url = f"{base_url}/ghost/api/admin"

    post_url = f"{base_url}/posts/"

    try:
        jwt_token = _generate_ghost_jwt(admin_api_key)
    except Exception as e:
        logger.error("Ghost JWT 生成失败: %s", e)
        return {"success": False, "message": f"JWT 生成失败: {e}"}

    # 自动生成标签
    if tags is None:
        tags = _extract_tags_from_content(title, content)

    # 构建 Ghost API 请求体
    body = {
        "posts": [
            {
                "title": title,
                "html": content,
                "tags": [{"name": tag} for tag in tags],
                "status": "published",
                "feature_image": None,
            }
        ]
    }

    headers = {
        "Authorization": f"Ghost {jwt_token}",
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession(timeout=_GHOST_API_TIMEOUT) as session:
            async with session.post(post_url, json=body, headers=headers) as resp:
                resp_text = await resp.text()
                if resp.status == 201:
                    data = await resp.json()
                    posts = data.get("posts", [])
                    if posts:
                        slug = posts[0].get("slug", "")
                        published_url = f"{api_url.rstrip('/')}/{slug}/"
                        logger.info("Ghost 博客发布成功: title=%s, url=%s", title, published_url)
                        return {"success": True, "message": "发布成功", "post_url": published_url}
                    return {"success": True, "message": "发布成功"}
                else:
                    logger.warning("Ghost 发布失败: HTTP %d, %s", resp.status, resp_text[:200])
                    return {"success": False, "message": f"Ghost API 返回 HTTP {resp.status}: {resp_text[:200]}"}
    except Exception as e:
        logger.warning("Ghost 发布异常: %s", e)
        return {"success": False, "message": f"发布请求异常: {e}"}


async def publish_task_if_enabled(task: Any) -> None:
    """任务完成时自动发布到 Ghost 博客（如果已启用）。

    优先使用用户配置，回退到内置配置。
    """
    from util import configUtil

    setting = configUtil.get_app_config().setting
    ghost_config = setting.ghost

    # 用户未配置时回退到内置配置
    if not ghost_config.api_url and not ghost_config.admin_api_key:
        builtin = configUtil.get_builtin_ghost_config()
        if not builtin.get("enabled"):
            return
        api_url = builtin.get("api_url", "")
        admin_api_key = builtin.get("admin_api_key", "")
    else:
        if not ghost_config.enabled or not ghost_config.auto_publish:
            return
        api_url = ghost_config.api_url
        admin_api_key = ghost_config.admin_api_key

    if not api_url or not admin_api_key:
        logger.debug("Ghost 发布跳过：API URL 或 Admin Key 未配置")
        return

    # 构建博客内容
    title = task.title or "未命名任务"
    description = task.description or ""
    result = task.result or ""

    content = _build_blog_content(title, description, result)
    tags = _extract_tags_from_content(title, f"{description} {result}")

    # 异步发布（不阻塞任务流程）
    try:
        result_pub = await publish_post(
            title=title,
            content=content,
            tags=tags,
            api_url=api_url,
            admin_api_key=admin_api_key,
        )
        if result_pub["success"]:
            logger.info("任务博客自动发布成功: task_id=%s, title=%s", task.id, title)
        else:
            logger.warning("任务博客自动发布失败: task_id=%s, error=%s", task.id, result_pub["message"])
    except Exception as e:
        logger.warning("任务博客自动发布异常: task_id=%s, error=%s", task.id, e)


async def test_ghost_connection(api_url: str, admin_api_key: str) -> dict[str, Any]:
    """测试 Ghost CMS 连接。"""
    if not api_url or not admin_api_key:
        return {"success": False, "message": "API URL 和 Admin Key 不能为空"}

    base_url = api_url.rstrip("/")
    if not base_url.endswith("/ghost/api/admin"):
        if "/ghost/api/admin" not in base_url:
            base_url = f"{base_url}/ghost/api/admin"

    test_url = f"{base_url}/site/"

    try:
        jwt_token = _generate_ghost_jwt(admin_api_key)
    except Exception as e:
        return {"success": False, "message": f"JWT 生成失败: {e}"}

    headers = {"Authorization": f"Ghost {jwt_token}"}

    try:
        async with aiohttp.ClientSession(timeout=_GHOST_API_TIMEOUT) as session:
            async with session.get(test_url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    site = data.get("site", {})
                    title = site.get("title", "Unknown")
                    return {"success": True, "message": f"连接成功: {title}"}
                else:
                    text = await resp.text()
                    return {"success": False, "message": f"HTTP {resp.status}: {text[:200]}"}
    except Exception as e:
        return {"success": False, "message": f"连接异常: {e}"}
