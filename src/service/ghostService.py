"""Reliable Ghost CMS publication service.

Only final conclusions enter this service. Publications are persisted in an
outbox table before network I/O, use a stable idempotency key, and can be
retried after a process restart. Ghost Admin API credentials never leave the
server and are never written to logs.
"""
from __future__ import annotations

import asyncio
import base64
import datetime
import hashlib
import hmac
import html
import ipaddress
import json
import logging
import os
import re
import socket
import time
import uuid
from typing import Any
from urllib.parse import urlencode, urlparse

import aiohttp

from util import safeHttpUtil

logger = logging.getLogger(__name__)

try:  # Prefer the repository's markdown-it-py dependency for full Markdown.
    from markdown_it import MarkdownIt

    _MARKDOWN_IT = (
        MarkdownIt("commonmark", {"html": False, "linkify": False, "breaks": False})
        .enable("table")
        .enable("strikethrough")
    )
except Exception:  # pragma: no cover - fallback when dependency is missing
    _MARKDOWN_IT = None
_GHOST_API_TIMEOUT = aiohttp.ClientTimeout(total=30)
_RETRY_DELAYS_SECONDS = (10, 30, 120, 300, 900, 3600)
_worker_task: asyncio.Task[None] | None = None
_worker_wakeup: asyncio.Event | None = None
_worker_token = uuid.uuid4().hex
_GHOST_LEASE_SECONDS = 120


def _generate_ghost_jwt(admin_api_key: str) -> str:
    """Generate a short-lived Ghost Admin API JWT from ``id:hex-secret``."""
    try:
        key_id, key_secret = admin_api_key.split(":", 1)
    except ValueError as exc:
        raise ValueError("Invalid Ghost admin API key format (expected 'id:secret')") from exc
    if not key_id or not key_secret:
        raise ValueError("Invalid Ghost admin API key format (empty id or secret)")
    try:
        secret = bytes.fromhex(key_secret)
    except ValueError as exc:
        raise ValueError("Invalid Ghost admin API key secret (expected hexadecimal)") from exc

    def _b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT", "kid": key_id}
    payload = {"iat": now, "exp": now + 300, "aud": "/admin/"}
    header_b64 = _b64(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode()
    signature = hmac.new(secret, signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64(signature)}"


def assert_safe_http_url(url: str, *, field_name: str = "URL") -> None:
    """Validate a configured upstream using the shared pinned-DNS policy."""
    safeHttpUtil.assert_safe_http_url(url, field_name=field_name)


def _safe_ghost_base_url(api_url: str) -> str:
    assert_safe_http_url(api_url, field_name="Ghost API URL")
    parsed = urlparse(api_url.strip())
    # Keep an explicitly configured subpath, but strip Admin API suffixes.
    path = parsed.path.rstrip("/")
    marker = "/ghost/api/admin"
    if marker in path:
        path = path.split(marker, 1)[0]
    return f"{parsed.scheme}://{parsed.netloc}{path}".rstrip("/")


def _sanitize_link(url: str) -> str:
    value = html.unescape(url.strip())
    parsed = urlparse(value)
    if parsed.scheme.lower() in {"http", "https", "mailto"}:
        return html.escape(value, quote=True)
    if not parsed.scheme and not value.startswith("//"):
        return html.escape(value, quote=True)
    return "#"


def _render_inline_markdown(text: str) -> str:
    """Render a conservative inline Markdown subset with HTML escaping."""
    escaped = html.escape(text, quote=False)
    placeholders: list[str] = []

    def _stash(value: str) -> str:
        placeholders.append(value)
        return f"\x00{len(placeholders) - 1}\x00"

    escaped = re.sub(
        r"`([^`]+)`",
        lambda m: _stash(f"<code>{html.escape(html.unescape(m.group(1)), quote=False)}</code>"),
        escaped,
    )
    escaped = re.sub(
        r"!\[([^\]]*)\]\(([^\s)]+)(?:\s+&quot;.*?&quot;)?\)",
        lambda m: _stash(
            f'<img src="{_sanitize_link(html.unescape(m.group(2)))}" alt="{html.escape(html.unescape(m.group(1)), quote=True)}">'
        ),
        escaped,
    )
    escaped = re.sub(
        r"\[([^\]]+)\]\(([^\s)]+)(?:\s+&quot;.*?&quot;)?\)",
        lambda m: _stash(
            f'<a href="{_sanitize_link(html.unescape(m.group(2)))}" rel="noopener noreferrer">{html.escape(html.unescape(m.group(1)), quote=False)}</a>'
        ),
        escaped,
    )
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"~~([^~]+)~~", r"<del>\1</del>", escaped)
    for index, value in enumerate(placeholders):
        escaped = escaped.replace(f"\x00{index}\x00", value)
    return escaped


