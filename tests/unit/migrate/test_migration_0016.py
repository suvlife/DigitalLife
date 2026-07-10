from __future__ import annotations

import sqlite3
from pathlib import Path

import db


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info('{table}')").fetchall()}


def test_migration_0016_creates_task_and_room_runs(tmp_path: Path) -> None:
    db_path = tmp_path / "runs.db"
    applied = db.migrate_database(db_path)
    assert "0016_task_runs.sql" in applied

    with sqlite3.connect(db_path) as conn:
        assert {
            "team_id", "root_room_id", "user_message_id", "owner_user_id", "status",
            "progress_percent", "final_answer", "blog_publish_status",
        } <= _columns(conn, "task_runs")
        assert {
            "run_id", "room_id", "status", "progress_percent", "current_agent_id",
            "current_activity", "expected_contributors", "completed_contributors",
        } <= _columns(conn, "room_runs")
        unique_indexes = conn.execute("PRAGMA index_list('room_runs')").fetchall()
        assert any(row[2] == 1 for row in unique_indexes)
