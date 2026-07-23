from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import db

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "assets/migrate"


def _setup_db_before_0019(db_path: Path) -> None:
    db.migrate_database(db_path, migrations_dir=MIGRATIONS_DIR, up_to="19")


def _insert_activity(db_path: Path, *, metadata: dict | None) -> None:
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "INSERT INTO agent_activities"
            " (agent_id, team_id, activity_type, status, title, detail,"
            "  started_at, metadata, created_at, updated_at)"
            " VALUES (1, 1, 'LLM_INFER', 'SUCCEEDED', '推理', '',"
            "         '2026-07-20 10:00:00', ?, '2026-07-20 10:00:00', '2026-07-20 10:00:00')",
            (json.dumps(metadata) if metadata is not None else None,),
        )


def test_0019_backfills_room_id_from_task_room_id(tmp_path: Path) -> None:
    """历史数据回填：room_id 取自 metadata.task_room_id（实际写入键）。"""
    db_path = tmp_path / "test.db"
    _setup_db_before_0019(db_path)
    _insert_activity(db_path, metadata={"task_room_id": 42, "model": "gpt-x"})
    _insert_activity(db_path, metadata={"model": "gpt-x"})  # 无房间归属
    _insert_activity(db_path, metadata={})  # 空 metadata

    db.migrate_database(db_path, migrations_dir=MIGRATIONS_DIR, up_to="20")

    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute(
            "SELECT id, room_id FROM agent_activities ORDER BY id"
        ).fetchall()
    assert rows[0][1] == 42, "task_room_id=42 应回填到 room_id 列"
    assert rows[1][1] is None, "无 task_room_id 的 metadata 应为 NULL"
    assert rows[2][1] is None, "空 metadata 应为 NULL"


def test_0019_creates_room_id_index(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    _setup_db_before_0019(db_path)

    db.migrate_database(db_path, migrations_dir=MIGRATIONS_DIR, up_to="20")

    with sqlite3.connect(str(db_path)) as conn:
        indexes = {
            row[1]
            for row in conn.execute(
                "PRAGMA index_list('agent_activities')"
            ).fetchall()
        }
        # 索引可用性：按 room_id 过滤不再全表扫描 json_extract
        conn.execute(
            "INSERT INTO agent_activities"
            " (agent_id, team_id, room_id, activity_type, status, title, detail,"
            "  started_at, metadata, created_at, updated_at)"
            " VALUES (1, 1, 7, 'LLM_INFER', 'SUCCEEDED', '推理', '',"
            "         '2026-07-20 10:00:00', '{}', '2026-07-20 10:00:00', '2026-07-20 10:00:00')"
        )
        row = conn.execute(
            "SELECT room_id FROM agent_activities WHERE room_id = 7"
        ).fetchone()
    assert "idx_agent_activities_room_id" in indexes
    assert row[0] == 7
