import asyncio
import logging
import os
import sqlite3
from datetime import datetime
from typing import Optional

import aiosqlite
import aiosqlite.core as _aiosqlite_core
import peewee
from peewee_async.databases import AioDatabase
from peewee_async.pool import PoolBackend
from peewee_async.utils import ConnectionProtocol

import appPaths
from db import check_database_initialized, migrate_database, resolve_db_path
from model.dbModel.base import bind_database

logger = logging.getLogger(__name__)

# aiosqlite.Connection 继承 Thread 且默认 daemon=False，
# 若连接因 asyncio 任务取消等原因未被正常 close()，其工作线程会阻塞进程退出。
# 在 __init__ 阶段（线程 start 之前）将 daemon 设为 True，使泄漏的连接不阻塞退出。
_orig_aiosqlite_init = _aiosqlite_core.Connection.__init__

def _patched_aiosqlite_init(self, *args, **kwargs):
    _orig_aiosqlite_init(self, *args, **kwargs)
    self.daemon = True

_aiosqlite_core.Connection.__init__ = _patched_aiosqlite_init


class _SqlitePoolState:
    def __init__(self) -> None:
        self.closed = False
        self._idle: list[ConnectionProtocol] = []
        self._lock = asyncio.Lock()


class SqlitePoolBackend(PoolBackend):
    """peewee-async 适配层：为 SQLite 提供带复用的异步连接池。

    SQLite 写操作串行化，因此池的主要价值是避免每次查询都付出
    aiosqlite 后台线程启动 + sqlite3.connect + pragma 协商成本。
    采用"少量空闲连接复用"策略：release 时归还而非 close，
    acquire 时优先取空闲连接。
    """

    _MAX_IDLE_CONNECTIONS = 4

    def __init__(self, *, database: str, **kwargs) -> None:
        super().__init__(database=database, **kwargs)
        self._acquired_count = 0
        self._connections: dict[int, ConnectionProtocol] = {}  # id -> conn（含空闲+在用）

    async def create(self) -> None:
        self.pool = _SqlitePoolState()

    async def acquire(self) -> ConnectionProtocol:
        if self.pool is None or self.pool.closed:
            await self.connect()
        state: _SqlitePoolState = self.pool  # type: ignore[assignment]

        async with state._lock:
            # 优先复用空闲连接
            if state._idle:
                conn = state._idle.pop()
                self._acquired_count += 1
                self._connections[id(conn)] = conn
                return conn

        # 无空闲连接，新建
        connect_params = dict(self.connect_params)
        connect_params.setdefault("isolation_level", None)
        try:
            conn: ConnectionProtocol = await aiosqlite.connect(self.database, **connect_params)
        except Exception:
            # 连接创建失败（含 CancelledError）：无 conn 需清理，直接传播
            raise
        self._acquired_count += 1
        self._connections[id(conn)] = conn
        return conn

    async def release(self, conn: ConnectionProtocol) -> None:
        conn_id = id(conn)
        self._acquired_count = max(0, self._acquired_count - 1)
        self._connections.pop(conn_id, None)
        if self.pool is None or self.pool.closed:
            # 池已关闭，直接关连接
            try:
                await conn.close()
            except Exception:
                pass
            return
        state: _SqlitePoolState = self.pool  # type: ignore[assignment]
        async with state._lock:
            if len(state._idle) < self._MAX_IDLE_CONNECTIONS and not state.closed:
                # 归还到空闲队列供复用
                state._idle.append(conn)
                return
        # 空闲队列已满，关闭连接
        try:
            await conn.close()
        except Exception:
            pass

    async def close(self) -> None:
        """关闭所有连接（含空闲），确保 aiosqlite 后台线程正确退出。"""
        if self.pool is not None:
            self.pool.closed = True
        state: _SqlitePoolState = self.pool  # type: ignore[assignment]
        async with state._lock:
            idle = list(state._idle)
            state._idle.clear()
        for conn_id, conn in list(self._connections.items()):
            try:
                await conn.close()
            except Exception:
                pass
        for conn in idle:
            try:
                await conn.close()
            except Exception:
                pass
        self._connections.clear()
        self._acquired_count = 0

    def has_acquired_connections(self) -> bool:
        return self._acquired_count > 0


class AioSqliteDatabase(AioDatabase, peewee.SqliteDatabase):
    pool_backend_cls = SqlitePoolBackend


_db: Optional[AioSqliteDatabase] = None
_db_path: Optional[str] = None


def _needs_migration(db_path: str) -> bool:
    """检查是否需要执行迁移：数据库文件不存在。"""
    return not os.path.exists(db_path)


async def startup(db_path: str) -> None:
    global _db, _db_path
    if _db is not None:
        return

    _db_path = db_path
    abs_path = os.path.abspath(db_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    # 启动时始终检查并执行待处理迁移，保证已有库也能升级到最新 schema。
    # migrate_database 是同步阻塞调用（含 sqlite3 连接 + fcntl 文件锁），
    # 丢到线程池执行以避免阻塞 asyncio 事件循环。
    if _needs_migration(abs_path):
        logger.info("Database not initialized, running migrations...")
    else:
        logger.info("Checking pending migrations for existing database...")
    applied = await asyncio.to_thread(migrate_database, abs_path)
    if applied:
        logger.info("Applied %d migration(s): %s", len(applied), applied)
    else:
        logger.info("Database schema is up to date")

    database = AioSqliteDatabase(
        abs_path,
        timeout=30,
    )
    bind_database(database)

    # 验证数据库是否已初始化
    if not check_database_initialized(abs_path):
        with database.allow_sync():
            database.close()
        raise RuntimeError(
            f"Database schema is not initialized. "
            f"Run '.venv/bin/python src/db.py migrate --db-path {abs_path}' first."
        )

    try:
        await database.aio_connect()
        _db = database
    except Exception:
        with database.allow_sync():
            database.close()
        raise

    logger.info("ORM service started: db=%s", abs_path)


async def shutdown() -> None:
    global _db, _db_path
    if _db is not None:
        await _db.aio_close()
    _db = None
    _db_path = None


def get_db() -> AioSqliteDatabase:
    if _db is None:
        raise RuntimeError("ormService not started")
    return _db


def is_ready() -> bool:
    return _db is not None and _db.is_connected


def get_db_path() -> Optional[str]:
    return _db_path


def backup_database() -> str:
    db_path = get_db_path()
    if db_path is None:
        raise RuntimeError("ormService not started")

    source_path = resolve_db_path(db_path)
    backup_dir = os.path.join(appPaths.DATA_DIR, "backups")
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = os.path.join(
        backup_dir,
        f"{source_path.stem}_{timestamp}{source_path.suffix or '.db'}",
    )

    with sqlite3.connect(str(source_path)) as source_conn, sqlite3.connect(backup_path) as backup_conn:
        source_conn.backup(backup_conn)

    logger.info("Database backup created: source=%s, backup=%s", source_path, backup_path)
    return backup_path
