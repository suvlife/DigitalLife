"""主动告警服务：把关键异常事件推送到外部 Webhook（钉钉/企业微信/Slack 兼容）。

生产环境此前对"任务失败 / LLM 配额耗尽 / 调度卡死"只能靠人工看日志或被动
WebSocket（对已连接前端可见，队列压力下还会丢弃），实际是"瞎的"。本服务提供
一个可选的 webhook 出口：配置 `setting.alert.webhook_url` 后，关键事件异步推送。

设计要点：
- 零新增依赖：复用项目内 safeHttpUtil 的安全 HTTP 客户端（SSRF 校验）。
- 异步发送 + 后台任务，绝不阻塞主链路；发送失败仅记日志，不影响业务。
- 按事件类型节流（默认同类 5 分钟最多 1 条），避免风暴期刷屏。
- 未配置 webhook_url 时全部操作为空操作（no-op），开销可忽略。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# 同类告警的最小间隔（秒），防止风暴期刷屏
_THROTTLE_SECONDS = 300
_last_sent_at: dict[str, float] = {}
_pending_tasks: set[asyncio.Task] = set()


def _get_alert_config() -> tuple[str | None, bool]:
    """读取 (webhook_url, enabled)。未初始化或异常时返回 (None, False)。"""
    try:
        from util import configUtil
        setting = configUtil.get_app_config().setting
        alert = getattr(setting, "alert", None)
        if alert is None:
            return None, False
        enabled = bool(getattr(alert, "enabled", False))
        url = getattr(alert, "webhook_url", None) or None
        return url, enabled
    except Exception:
        return None, False


def _throttled(event_key: str) -> bool:
    """同类事件在节流窗口内只发一次。返回 True 表示应被节流（跳过）。"""
    now = time.monotonic()
    last = _last_sent_at.get(event_key)
    if last is not None and (now - last) < _THROTTLE_SECONDS:
        return True
    _last_sent_at[event_key] = now
    return False


def _format_text(title: str, fields: dict[str, Any]) -> str:
    lines = [f"【DigitalLife 告警】{title}"]
    for k, v in fields.items():
        lines.append(f"- {k}: {v}")
    lines.append(f"- 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    return "\n".join(lines)


async def _send_async(url: str, title: str, fields: dict[str, Any]) -> None:
    """实际发送（Markdown 兼容钉钉/企业微信/Slack incoming-webhook 的通用格式）。"""
    text = _format_text(title, fields)
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text},
        # Slack 兼容字段
        "text": text,
    }
    try:
        from util import safeHttpUtil
        await safeHttpUtil.request(
            "POST", url, json_body=payload, field_name="alert webhook",
            allow_private=True, timeout=10, max_bytes=64 * 1024,
        )
        logger.info("[alert] 已推送告警: %s", title)
    except Exception:
        logger.exception("[alert] 推送告警失败: %s", title)


def send_alert(event_key: str, title: str, fields: dict[str, Any] | None = None, *, throttle: bool = True) -> None:
    """同步入口：调度一条后台告警发送任务（不阻塞调用方）。

    event_key 用于按类型节流（如 "task_failed" / "llm_rate_limited"）。
    未启用或未配置 webhook 时直接 no-op。
    """
    url, enabled = _get_alert_config()
    if not enabled or not url:
        return
    if throttle and _throttled(event_key):
        logger.debug("[alert] 告警被节流跳过: %s", event_key)
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 无事件循环（如进程退出阶段），跳过
        return
    task = loop.create_task(_send_async(url, title, fields or {}))
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)


# ── 语义化告警入口 ─────────────────────────────────────────────

def alert_task_failed(agent_id: int, task_id: Any, error: str) -> None:
    send_alert("task_failed", "Agent 任务失败", {
        "agent_id": agent_id, "task_id": task_id, "error": (error or "")[:500],
    })


def alert_llm_rate_limited(service_name: str, detail: str = "") -> None:
    send_alert("llm_rate_limited", "LLM 配额/限流告警", {
        "service": service_name, "detail": (detail or "")[:300],
    })


def alert_schedule_stuck(reason: str) -> None:
    send_alert("schedule_stuck", "调度异常/卡死", {"reason": (reason or "")[:300]})


def reset_for_testing() -> None:
    _last_sent_at.clear()
