#!/usr/bin/env python3
"""Create a verified SQLite backup, apply migrations, and print rollback instructions."""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import db  # noqa: E402
from util import configUtil  # noqa: E402


def backup_and_migrate(config_dir: str | None, backup_dir: str | None) -> tuple[Path, Path]:
    configured = configUtil.load(config_dir).setting.db_path
    database = db.resolve_db_path(configured)
    if not database.is_file():
        raise FileNotFoundError(f"Database does not exist: {database}")
    target_dir = Path(backup_dir).expanduser().resolve() if backup_dir else database.parent / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = target_dir / f"{database.name}.{stamp}.bak"

    source_conn = sqlite3.connect(str(database), timeout=30)
    target_conn = sqlite3.connect(str(backup), timeout=30)
    try:
        source_conn.backup(target_conn)
        result = target_conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"Backup integrity check failed: {result}")
    finally:
        target_conn.close()
        source_conn.close()

    db.migrate_database(str(database))
    with sqlite3.connect(str(database), timeout=30) as migrated:
        result = migrated.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"Migrated database integrity check failed: {result}")
    return database, backup


def restore_backup(database: str, backup: str) -> None:
    database_path = Path(database).expanduser().resolve()
    backup_path = Path(backup).expanduser().resolve()
    if not backup_path.is_file():
        raise FileNotFoundError(f"Backup does not exist: {backup_path}")
    with sqlite3.connect(str(backup_path)) as conn:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"Backup integrity check failed: {result}")
    temp = database_path.with_name(database_path.name + ".restore.tmp")
    shutil.copy2(backup_path, temp)
    # The service must be stopped before rollback. Remove stale WAL/SHM sidecars
    # so SQLite cannot replay post-backup writes over the restored main file.
    for suffix in ("-wal", "-shm"):
        try:
            Path(str(database_path) + suffix).unlink()
        except FileNotFoundError:
            pass
    os.replace(temp, database_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir")
    parser.add_argument("--backup-dir")
    parser.add_argument("--restore", nargs=2, metavar=("DATABASE", "BACKUP"))
    args = parser.parse_args()
    if args.restore:
        restore_backup(*args.restore)
        print(f"Restored {args.restore[0]} from {args.restore[1]}")
        return
    database, backup = backup_and_migrate(args.config_dir, args.backup_dir)
    print(f"Migrated: {database}")
    print(f"Verified backup: {backup}")
    print(f"Rollback: {sys.executable} {Path(__file__).resolve()} --restore {database} {backup}")


if __name__ == "__main__":
    main()
