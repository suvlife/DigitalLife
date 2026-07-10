import sqlite3
from pathlib import Path

from src import db

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "assets" / "migrate"


def test_0017_creates_blog_publication_outbox(tmp_path: Path) -> None:
    db_path = tmp_path / "publication.db"
    db.migrate_database(db_path, migrations_dir=MIGRATIONS_DIR)
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(blog_publications)")}
        assert {"publication_key", "markdown_content", "content_hash", "status", "next_retry_at", "post_url", "run_id"} <= columns
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(blog_publications)")}
        assert "idx_blog_publications_status_retry" in indexes
        assert "sqlite_autoindex_blog_publications_1" in indexes
