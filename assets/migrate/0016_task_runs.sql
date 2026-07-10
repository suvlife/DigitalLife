-- 用户问题运行实例及房间级进度快照。
-- 0017 预留给 Ghost publication worker。

CREATE TABLE IF NOT EXISTS task_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id             INTEGER NOT NULL,
    root_room_id        INTEGER NOT NULL,
    user_message_id     INTEGER,
    owner_user_id       INTEGER,
    title               TEXT NOT NULL DEFAULT '',
    query               TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'QUEUED',
    progress_percent    INTEGER NOT NULL DEFAULT 0,
    total_rooms         INTEGER NOT NULL DEFAULT 0,
    active_rooms        INTEGER NOT NULL DEFAULT 0,
    completed_rooms     INTEGER NOT NULL DEFAULT 0,
    failed_rooms        INTEGER NOT NULL DEFAULT 0,
    total_agents        INTEGER NOT NULL DEFAULT 0,
    active_agents       INTEGER NOT NULL DEFAULT 0,
    started_at          DATETIME,
    finished_at         DATETIME,
    final_message_id    INTEGER,
    final_answer        TEXT NOT NULL DEFAULT '',
    blog_publish_status TEXT NOT NULL DEFAULT 'NOT_STARTED',
    blog_post_id        TEXT,
    blog_post_url       TEXT,
    error_message       TEXT,
    metadata            TEXT NOT NULL DEFAULT '{}',
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_task_runs_user_message_id
    ON task_runs(user_message_id) WHERE user_message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_task_runs_team_status ON task_runs(team_id, status, id);
CREATE INDEX IF NOT EXISTS idx_task_runs_owner_id ON task_runs(owner_user_id, id);
CREATE INDEX IF NOT EXISTS idx_task_runs_root_room_id ON task_runs(root_room_id, id);

CREATE TABLE IF NOT EXISTS room_runs (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                 INTEGER NOT NULL,
    team_id                INTEGER NOT NULL,
    room_id                INTEGER NOT NULL,
    dept_id                INTEGER,
    status                 TEXT NOT NULL DEFAULT 'WAITING',
    progress_percent       INTEGER NOT NULL DEFAULT 0,
    current_agent_id       INTEGER,
    current_activity       TEXT,
    started_at             DATETIME,
    finished_at            DATETIME,
    message_count          INTEGER NOT NULL DEFAULT 0,
    expected_contributors  INTEGER NOT NULL DEFAULT 0,
    completed_contributors INTEGER NOT NULL DEFAULT 0,
    last_activity_at       DATETIME,
    error_message          TEXT,
    metadata               TEXT NOT NULL DEFAULT '{}',
    created_at             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, room_id)
);
CREATE INDEX IF NOT EXISTS idx_room_runs_run_status ON room_runs(run_id, status, id);
CREATE INDEX IF NOT EXISTS idx_room_runs_room_id ON room_runs(room_id, id);
CREATE INDEX IF NOT EXISTS idx_room_runs_team_id ON room_runs(team_id, id);