def markdown_to_safe_html(markdown_text: str) -> str:
    """Convert Markdown to allowlisted HTML suitable for Ghost ``source=html``.

    Raw HTML is always escaped. Supported blocks include headings, paragraphs,
    fenced code, blockquotes, ordered/unordered/task lists, tables and rules.
    """
    lines = markdown_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    output: list[str] = []
    paragraph: list[str] = []
    list_type: str | None = None
    in_quote = False
    in_code = False
    code_language = ""
    code_lines: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            output.append(f"<p>{'<br>'.join(_render_inline_markdown(part) for part in paragraph)}</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            output.append(f"</{list_type}>")
            list_type = None

    def close_quote() -> None:
        nonlocal in_quote
        if in_quote:
            flush_paragraph()
            output.append("</blockquote>")
            in_quote = False

    index = 0
    while index < len(lines):
        line = lines[index]
        fence = re.match(r"^\s*```\s*([\w.+-]*)\s*$", line)
        if fence:
            flush_paragraph(); close_list(); close_quote()
            if in_code:
                language_attr = f' class="language-{html.escape(code_language, quote=True)}"' if code_language else ""
                output.append(f"<pre><code{language_attr}>{html.escape(chr(10).join(code_lines))}</code></pre>")
                code_lines.clear(); code_language = ""; in_code = False
            else:
                in_code = True; code_language = fence.group(1)
            index += 1
            continue
        if in_code:
            code_lines.append(line)
            index += 1
            continue
        if not line.strip():
            flush_paragraph(); close_list(); close_quote(); index += 1; continue

        # GFM-style tables with a header separator.
        if "|" in line and index + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{3,}", lines[index + 1]):
            flush_paragraph(); close_list(); close_quote()
            headers = [cell.strip() for cell in line.strip().strip("|").split("|")]
            output.append("<table><thead><tr>" + "".join(f"<th>{_render_inline_markdown(cell)}</th>" for cell in headers) + "</tr></thead><tbody>")
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
                output.append("<tr>" + "".join(f"<td>{_render_inline_markdown(cell)}</td>" for cell in cells) + "</tr>")
                index += 1
            output.append("</tbody></table>")
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            flush_paragraph(); close_list(); close_quote()
            level = len(heading.group(1))
            output.append(f"<h{level}>{_render_inline_markdown(heading.group(2).strip())}</h{level}>")
            index += 1; continue
        if re.match(r"^\s*(---|\*\*\*|___)\s*$", line):
            flush_paragraph(); close_list(); close_quote(); output.append("<hr>"); index += 1; continue
        quote = re.match(r"^\s*>\s?(.*)$", line)
        if quote:
            flush_paragraph(); close_list()
            if not in_quote:
                output.append("<blockquote>"); in_quote = True
            paragraph.append(quote.group(1)); index += 1; continue
        if in_quote:
            close_quote()
        item = re.match(r"^\s*([-+*]|\d+[.)])\s+(.+)$", line)
        if item:
            flush_paragraph()
            wanted = "ol" if item.group(1)[0].isdigit() else "ul"
            if list_type != wanted:
                close_list(); output.append(f"<{wanted}>"); list_type = wanted
            value = item.group(2)
            task = re.match(r"^\[([ xX])\]\s+(.+)$", value)
            if task:
                checked = " checked" if task.group(1).lower() == "x" else ""
                value = f'<input type="checkbox" disabled{checked}> {_render_inline_markdown(task.group(2))}'
            else:
                value = _render_inline_markdown(value)
            output.append(f"<li>{value}</li>"); index += 1; continue
        close_list()
        paragraph.append(line.strip())
        index += 1

    if in_code:
        language_attr = f' class="language-{html.escape(code_language, quote=True)}"' if code_language else ""
        output.append(f"<pre><code{language_attr}>{html.escape(chr(10).join(code_lines))}</code></pre>")
    flush_paragraph(); close_list(); close_quote()
    return "\n".join(output)


def markdown_to_html(markdown_text: str) -> str:
    """Convert Markdown to HTML for Ghost ``source=html``.

    The full document is rendered with no length truncation (#6). ``markdown-it-py``
    is used when available (raw HTML disabled so untrusted input stays escaped);
    otherwise the built-in allowlist renderer is used as a fallback.
    """
    text = markdown_text or ""
    if _MARKDOWN_IT is not None:
        return _MARKDOWN_IT.render(text)
    return markdown_to_safe_html(text)


def _extract_tags_from_content(title: str, content: str) -> list[str]:
    tags = ["数字人生", "多智能体"]
    words = [word.strip() for word in re.split(r"[,，\s]+", title) if len(word.strip()) >= 2]
    for word in words[:3]:
        if word not in tags:
            tags.append(word[:40])
    return tags[:5]


def _build_final_markdown(title: str, conclusion: str, *, question: str = "") -> str:
    sections = [f"# {title}"]
    if question.strip():
        sections.append(f"## 用户问题\n\n{question.strip()}")
    sections.append(f"## 最终结论\n\n{conclusion.strip()}")
    sections.append("---\n\n*本文由数字人生多智能体协作平台自动生成*")
    return "\n\n".join(sections)


async def publish_post(
    title: str,
    content_markdown: str,
    status: str | None = None,
) -> dict[str, Any]:
    """Public contract: publish one Markdown document to Ghost.

    Reads Ghost credentials from server-side config, converts the *entire*
    Markdown body to HTML (no truncation, #6) and submits it via the Admin API
    ``source=html`` endpoint. Returns ``{"success": True, "url": ...}`` on
    success or ``{"success": False, "error": ...}`` on failure.
    """
    from util import configUtil

    ghost = configUtil.get_app_config().setting.ghost
    if not (ghost.api_url and ghost.admin_api_key):
        return {"success": False, "error": "Ghost API URL 或 Admin Key 未配置"}
    effective_status = (status or ghost.publish_status or "published").strip()
    if not (title and title.strip()):
        return {"success": False, "error": "标题不能为空"}
    if not (content_markdown and content_markdown.strip()):
        return {"success": False, "error": "正文内容不能为空"}

    result = await _publish_to_ghost(
        title.strip(),
        content_markdown,
        api_url=ghost.api_url,
        admin_api_key=ghost.admin_api_key,
        status=effective_status,
        skip_ssl_verify=ghost.skip_ssl_verify,
    )
    if result.get("success"):
        return {"success": True, "url": result.get("post_url"), "post_id": result.get("post_id")}
    return {"success": False, "error": result.get("message", "Ghost 发布失败")}


async def publish_run_conclusion(
    run_id: Any,
    team_name: str,
    title: str,
    content_markdown: str,
) -> dict[str, Any]:
    """Public contract: publish a run's final conclusion as a blog post.

    Builds a complete document (title + conclusion body) and publishes it
    through :func:`publish_post`. The full conclusion is submitted without any
    length truncation. Returns ``{"success", "url"|"error"}``.
    """
    from util import configUtil

    ghost = configUtil.get_app_config().setting.ghost
    safe_title = (title or "").strip() or "综合分析报告"
    document = _build_final_markdown(safe_title, content_markdown or "")

    result = await publish_post(safe_title, document, status=ghost.publish_status)
    if result.get("success"):
        logger.info("Ghost run conclusion published: run_id=%s team=%s", run_id, team_name)
    else:
        logger.warning(
            "Ghost run conclusion publish failed: run_id=%s team=%s", run_id, team_name
        )
    return result


async def _publish_to_ghost(
    title: str,
    content: str,
    tags: list[str] | None = None,
    *,
    api_url: str,
    admin_api_key: str,
    status: str = "published",
    slug: str | None = None,
    skip_ssl_verify: bool = False,
) -> dict[str, Any]:
    """Create or converge one Ghost post using a stable slug.

    A retry first looks up ``slug``. If a previous POST reached Ghost but its
    response was lost, the existing post is updated instead of creating a
    duplicate. Ghost requires ``updated_at`` for optimistic update locking.
    """
    if not api_url or not admin_api_key:
        return {"success": False, "message": "Ghost API URL 或 Admin Key 未配置", "retryable": False}
    if status not in {"published", "draft"}:
        return {"success": False, "message": "Ghost status 必须为 published 或 draft", "retryable": False}
    if skip_ssl_verify:
        # Audit L4: publishing without TLS verification is not an authenticated
        # channel; surface it so operators do not run this way unintentionally.
        logger.warning("Ghost publish with TLS verification disabled (skip_ssl_verify=True)")
    try:
        base_url = _safe_ghost_base_url(api_url)
        jwt_token = _generate_ghost_jwt(admin_api_key)
    except ValueError as exc:
        return {"success": False, "message": str(exc), "retryable": False}

    headers = {
        "Authorization": f"Ghost {jwt_token}",
        "Accept-Version": "v5.0",
        "Content-Type": "application/json",
    }
    post_body: dict[str, Any] = {
        "title": title,
        "html": markdown_to_html(content),
        "tags": [{"name": tag} for tag in (tags or _extract_tags_from_content(title, content))],
        "status": status,
    }
    if slug:
        post_body["slug"] = slug

    try:
        existing: dict[str, Any] | None = None
        if slug:
            query = urlencode({"filter": f"slug:{slug}", "limit": "1", "formats": "html"})
            lookup_endpoint = f"{base_url}/ghost/api/admin/posts/?{query}"
            response = await safeHttpUtil.request(
                "GET", lookup_endpoint, headers=headers, timeout=_GHOST_API_TIMEOUT,
                field_name="Ghost API URL", ssl=False if skip_ssl_verify else None,
            )
            text = response.text
            if response.status == 200:
                data = json.loads(text) if text else {}
                posts = data.get("posts") or []
                existing = posts[0] if posts else None
            elif response.status == 429 or response.status >= 500:
                return {
                    "success": False,
                    "message": f"Ghost 对账查询返回 HTTP {response.status}: {text[:500]}",
                    "retryable": True,
                }
            else:
                return {
                    "success": False,
                    "message": f"Ghost 对账查询返回 HTTP {response.status}: {text[:500]}",
                    "retryable": False,
                }

        if existing is not None:
            post_id = existing.get("id")
            updated_at = existing.get("updated_at")
            if not post_id or not updated_at:
                return {"success": False, "message": "Ghost 对账结果缺少 id/updated_at", "retryable": True}
            update_body = dict(post_body)
            update_body["updated_at"] = updated_at
            endpoint = f"{base_url}/ghost/api/admin/posts/{post_id}/?source=html"
            method = "PUT"
            payload = {"posts": [update_body]}
        else:
            endpoint = f"{base_url}/ghost/api/admin/posts/?source=html"
            method = "POST"
            payload = {"posts": [post_body]}

        response = await safeHttpUtil.request(
            method, endpoint, headers=headers, json_body=payload, timeout=_GHOST_API_TIMEOUT,
            field_name="Ghost API URL", ssl=False if skip_ssl_verify else None,
        )
        response_text = response.text
        if response.status in {200, 201}:
            data = json.loads(response_text) if response_text else {}
            post = (data.get("posts") or [{}])[0]
            return {
                "success": True,
                "message": "发布成功",
                "post_url": post.get("url") or (existing or {}).get("url"),
                "post_id": post.get("id") or (existing or {}).get("id"),
                "retryable": False,
            }
        retryable = response.status in {409, 429} or response.status >= 500
        logger.warning("Ghost publish failed: status=%s", response.status)
        return {
            "success": False,
            "message": f"Ghost API 返回 HTTP {response.status}: {response_text[:500]}",
            "retryable": retryable,
        }
    except (aiohttp.ClientError, asyncio.TimeoutError, safeHttpUtil.UnsafeUrlError) as exc:
        logger.warning("Ghost publish transport error: %s", type(exc).__name__)
        return {"success": False, "message": f"发布请求异常: {type(exc).__name__}", "retryable": True}


def _stable_ghost_slug(publication_key: str) -> str:
    """Return a deterministic, Ghost-safe remote idempotency identifier."""
    digest = hashlib.sha256(publication_key.encode("utf-8")).hexdigest()[:24]
    return f"digitallife-{digest}"


async def enqueue_final_conclusion(
    *,
    source_id: str | int,
    title: str,
    conclusion: str,
    question: str = "",
    team_id: int | None = None,
    room_id: int | None = None,
    publication_key: str | None = None,
    run_id: int | None = None,
) -> dict[str, Any]:
    """Unified final-conclusion entry point used by current submit_conclusion."""
    from dal.db import gtBlogPublicationManager
    from util import configUtil

    ghost = configUtil.get_app_config().setting.ghost
    if not (ghost.enabled and ghost.auto_publish and ghost.api_url and ghost.admin_api_key):
        return {"success": False, "queued": False, "message": "Ghost 自动发布未启用或配置不完整"}
    if not conclusion.strip():
        return {"success": False, "queued": False, "message": "最终结论不能为空"}

    source_text = str(source_id)
    key = publication_key or f"final-conclusion:{source_text}"
    markdown_content = _build_final_markdown(title, conclusion, question=question)
    content_hash = hashlib.sha256(markdown_content.encode("utf-8")).hexdigest()
    row = await gtBlogPublicationManager.upsert_pending(
        publication_key=key,
        source_type="FINAL_CONCLUSION",
        source_id=source_text,
        title=title.strip() or "综合分析报告",
        markdown_content=markdown_content,
        content_hash=content_hash,
        tags=_extract_tags_from_content(title, markdown_content),
        ghost_slug=_stable_ghost_slug(key),
        team_id=team_id,
        room_id=room_id,
        run_id=run_id,
    )
    _wake_worker()
    return {
        "success": True,
        "queued": row.status != "PUBLISHED",
        "publication_id": row.id,
        "status": row.status,
        "post_url": row.post_url,
    }


async def publish_task_if_enabled(task: Any) -> dict[str, Any]:
    """Compatibility wrapper; only objects explicitly marked final are accepted.

    Ordinary collaboration task ``DONE`` records are intentionally ignored to
    prevent fragmented and duplicate blog posts.
    """
    if not bool(getattr(task, "is_final_conclusion", False)):
        logger.debug("Skip non-final task publication: task_id=%s", getattr(task, "id", None))
        return {"success": False, "queued": False, "message": "仅最终结论可发布"}
    source_id = getattr(task, "publication_source_id", None) or getattr(task, "id", None) or getattr(task, "room_id", None)
    if source_id is None:
        return {"success": False, "queued": False, "message": "最终结论缺少稳定 source_id"}
    return await enqueue_final_conclusion(
        source_id=source_id,
        title=getattr(task, "title", "综合分析报告"),
        conclusion=getattr(task, "result", ""),
        question=getattr(task, "description", ""),
        team_id=getattr(task, "team_id", None),
        room_id=getattr(task, "room_id", None),
    )


def _wake_worker() -> None:
    if _worker_wakeup is not None:
        _worker_wakeup.set()


async def _process_publication(row: Any) -> None:
    from dal.db import gtBlogPublicationManager
    from util import configUtil

    claim_token = str(getattr(row, "worker_token", "") or "")
    if not claim_token:
        logger.error("Refusing to process Ghost publication %s without a claim token", row.id)
        return
    slug = getattr(row, "ghost_slug", None) or _stable_ghost_slug(row.publication_key)
    if not getattr(row, "ghost_slug", None):
        await gtBlogPublicationManager.ensure_ghost_slug(row.id, slug)
        row.ghost_slug = slug

    ghost = configUtil.get_app_config().setting.ghost
    result = await _publish_to_ghost(
        row.title,
        row.markdown_content,
        list(row.tags or []),
        api_url=ghost.api_url,
        admin_api_key=ghost.admin_api_key,
        status=ghost.publish_status,
        slug=slug,
        skip_ssl_verify=ghost.skip_ssl_verify,
    )
    if result.get("success"):
        post_id = result.get("post_id")
        post_url = result.get("post_url")
        persisted = await gtBlogPublicationManager.mark_published(
            row.id,
            worker_token=claim_token,
            ghost_post_id=post_id,
            post_url=post_url,
        )
        # Losing the lease is not a remote failure. The current owner (or the
        # next retry) will reconcile by slug and converge without another POST.
        if not persisted:
            logger.warning("Ghost post succeeded but publication claim was lost: row=%s", row.id)
            return
        if getattr(row, "run_id", None) is not None:
            try:
                from service import runService
                await runService.update_blog_publish_status(
                    run_id=row.run_id, status="PUBLISHED", post_id=post_id, post_url=post_url,
                )
            except Exception:
                logger.exception("Failed to update TaskRun blog publication status")
        return

    max_attempts = max(1, int(ghost.max_retry_attempts))
    terminal = not bool(result.get("retryable")) or row.attempt_count >= max_attempts
    delay_index = min(max(row.attempt_count - 1, 0), len(_RETRY_DELAYS_SECONDS) - 1)
    error_message = str(result.get("message", "Ghost publish failed"))
    persisted = await gtBlogPublicationManager.mark_retry(
        row.id,
        worker_token=claim_token,
        error=error_message,
        next_retry_at=datetime.datetime.now() + datetime.timedelta(seconds=_RETRY_DELAYS_SECONDS[delay_index]),
        terminal=terminal,
    )
    if not persisted:
        logger.warning("Ghost retry result ignored after claim loss: row=%s", row.id)
        return
    if getattr(row, "run_id", None) is not None:
        try:
            from service import runService
            await runService.update_blog_publish_status(
                run_id=row.run_id,
                status="FAILED" if terminal else "RETRY_WAITING",
                error_message=error_message,
            )
        except Exception:
            logger.exception("Failed to update TaskRun blog publication failure status")


async def process_pending_once(
    limit: int = 10, *, worker_token: str | None = None, lease_seconds: int = _GHOST_LEASE_SECONDS
) -> int:
    from dal.db import gtBlogPublicationManager
    token = worker_token or _worker_token
    rows = await gtBlogPublicationManager.claim_due(
        worker_token=token, limit=limit, lease_seconds=lease_seconds
    )
    for row in rows:
        await _process_publication(row)
    return len(rows)


async def _worker_loop() -> None:
    assert _worker_wakeup is not None
    while True:
        try:
            processed = await process_pending_once()
            if processed:
                continue
            _worker_wakeup.clear()
            try:
                await asyncio.wait_for(_worker_wakeup.wait(), timeout=10)
            except asyncio.TimeoutError:
                pass
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ghost publication worker iteration failed")
            await asyncio.sleep(5)


async def startup() -> None:
    global _worker_task, _worker_wakeup, _worker_token
    if _worker_task is not None and not _worker_task.done():
        return
    from dal.db import gtBlogPublicationManager
    # Refresh after process start so pre-fork servers cannot share a token.
    _worker_token = f"{os.getpid()}-{uuid.uuid4().hex}"
    await gtBlogPublicationManager.recover_interrupted()
    _worker_wakeup = asyncio.Event()
    _worker_task = asyncio.create_task(_worker_loop(), name="ghost-publication-worker")


async def shutdown() -> None:
    global _worker_task, _worker_wakeup
    task = _worker_task
    _worker_task = None
    _worker_wakeup = None
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def test_ghost_connection(api_url: str, admin_api_key: str, *, skip_ssl_verify: bool = False) -> dict[str, Any]:
    """Test server-side Admin API authentication without publishing content."""
    if not api_url or not admin_api_key:
        return {"success": False, "message": "请填写 Ghost API URL 和 Admin API Key"}
    if skip_ssl_verify:
        logger.warning("Ghost connection test with TLS verification disabled (skip_ssl_verify=True)")
    try:
        base_url = _safe_ghost_base_url(api_url)
        token = _generate_ghost_jwt(admin_api_key)
    except ValueError as exc:
        return {"success": False, "message": str(exc)}
    endpoint = f"{base_url}/ghost/api/admin/site/"
    headers = {"Authorization": f"Ghost {token}", "Accept-Version": "v5.0"}
    try:
        response = await safeHttpUtil.request(
            "GET", endpoint, headers=headers, timeout=_GHOST_API_TIMEOUT,
            field_name="Ghost API URL", ssl=False if skip_ssl_verify else None,
        )
        if response.status == 200:
            data = response.json()
            site = data.get("site", {})
            return {"success": True, "message": "连接成功", "site_title": site.get("title", "")}
        return {"success": False, "message": f"连接失败：HTTP {response.status}"}
    except aiohttp.ClientConnectorCertificateError as exc:
        cert_err = getattr(exc, "certificate_error", None)
        detail = getattr(cert_err, "verify_message", "") or str(cert_err) or str(exc)
        return {"success": False, "message": f"SSL 证书验证失败：{detail}。请检查 Ghost 地址的 HTTPS 证书是否有效且证书链完整。"}
    except (aiohttp.ClientError, asyncio.TimeoutError, safeHttpUtil.UnsafeUrlError) as exc:
        return {"success": False, "message": f"连接异常：{type(exc).__name__}"}
