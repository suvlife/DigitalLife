"""统一的异步事务上下文管理器。

独立模块，避免与 dal/db/__init__.py 的 manager 子模块形成循环导入。
"""
from __future__ import annotations

import contextlib
from typing import AsyncIterator


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
