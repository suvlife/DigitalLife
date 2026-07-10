import { describe, expect, it } from 'vitest';
import { normalizeRunSnapshot } from './client';

describe('run snapshot API normalization', () => {
  it('normalizes backend snake_case snapshot payloads', () => {
    const run = normalizeRunSnapshot({ run: { id: 9, team_id: 2, status: 'DISCUSSING', progress_percent: 58, query: '问策', final_answer: '', blog_publish_status: 'PENDING' }, rooms: [{ run_id: 9, room_id: 4, status: 'DISCUSSING', progress_percent: 50, current_agent_id: 72, current_activity: 'THINKING', completed_contributors: 1, expected_contributors: 2 }] });
    expect(run?.id).toBe('9');
    expect(run?.teamId).toBe(2);
    expect(run?.progress).toBe(58);
    expect(run?.roomRuns[4].currentNpcStatus).toBe('thinking');
    expect(run?.activeAgentIds).toEqual([72]);
    expect(run?.publication.status).toBe('pending');
  });
});
