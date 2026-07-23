import sqlite3
from pathlib import Path

from scripts.backup_and_migrate import backup_and_migrate, restore_backup


def test_backup_migrate_and_restore_roundtrip(tmp_path, monkeypatch):
    database = tmp_path / "data.db"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
        conn.execute("INSERT INTO sentinel VALUES ('before')")
    config = tmp_path / "config"
    config.mkdir()
    (config / "setting.json").write_text('{"db_path": "%s", "llm_services": []}' % database.as_posix())

    migrated, backup = backup_and_migrate(str(config), str(tmp_path / "backups"))
    assert migrated == database
    assert backup.is_file()
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT value FROM sentinel").fetchone()[0] == "before"
        assert conn.execute("SELECT name FROM _migrations ORDER BY name DESC LIMIT 1").fetchone()[0] == "0019_agent_activity_room_id.sql"
        conn.execute("UPDATE sentinel SET value='after'")
    restore_backup(str(database), str(backup))
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT value FROM sentinel").fetchone()[0] == "before"
