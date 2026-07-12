-- Reliable Ghost outbox claims and stable remote identity.
ALTER TABLE blog_publications ADD COLUMN ghost_slug TEXT;
ALTER TABLE blog_publications ADD COLUMN worker_token TEXT;
ALTER TABLE blog_publications ADD COLUMN lease_expires_at DATETIME;
CREATE INDEX IF NOT EXISTS idx_blog_publications_ghost_slug
    ON blog_publications(ghost_slug);
CREATE INDEX IF NOT EXISTS idx_blog_publications_worker_token
    ON blog_publications(worker_token);
CREATE INDEX IF NOT EXISTS idx_blog_publications_lease
    ON blog_publications(lease_expires_at);
