import asyncio
import logging

logger = logging.getLogger(__name__)


def cancel_task_safely(task: asyncio.Task | None) -> None:
    """安全取消 asyncio task；任务为空、已结束或所属 loop 已关闭时静默返回。

    注意：此函数是同步的，调用 task.cancel() 后不会 await。
    为避免 "Task exception was never retrieved" 告警，注册 done_callback
    检索并记录异常。调用方若需确保取消完成，应在 async 上下文中
    `await asyncio.gather(task, return_exceptions=True)`。
    """
    if task is None or task.done():
        return
    try:
        if task.get_loop().is_closed():
            return
        task.cancel()
        # 注册回调检索异常，避免 "exception was never retrieved" 告警
        task.add_done_callback(_retrieve_task_exception)
    except RuntimeError:
        return


def _retrieve_task_exception(task: asyncio.Task) -> None:
    """done_callback：检索并记录被取消 task 的异常。"""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("后台 task 异常退出: %s: %s", type(exc).__name__, exc)
