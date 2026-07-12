from __future__ import annotations

import os
import re
import sqlite3

import pytest

import appPaths
from service import ormService


def test_backup_database_creates_timestamped_copy_under_backups_dir(tmp_path, monkeypatch) -> None:
    source_db_path = tmp_path / "runtime.db"
    with sqlite3.connect(source_db_path) as conn:
        conn.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        conn.execute("INSERT INTO demo (name) VALUES (?)", ("alice",))
        conn.commit()

    data_dir = tmp_path / "data"
    monkeypatch.setattr(appPaths, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(ormService, "_db_path", str(source_db_path))

    backup_path = ormService.backup_database()

    assert os.path.isfile(backup_path)
    assert os.path.dirname(backup_path) == os.path.join(str(data_dir), "backups")
    assert re.fullmatch(r"runtime_\d{8}_\d{6}_\d{6}\.db", os.path.basename(backup_path))

    with sqlite3.connect(backup_path) as conn:
        rows = conn.execute("SELECT id, name FROM demo").fetchall()
    assert rows == [(1, "alice")]


def test_backup_database_requires_started_orm(monkeypatch) -> None:
    monkeypatch.setattr(ormService, "_db_path", None)

    with pytest.raises(RuntimeError, match="ormService not started"):
        ormService.backup_database()

@pytest.mark.asyncio
async def test_pool_applies_runtime_sqlite_pragmas_to_every_connection(tmp_path) -> None:
    database = ormService.AioSqliteDatabase(str(tmp_path / "pragma.db"), timeout=1)
    await database.aio_connect()
    try:
        async with database.aio_connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute("PRAGMA journal_mode")
                assert (await cursor.fetchone())[0].lower() == "wal"
                await cursor.execute("PRAGMA busy_timeout")
                assert (await cursor.fetchone())[0] == ormService._SQLITE_BUSY_TIMEOUT_MS
                await cursor.execute("PRAGMA foreign_keys")
                assert (await cursor.fetchone())[0] == 1
                await cursor.execute("PRAGMA synchronous")
                # NORMAL is represented by integer 1.
                assert (await cursor.fetchone())[0] == 1
    finally:
        await database.aio_close()


@pytest.mark.asyncio
async def test_retry_sqlite_locked_is_bounded(monkeypatch) -> None:
    attempts = 0

    async def always_locked():
        nonlocal attempts
        attempts += 1
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ormService.asyncio, "sleep", lambda _delay: _completed_sleep())
    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        await ormService.retry_sqlite_locked(always_locked, delays=(0.01, 0.02))
    assert attempts == 3


async def _completed_sleep() -> None:
    return None

@pytest.mark.asyncio
async def test_async_write_waits_for_external_sqlite_writer_and_succeeds(tmp_path) -> None:
    db_path = tmp_path / "contended.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE counter (id INTEGER PRIMARY KEY, value INTEGER NOT NULL)")
        conn.execute("INSERT INTO counter VALUES (1, 0)")
        conn.commit()

    database = ormService.AioSqliteDatabase(str(db_path), timeout=1)
    await database.aio_connect()
    blocker = sqlite3.connect(db_path, timeout=1, check_same_thread=False)
    blocker.execute("PRAGMA journal_mode=WAL")
    blocker.execute("BEGIN IMMEDIATE")
    blocker.execute("UPDATE counter SET value = 1 WHERE id = 1")

    async def release_writer() -> None:
        import asyncio
        await asyncio.sleep(0.1)
        blocker.commit()
        blocker.close()

    release_task = __import__("asyncio").create_task(release_writer())
    try:
        await database.aio_execute_sql("UPDATE counter SET value = value + 1 WHERE id = 1")
        await release_task
        async with database.aio_connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute("SELECT value FROM counter WHERE id = 1")
                assert (await cursor.fetchone())[0] == 2
    finally:
        if not release_task.done():
            blocker.rollback()
            blocker.close()
            await release_task
        await database.aio_close()
