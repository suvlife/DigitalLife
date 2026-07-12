import sqlite3
from pathlib import Path

from src import db

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "assets" / "migrate"


def test_0018_adds_ghost_remote_identity_and_lease_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "publication-lease.db"
    db.migrate_database(db_path, migrations_dir=MIGRATIONS_DIR)
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(blog_publications)")}
        assert {"ghost_slug", "worker_token", "lease_expires_at"} <= columns
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(blog_publications)")}
        assert {
            "idx_blog_publications_ghost_slug",
            "idx_blog_publications_worker_token",
            "idx_blog_publications_lease",
        } <= indexes
