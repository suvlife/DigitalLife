-- Ghost publication outbox: idempotent, persistent and recoverable across restarts.
CREATE TABLE IF NOT EXISTS blog_publications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    publication_key TEXT NOT NULL UNIQUE,
    source_type     TEXT NOT NULL DEFAULT 'FINAL_CONCLUSION',
    source_id       TEXT NOT NULL,
    team_id         INTEGER,
    room_id         INTEGER,
    run_id          INTEGER,
    title           TEXT NOT NULL,
    markdown_content TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    tags            TEXT NOT NULL DEFAULT '[]',
    status          TEXT NOT NULL DEFAULT 'PENDING',
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    next_retry_at   DATETIME,
    ghost_post_id   TEXT,
    post_url        TEXT,
    last_error      TEXT NOT NULL DEFAULT '',
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_blog_publications_status_retry
    ON blog_publications(status, next_retry_at, id);
CREATE INDEX IF NOT EXISTS idx_blog_publications_run_id ON blog_publications(run_id);
CREATE INDEX IF NOT EXISTS idx_blog_publications_source
    ON blog_publications(source_type, source_id);
