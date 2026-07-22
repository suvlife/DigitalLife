import { describe, it, expect } from 'vitest';
import { calculateRunProgress, deriveRoomRuntime, npcStatusFromActivity, activityLabel } from './status';
import type { Activity, Room, Task } from './types';

const baseActivity = (patch: Partial<Activity> = {}): Activity => ({
  id: 1, agentId: 7, teamId: 1, roomId: 2, type: 'llm_infer', status: 'started',
  title: '', detail: '', startedAt: '2026-01-01T00:00:00Z', finishedAt: null, metadata: {}, ...patch,
});
const room: Room = {
  id: 2, teamId: 1, name: '经世阁', i18n: {}, type: 'group', state: 'SCHEDULING',
  needScheduling: true, currentTurnAgentId: 7, agentIds: [7, 8], tags: [],
};
let n = 0;
const task = (status: string): Task => ({
  id: ++n, teamId: 1, roomId: 2, assigneeId: 7, title: '任务', description: '',
  status, priority: 'NORMAL', result: '', updatedAt: null,
});

describe('npcStatusFromActivity', () => {
  it('maps inference and reasoning to thinking', () => {
    expect(npcStatusFromActivity(baseActivity())).toBe('thinking');
    expect(npcStatusFromActivity(baseActivity({ type: 'reasoning' }))).toBe('thinking');
  });
  it('maps retry with started to retrying', () => {
    expect(npcStatusFromActivity(baseActivity({ metadata: { retry_attempt: 2 } }))).toBe('retrying');
  });
  it('maps chat_reply to speaking', () => {
    expect(npcStatusFromActivity(baseActivity({ type: 'chat_reply' }))).toBe('speaking');
  });
  it('maps failed status to failed', () => {
    expect(npcStatusFromActivity(baseActivity({ status: 'failed' }))).toBe('failed');
  });
  it('returns idle for empty', () => {
    expect(npcStatusFromActivity(null)).toBe('idle');
    expect(npcStatusFromActivity(undefined)).toBe('idle');
  });
});

describe('activityLabel', () => {
  it('uses agent name in label', () => {
    expect(activityLabel('thinking', '诸葛先生')).toContain('诸葛先生');
    expect(activityLabel('thinking', '诸葛先生')).toContain('思考');
  });
  it('falls back to 大师', () => {
    expect(activityLabel('speaking')).toContain('大师');
  });
});

describe('deriveRoomRuntime', () => {
  it('derives completed room from all-done tasks', () => {
    const result = deriveRoomRuntime({ ...room, needScheduling: false, state: 'IDLE' }, [task('DONE'), task('DONE')], []);
    expect(result.status).toBe('completed');
    expect(result.progress).toBe(100);
    expect(result.completedTasks).toBe(2);
  });
  it('derives discussing room with speaker from latest activity', () => {
    const result = deriveRoomRuntime(room, [task('IN_PROGRESS')], [baseActivity()], (id) => id ? '诸葛先生' : '大师');
    expect(result.status).toBe('discussing');
    expect(result.currentNpcStatus).toBe('thinking');
    expect(result.activityLabel).toContain('诸葛先生');
  });
  it('marks failed when a task failed', () => {
    const result = deriveRoomRuntime({ ...room, needScheduling: false, state: 'IDLE' }, [task('FAILED')], []);
    expect(result.status).toBe('failed');
    expect(result.error).toBeDefined();
  });
});

describe('calculateRunProgress', () => {
  it('returns 100 for completed/failed phases', () => {
    const rooms = [deriveRoomRuntime({ ...room, needScheduling: false, state: 'IDLE' }, [task('DONE')], [])];
    expect(calculateRunProgress(rooms, 'completed')).toBe(100);
    expect(calculateRunProgress(rooms, 'failed')).toBe(100);
  });
  it('is monotonic across phases', () => {
    const rooms = [deriveRoomRuntime({ ...room, needScheduling: false, state: 'IDLE' }, [task('DONE')], [])];
    const discussing = calculateRunProgress(rooms, 'discussing');
    const synthesizing = calculateRunProgress(rooms, 'synthesizing');
    const publishing = calculateRunProgress(rooms, 'publishing');
    expect(synthesizing).toBeGreaterThan(discussing);
    expect(publishing).toBeGreaterThan(synthesizing);
  });
  it('returns 0 for empty rooms in non-terminal phase', () => {
    expect(calculateRunProgress([], 'discussing')).toBe(0);
  });
});
