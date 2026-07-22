import asyncio
import logging
import os
import sqlite3
from datetime import datetime
from collections.abc import Awaitable, Callable
from typing import Optional, TypeVar

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

_SQLITE_BUSY_TIMEOUT_MS = 5000
_SQLITE_LOCK_RETRY_DELAYS = (0.05, 0.15, 0.35)
_T = TypeVar("_T")

# 定时自动备份配置（环境变量可调）：默认每 6 小时备份一次，保留最近 12 份。
_AUTO_BACKUP_INTERVAL_SECONDS = float(os.environ.get("DIGITALLIFE_BACKUP_INTERVAL_SECONDS", str(6 * 3600)))
_BACKUP_KEEP_COUNT = int(os.environ.get("DIGITALLIFE_BACKUP_KEEP_COUNT", "12"))
_auto_backup_task: "asyncio.Task | None" = None


def is_sqlite_locked_error(exc: BaseException) -> bool:
    """Return whether an exception represents SQLite BUSY/LOCKED contention."""
    current: BaseException | None = exc
    while current is not None:
        message = str(current).lower()
        if "database is locked" in message or "database table is locked" in message:
            return True
        current = current.__cause__ or current.__context__
    return False


async def retry_sqlite_locked(
    operation: Callable[[], Awaitable[_T]],
    *,
    delays: tuple[float, ...] = _SQLITE_LOCK_RETRY_DELAYS,
) -> _T:
    """Retry a database-only, re-entrant operation after bounded lock contention.

    Callers must keep network, filesystem and event-bus side effects outside the
    operation.  The bounded schedule prevents hidden infinite retries.
    """
    for attempt in range(len(delays) + 1):
        try:
            return await operation()
        except Exception as exc:
            if not is_sqlite_locked_error(exc) or attempt >= len(delays):
                raise
            delay = delays[attempt]
            logger.warning(
                "SQLite busy/locked; retrying database operation in %.2fs (%d/%d)",
                delay, attempt + 1, len(delays),
            )
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")

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
        conn: ConnectionProtocol | None = None
        try:
            conn = await aiosqlite.connect(self.database, **connect_params)
            # PRAGMAs are connection-local except journal_mode. Apply the full
            # policy to every pooled connection instead of relying on the
            # synchronous migration connection's side effects.
            async def configure_connection() -> None:
                assert conn is not None
                async with conn.cursor() as cursor:
                    # Set busy_timeout first so journal-mode negotiation itself
                    # waits briefly for an existing writer.
                    await cursor.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
                    await cursor.execute("PRAGMA foreign_keys=ON")
                    await cursor.execute("PRAGMA journal_mode=WAL")
                    await cursor.execute("PRAGMA synchronous=NORMAL")

            await retry_sqlite_locked(configure_connection)
        except BaseException:
            # PRAGMA negotiation can fail after the aiosqlite worker starts.
            # Always close that partially initialized connection.
            if conn is not None:
                try:
                    await conn.close()
                except Exception:
                    pass
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

    async def aio_execute_sql(self, sql, params=None, fetch_results=None):
        # A statement rejected with SQLITE_BUSY/LOCKED has not completed. It is
        # therefore safe to retry the statement itself with a small bounded
        # backoff. Higher-level multi-statement transitions still need their
        # own transaction retry (see retry_sqlite_locked).
        async def execute():
            return await super(AioSqliteDatabase, self).aio_execute_sql(
                sql, params, fetch_results=fetch_results
            )

        return await retry_sqlite_locked(execute)


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
    _start_auto_backup()


async def shutdown() -> None:
    global _db, _db_path
    await _stop_auto_backup()
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


def prune_old_backups(keep: int | None = None) -> int:
    """按保留数清理旧备份（轮转），返回删除的份数。默认保留 _BACKUP_KEEP_COUNT 份。"""
    keep = _BACKUP_KEEP_COUNT if keep is None else keep
    backup_dir = os.path.join(appPaths.DATA_DIR, "backups")
    if not os.path.isdir(backup_dir):
        return 0
    try:
        backups = sorted(
            (os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.endswith(".db")),
            key=os.path.getmtime,
        )
    except OSError:
        return 0
    removed = 0
    # 旧的在前，删除超出保留数的最早备份
    for path in backups[:-keep] if keep > 0 else backups:
        try:
            os.remove(path)
            removed += 1
        except OSError:
            logger.warning("Failed to remove old backup: %s", path)
    if removed:
        logger.info("Pruned %d old database backup(s), keeping latest %d", removed, keep)
    return removed


async def _auto_backup_loop() -> None:
    """后台定时备份循环：到点执行备份并轮转旧备份。间隔<=0 时禁用。"""
    if _AUTO_BACKUP_INTERVAL_SECONDS <= 0:
        logger.info("Automatic database backup disabled (interval<=0)")
        return
    logger.info(
        "Automatic database backup enabled: interval=%.0fs, keep=%d",
        _AUTO_BACKUP_INTERVAL_SECONDS, _BACKUP_KEEP_COUNT,
    )
    while True:
        await asyncio.sleep(_AUTO_BACKUP_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(backup_database)
            await asyncio.to_thread(prune_old_backups)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Automatic database backup failed")


def _start_auto_backup() -> None:
    """启动后台定时备份任务（幂等）。"""
    global _auto_backup_task
    if _auto_backup_task is not None or _AUTO_BACKUP_INTERVAL_SECONDS <= 0:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _auto_backup_task = loop.create_task(_auto_backup_loop())


async def _stop_auto_backup() -> None:
    """停止后台定时备份任务。"""
    global _auto_backup_task
    if _auto_backup_task is None:
        return
    _auto_backup_task.cancel()
    try:
        await _auto_backup_task
    except asyncio.CancelledError:
        pass
    _auto_backup_task = None
