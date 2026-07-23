-- 活动记录增加 room_id 冗余列（与 metadata.task_room_id 同源），
-- 替代 json_extract 无索引全表扫描；同时修复查询侧键名（$.room_id）与写入侧
-- 键名（task_room_id）不匹配导致按房间过滤恒为空的问题。
ALTER TABLE agent_activities ADD COLUMN room_id INTEGER;
CREATE INDEX IF NOT EXISTS idx_agent_activities_room_id ON agent_activities(room_id);

-- 历史数据回填：实际写入键为 task_room_id
UPDATE agent_activities
SET room_id = CAST(json_extract(metadata, '$.task_room_id') AS INTEGER)
WHERE json_extract(metadata, '$.task_room_id') IS NOT NULL;
