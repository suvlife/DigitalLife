from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

from constants import MessageBusTopic

logger = logging.getLogger(__name__)


@dataclass
class EventBusMessage:
    topic: MessageBusTopic
    payload: Dict[str, Any] = field(default_factory=dict)
    event_id: int | None = field(default=None, init=False)  # 由 publish 自动设置，None 表示未发布


_subscribers: Dict[MessageBusTopic, List[Callable[[EventBusMessage], None]]] = {}
_event_id_counter: int = 0
# 保留后台回调任务的强引用，避免被 GC 中途回收；
# 任务完成后通过 done_callback 自动从集合中移除。
_background_tasks: set[asyncio.Task] = set()
# 缓存主事件循环引用，供跨线程 publish 使用
_main_loop: asyncio.AbstractEventLoop | None = None


def _next_event_id() -> int:
    global _event_id_counter
    _event_id_counter += 1
    return _event_id_counter


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """缓存主事件循环引用，供跨线程 publish 使用。在 startup 中调用。"""
    global _main_loop
    _main_loop = loop


def subscribe(topic: MessageBusTopic, callback: Callable[[EventBusMessage], None]) -> None:
    """订阅指定主题，callback 接收 EventBusMessage 对象。

    幂等：同一 callback 重复订阅不会多次注册。
    """
    callbacks = _subscribers.setdefault(topic, [])
    if callback not in callbacks:
        callbacks.append(callback)


def subscribe_many(topics: list[MessageBusTopic], callback: Callable[[EventBusMessage], None]) -> None:
    """一次订阅多个主题，callback 接收 EventBusMessage 对象。"""
    for topic in topics:
        subscribe(topic, callback)


def unsubscribe(topic: MessageBusTopic, callback: Callable[[EventBusMessage], None]) -> None:
    """取消订阅指定主题（移除所有匹配的回调，防止重复订阅残留）。"""
    callbacks: List[Callable[[EventBusMessage], None]] = _subscribers.get(topic, [])
    _subscribers[topic] = [c for c in callbacks if c != callback]


def unsubscribe_many(topics: list[MessageBusTopic], callback: Callable[[EventBusMessage], None]) -> None:
    """一次取消多个主题的订阅。"""
    for topic in topics:
        unsubscribe(topic, callback)


def publish(topic: MessageBusTopic, **payload: Any) -> None:
    """向指定主题的所有订阅者投递消息。

    回调统一在 asyncio 事件循环里异步调度，避免慢订阅者阻塞发布链路。
    支持跨线程调用：若当前线程无运行中的事件循环，fallback 到缓存的主循环
    并用 call_soon_threadsafe 投递。
    """
    msg = EventBusMessage(topic=topic, payload=payload)
    msg.event_id = _next_event_id()
    logger.debug("[messageBus] publish event_id=%s topic=%s keys=%s", msg.event_id, topic.name, sorted(payload.keys()))
    callbacks = list(_subscribers.get(topic, []))

    try:
        loop = asyncio.get_running_loop()
        for cb in callbacks:
            loop.call_soon(_invoke_callback, cb, msg)
    except RuntimeError:
        # 当前线程无运行中的事件循环，用缓存的主循环 + threadsafe 投递
        if _main_loop is not None and not _main_loop.is_closed():
            for cb in callbacks:
                _main_loop.call_soon_threadsafe(_invoke_callback, cb, msg)
        else:
            logger.error("[messageBus] 无可用事件循环，丢弃事件: topic=%s", topic.name)


def _on_background_task_done(task: asyncio.Task) -> None:
    """回收后台回调任务的强引用，并检索异常（审计 H5）。

    裸 `_background_tasks.discard` 只丢引用、从不检索 `.exception()`，会把协程
    回调里的异常静默吞掉（仅 GC 时报 "Task exception was never retrieved"），
    导致调度事件被静默丢弃、Agent 不被唤醒且无业务日志。这里主动检索并落错误
    日志，保证故障可观测。
    """
    _background_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "[messageBus] 后台回调任务异常: task=%s: %s",
            task.get_name(), exc, exc_info=exc,
        )


def _invoke_callback(callback: Callable[[EventBusMessage], None], msg: EventBusMessage) -> None:
    callback_name = getattr(callback, "__name__", repr(callback))
    try:
        result = callback(msg)
        if inspect.isawaitable(result):
            task = asyncio.create_task(result, name=f"mb-{msg.event_id}-{callback_name}")
            _background_tasks.add(task)
            task.add_done_callback(_on_background_task_done)
    except Exception as e:
        logger.error(f"[messageBus] event_id={msg.event_id} topic={msg.topic} callback={callback_name} 异常: {e}")


async def startup() -> None:
    """初始化消息总线，须在各模块 subscribe 前调用。"""
    global _event_id_counter, _main_loop
    _event_id_counter = 0
    _subscribers.clear()
    _main_loop = asyncio.get_running_loop()


async def shutdown() -> None:
    """清空所有订阅，程序退出前调用。"""
    _subscribers.clear()