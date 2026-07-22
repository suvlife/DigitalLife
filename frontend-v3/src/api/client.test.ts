import { describe, it, expect } from 'vitest';
import {
  activity, task, normalizeRoomRuntime, normalizeRunSnapshot, normalizeRunArchiveEntry,
  providerDisplayName,
} from './client';

describe('activity normalizer', () => {
  it('maps fields with snake_case to camelCase', () => {
    const a = activity({
      id: 5, agent_id: 7, team_id: 1, room_id: 2, activity_type: 'LLM_INFER',
      status: 'STARTED', title: '推演', detail: '细节', started_at: '2026-01-01', finished_at: null,
    });
    expect(a.id).toBe(5);
    expect(a.agentId).toBe(7);
    expect(a.roomId).toBe(2);
    expect(a.type).toBe('llm_infer');
    expect(a.status).toBe('started');
    expect(a.title).toBe('推演');
  });
  it('falls back to metadata.room_id when room_id absent', () => {
    const a = activity({ id: 1, agent_id: 1, team_id: 1, metadata: { room_id: 9 } });
    expect(a.roomId).toBe(9);
  });
  it('uses detail or error_message', () => {
    expect(activity({ id: 1, error_message: '出错' }).detail).toBe('出错');
  });
  it('defaults unknown type', () => {
    expect(activity({}).type).toBe('unknown');
  });
});

describe('task normalizer', () => {
  it('maps task fields', () => {
    const t = task({
      id: 3, team_id: 1, room_id: 2, assignee_id: 7, title: '任务', description: '描述',
      status: 'IN_PROGRESS', priority: 'HIGH', result: '结果', updated_at: '2026-01-01',
    });
    expect(t.id).toBe(3);
    expect(t.assigneeId).toBe(7);
    expect(t.status).toBe('IN_PROGRESS');
    expect(t.priority).toBe('HIGH');
  });
  it('defaults status and priority', () => {
    const t = task({ id: 1, team_id: 1 });
    expect(t.status).toBe('TODO');
    expect(t.priority).toBe('NORMAL');
  });
  it('handles null room_id', () => {
    expect(task({ id: 1, team_id: 1, room_id: null }).roomId).toBeNull();
  });
});

describe('normalizeRoomRuntime', () => {
  it('clamps completed/failed to 100', () => {
    expect(normalizeRoomRuntime({ room_id: 1, status: 'COMPLETED', progress_percent: 50 }).progress).toBe(100);
    expect(normalizeRoomRuntime({ room_id: 1, status: 'failed', progress: 30 }).progress).toBe(100);
  });
  it('boosts synthesizing to at least 92', () => {
    const r = normalizeRoomRuntime({ room_id: 1, status: 'synthesizing', progress_percent: 40 });
    expect(r.progress).toBeGreaterThanOrEqual(92);
  });
  it('keeps reported progress otherwise', () => {
    expect(normalizeRoomRuntime({ room_id: 1, status: 'discussing', progress_percent: 55 }).progress).toBe(55);
  });
  it('nulls non-positive current_agent_id', () => {
    expect(normalizeRoomRuntime({ room_id: 1, status: 'waiting', current_agent_id: 0 }).currentAgentId).toBeNull();
    expect(normalizeRoomRuntime({ room_id: 1, status: 'waiting', current_agent_id: 5 }).currentAgentId).toBe(5);
  });
});

describe('normalizeRunSnapshot', () => {
  it('returns null for missing/invalid run', () => {
    expect(normalizeRunSnapshot(null)).toBeNull();
    expect(normalizeRunSnapshot({})).toBeNull();
    expect(normalizeRunSnapshot({ run: { id: 0 } })).toBeNull();
  });
  it('maps run with rooms into roomRuns', () => {
    const snap = normalizeRunSnapshot({
      run: { id: 42, team_id: 1, status: 'DISCUSSING', progress_percent: 30, query: '问' },
      rooms: [
        { room_id: 1, status: 'COMPLETED', current_agent_id: 0 },
        { room_id: 2, status: 'DISCUSSING', current_agent_id: 7 },
      ],
    });
    expect(snap).not.toBeNull();
    expect(snap!.id).toBe('42');
    expect(snap!.phase).toBe('discussing');
    expect(Object.keys(snap!.roomRuns)).toHaveLength(2);
    expect(snap!.roomRuns[1].status).toBe('completed');
    expect(snap!.completedRoomIds).toContain(1);
    expect(snap!.activeAgentIds).toContain(7);
  });
  it('maps publication fields', () => {
    const snap = normalizeRunSnapshot({
      run: { id: 1, team_id: 1, blog_publish_status: 'published', blog_post_url: 'https://blog.example/p' },
      rooms: [],
    });
    expect(snap!.publication.status).toBe('published');
    expect(snap!.publication.url).toBe('https://blog.example/p');
  });
});

describe('normalizeRunArchiveEntry', () => {
  it('clamps progress to 0-100 and maps phase', () => {
    const e = normalizeRunArchiveEntry({ id: 9, team_id: 1, status: 'COMPLETED', progress_percent: 150 });
    expect(e.id).toBe('9');
    expect(e.progress).toBe(100);
    expect(e.phase).toBe('completed');
  });
  it('handles missing progress', () => {
    expect(normalizeRunArchiveEntry({ id: 1, team_id: 1 }).progress).toBe(0);
  });
});

describe('providerDisplayName', () => {
  it('picks zh-CN', () => {
    expect(providerDisplayName({ id: 'qwen', display_name: { 'zh-CN': '通义千问', en: 'Qwen' } })).toBe('通义千问');
  });
  it('falls back to en then id', () => {
    expect(providerDisplayName({ id: 'qwen', display_name: { en: 'Qwen' } })).toBe('Qwen');
    expect(providerDisplayName({ id: 'qwen', display_name: {} })).toBe('qwen');
  });
});

describe('normalizePublicationStatus', () => {
  it('maps known statuses', () => {
    // 间接验证（函数未导出，通过 normalizeRunSnapshot 间接测）
    const mk = (s: string) => normalizeRunSnapshot({ run: { id: 1, team_id: 1, blog_publish_status: s }, rooms: [] })!.publication.status;
    expect(mk('published')).toBe('published');
    expect(mk('publishing')).toBe('publishing');
    expect(mk('failed')).toBe('failed');
    expect(mk('')).toBe('idle');
  });
});
