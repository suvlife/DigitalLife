-- 多租户：团队和角色模板加 owner_user_id
-- NULL = 公共/系统预设（所有用户可见）
-- 非 NULL = 用户私有（仅 owner 和 admin 可见）

ALTER TABLE teams ADD COLUMN owner_user_id INTEGER;
CREATE INDEX IF NOT EXISTS idx_teams_owner_user_id ON teams(owner_user_id);

ALTER TABLE role_templates ADD COLUMN owner_user_id INTEGER;
CREATE INDEX IF NOT EXISTS idx_role_templates_owner_user_id ON role_templates(owner_user_id);

-- 现有团队设为公共（owner_user_id = NULL）
-- 现有 SYSTEM 角色模板设为公共
-- 现有 USER 角色模板归属到第一个 admin 用户
UPDATE role_templates SET owner_user_id = (SELECT id FROM users WHERE role='ADMIN' ORDER BY id LIMIT 1) WHERE type = 'USER';
