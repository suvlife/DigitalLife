"""统一的异步事务上下文管理器。

独立模块，避免与 dal/db/__init__.py 的 manager 子模块形成循环导入。
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import AsyncIterator, TypeVar

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

# 事务级重试的有界退避（与 ormService._SQLITE_LOCK_RETRY_DELAYS 对齐）。
_TXN_LOCK_RETRY_DELAYS = (0.05, 0.15, 0.35)


def is_sqlite_locked_error(exc: BaseException) -> bool:
    """判断异常链中是否包含 SQLite BUSY/LOCKED 竞争。

    与 ``service.ormService.is_sqlite_locked_error`` 语义一致，但独立实现，
    避免 dal 层反向依赖 service 层。
    """
    current: BaseException | None = exc
    while current is not None:
        message = str(current).lower()
        if "database is locked" in message or "database table is locked" in message:
            return True
        current = current.__cause__ or current.__context__
    return False


@contextlib.asynccontextmanager
async def atomic_transaction() -> AsyncIterator[None]:
    """统一的异步事务上下文管理器。

    业务代码统一通过 ``async with dal.db.transaction.atomic_transaction():`` 使用事务，
    避免在各处直接访问 ``Model._meta.database``（在 DatabaseProxy 未初始化的
    单元测试场景下会抛 AttributeError）。

    事务语义：
    - 顶层调用开启真实事务；
    - 嵌套调用退化为 savepoint；
    - 块内抛异常自动回滚，正常退出提交。

    若 DatabaseProxy 未初始化（如单元测试中未绑定真实 DB），退化为无操作上下文，
    保证逻辑可被 mock 驱动。
    """
    # 延迟导入，避免循环依赖
    from model.dbModel.base import _database_proxy

    database = _database_proxy.obj
    if database is None:
        yield
        return
    async with database.aio_atomic():
        yield


async def run_in_transaction_with_retry(
    operation: Callable[[], Awaitable[_T]],
    *,
    delays: tuple[float, ...] = _TXN_LOCK_RETRY_DELAYS,
) -> _T:
    """事务级重试：把整块多语句事务在 SQLITE_BUSY/LOCKED 后有界重试。

    与 ``ormService.retry_sqlite_locked``（仅覆盖单条语句）不同，本封装把
    ``atomic_transaction()`` 的开启/提交都放进重试范围，因此能兜住 COMMIT
    期触发的 BUSY（快照冲突）——语句级重试无法覆盖该窗口。

    要求 ``operation`` 幂等且无外部副作用（网络 / 文件 / 事件总线）：失败尝试
    的事务已整体回滚，未持久化任何行，故重跑安全。``operation`` 不应自行开启
    ``atomic_transaction()``（否则退化为 savepoint，外层 COMMIT BUSY 仍兜不到）。

    有界退避防止隐藏的无限重试。
    """
    for attempt in range(len(delays) + 1):
        try:
            async with atomic_transaction():
                return await operation()
        except Exception as exc:
            if not is_sqlite_locked_error(exc) or attempt >= len(delays):
                raise
            delay = delays[attempt]
            logger.warning(
                "SQLite busy/locked; retrying transaction in %.2fs (%d/%d)",
                delay, attempt + 1, len(delays),
            )
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")
