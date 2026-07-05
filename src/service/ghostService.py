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


def _markdown_to_lexical(markdown_text: str) -> str:
    """将 Markdown 文本转换为 Ghost Lexical 格式（JSON 字符串）。

    Ghost v5+ 使用 Lexical 编辑器格式，支持标题、段落、列表、代码块等。
    """
    import json as _json
    import re as _re

    def _text_node(text: str, fmt: int = 0) -> dict:
        return {'type': 'text', 'version': 1, 'text': text, 'format': fmt}

    def _heading(tag: str, text: str) -> dict:
        return {'type': 'heading', 'version': 1, 'tag': tag, 'direction': 'ltr', 'format': '', 'indent': 0,
                'children': [_text_node(text)]}

    def _paragraph(text: str) -> dict:
        children = []
        parts = _re.split(r'(\*\*.+?\*\*)', text)
        for part in parts:
            if part.startswith('**') and part.endswith('**'):
                children.append(_text_node(part[2:-2], 1))
            elif part:
                children.append(_text_node(part))
        if not children:
            children = [_text_node('')]
        return {'type': 'paragraph', 'version': 1, 'direction': 'ltr', 'format': '', 'indent': 0,
                'children': children}

    def _list(ordered: bool, items: list[str]) -> dict:
        list_type = 'ordered' if ordered else 'unordered'
        children = []
        for item in items:
            children.append({
                'type': 'listitem', 'version': 1, 'direction': 'ltr', 'format': '', 'indent': 0,
                'value': item, 'children': [_text_node(item)]
            })
        return {'type': list_type, 'version': 1, 'direction': 'ltr', 'format': '', 'indent': 0,
                'start': 1 if ordered else None, 'children': children}

    nodes = []
    lines = markdown_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        h_match = _re.match(r'^(#{1,3})\s+(.+)$', line)
        if h_match:
            tag = f'h{len(h_match.group(1))}'
            nodes.append(_heading(tag, h_match.group(2).strip()))
            i += 1
            continue

        if line.strip().startswith("```"):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1
            nodes.append({'type': 'code', 'version': 1, 'direction': 'ltr', 'format': '', 'indent': 0,
                          'language': '', 'code': '\n'.join(code_lines)})
            continue

        if _re.match(r'^[-*]\s+', line):
            items = []
            while i < len(lines) and _re.match(r'^[-*]\s+', lines[i]):
                items.append(_re.sub(r'^[-*]\s+', '', lines[i]).strip())
                i += 1
            nodes.append(_list(False, items))
            continue

        if _re.match(r'^\d+\.\s+', line):
            items = []
            while i < len(lines) and _re.match(r'^\d+\.\s+', lines[i]):
                items.append(_re.sub(r'^\d+\.\s+', '', lines[i]).strip())
                i += 1
            nodes.append(_list(True, items))
            continue

        if line.strip() in ("---", "***", "___"):
            nodes.append(_paragraph('———'))
            i += 1
            continue

        para_lines = [line.strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not _re.match(r'^#{1,3}\s', lines[i]) \
                and not _re.match(r'^[-*]\s', lines[i]) and not _re.match(r'^\d+\.\s', lines[i]) \
                and not lines[i].strip().startswith("```") and lines[i].strip() not in ("---", "***", "___"):
            para_lines.append(lines[i].strip())
            i += 1
        para_text = " ".join(para_lines)
        para_text = _re.sub(r'`(.+?)`', r'\1', para_text)
        nodes.append(_paragraph(para_text))

    return _json.dumps({
        'root': {'type': 'root', 'version': 1, 'direction': 'ltr', 'format': '', 'indent': 0, 'children': nodes}
    }, ensure_ascii=False)


def _extract_tags_from_content(title: str, content: str) -> list[str]:
    """从标题和内容中提取关键词作为标签。"""
    tags: list[str] = []
    title_words = [w.strip() for w in title.replace(",", " ").replace("，", " ").split() if len(w.strip()) >= 2]
    tags.extend(title_words[:3])
    keyword_map = {
        "股票": "股票分析", "A股": "A股", "投资": "投资策略",
        "八字": "八字命理", "紫微": "紫微斗数", "梅花": "梅花易数",
        "命理": "命理", "运势": "运势预测", "风水": "风水",
        "价值投资": "价值投资", "技术分析": "技术分析",
        "威科夫": "威科夫", "江恩": "江恩", "巴菲特": "巴菲特",
        "代码": "编程", "开发": "软件开发",
    }
    content_lower = content.lower()
    for keyword, tag in keyword_map.items():
        if keyword in content_lower and tag not in tags:
            tags.append(tag)
    return tags[:5]


def _build_blog_content_from_task(task: Any) -> str:
    """从单个任务构建博客内容（Markdown 格式）。"""
    title = task.title or "未命名任务"
    description = task.description or ""
    result = task.result or ""

    sections = [f"# {title}\n"]
    if description:
        sections.append(f"## 任务描述\n\n{description}\n")
    if result:
        sections.append(f"## 分析结果\n\n{result}\n")
    sections.append("---\n*本文由数字人生多智能体协作平台自动生成*\n")
    return "\n".join(sections)


async def _build_blog_content_from_room(task: Any) -> str:
    """从任务关联的房间收集分析消息，构建博客内容。

    支持两种模式：
    - 全量模式：收集所有 Agent 的消息（task 无 _filter_agent_id 时）
    - 单 Agent 模式：只收集指定 Agent 的消息（task 有 _filter_agent_id 时）
    """
    from model.dbModel.gtRoomMessage import GtRoomMessage
    from model.dbModel.gtAgent import GtAgent

    title = task.title or "未命名任务"
    description = task.description or ""
    result = task.result or ""

    # 获取房间 ID
    room_id = None
    if hasattr(task, 'room_id') and task.room_id:
        room_id = task.room_id
    else:
        room_id = getattr(task, 'task_data', {}).get('room_id') if hasattr(task, 'task_data') else None

    # 单 Agent 过滤模式
    filter_agent_id = getattr(task, '_filter_agent_id', None)

    sections = [f"# {title}\n"]
    if description:
        sections.append(f"## 任务背景\n\n{description}\n")

    if room_id:
        try:
            messages = list(await GtRoomMessage.select()
                .where(GtRoomMessage.room_id == room_id)
                .order_by(GtRoomMessage.seq.asc())
                .aio_execute())

            if messages:
                agent_messages: dict[int, list[str]] = {}
                for msg in messages:
                    if msg.sender_id <= 0:
                        continue
                    # 单 Agent 模式：只收集该 Agent 的消息
                    if filter_agent_id is not None and msg.sender_id != filter_agent_id:
                        continue
                    if msg.sender_id not in agent_messages:
                        agent_messages[msg.sender_id] = []
                    content = msg.content or ""
                    if content.strip():
                        agent_messages[msg.sender_id].append(content)

                if filter_agent_id is not None:
                    # 单 Agent 模式：直接输出该专家的分析
                    for agent_id, msgs in agent_messages.items():
                        agent_name = f"专家{agent_id}"
                        try:
                            agent = await GtAgent.aio_get_or_none(GtAgent.id == agent_id)
                            if agent:
                                agent_name = agent.display_name or agent.name
                        except Exception:
                            pass
                        combined = "\n\n".join(msgs)
                        sections.append(f"{combined}\n")
                else:
                    # 全量模式：按 Agent 分组输出
                    sections.append("## 各专家分析\n")
                    for agent_id, msgs in agent_messages.items():
                        agent_name = f"专家{agent_id}"
                        try:
                            agent = await GtAgent.aio_get_or_none(GtAgent.id == agent_id)
                            if agent:
                                agent_name = agent.display_name or agent.name
                        except Exception:
                            pass
                        sections.append(f"### {agent_name}\n")
                        combined = "\n\n".join(msgs)
                        sections.append(f"{combined}\n")

                    if result:
                        sections.append("## 综合结论\n")
                        sections.append(f"{result}\n")
            else:
                if result:
                    sections.append(f"## 分析结果\n\n{result}\n")
        except Exception as e:
            logger.warning("收集房间消息失败: %s, 回退到任务结果", e)
            if result:
                sections.append(f"## 分析结果\n\n{result}\n")
    else:
        if result:
            sections.append(f"## 分析结果\n\n{result}\n")

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

    # 构建 Ghost API 请求体（使用 Lexical 格式，Ghost v5+ 原生内容格式）
    lexical = _markdown_to_lexical(content)
    body = {
        "posts": [
            {
                "title": title,
                "lexical": lexical,
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

    # 构建博客内容（收集房间内所有大师的分析消息）
    title = task.title or "未命名任务"
    content = await _build_blog_content_from_room(task)
    tags = _extract_tags_from_content(title, content)

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
