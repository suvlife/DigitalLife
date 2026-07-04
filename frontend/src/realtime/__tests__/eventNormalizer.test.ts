import { describe, expect, it } from 'vitest';
import { normalizeWsEventPayload } from '../eventNormalizer';

describe('normalizeWsEventPayload', () => {
  it('normalizes room_status with current_turn_agent_id', () => {
    const event = normalizeWsEventPayload({
      event: 'room_status',
      gt_room: {
        id: 11,
        team_id: 7,
        name: 'general',
      },
      state: 'SCHEDULING',
      need_scheduling: true,
      current_turn_agent_id: 42,
    });

    expect(event).toEqual({
      type: 'room_status',
      teamId: 7,
      roomId: 11,
      state: 'scheduling',
      needScheduler: true,
      currentTurnAgentId: 42,
    });
  });

  it('normalizes message_changed db_id from id fallback', () => {
    const event = normalizeWsEventPayload({
      event: 'message_changed',
      gt_room: {
        id: 11,
        team_id: 7,
        name: 'general',
      },
      gt_message: {
        id: 28,
        sender_id: -1,
        sender_display_name: 'OPERATOR',
        content: '测试',
        send_time: '2026-05-24 00:05:57',
        seq: 1,
        insert_immediately: false,
      },
    });

    expect(event).toEqual({
      type: 'message_changed',
      teamId: 7,
      roomId: 11,
      roomName: 'general',
      message: {
        db_id: 28,
        sender_id: -1,
        sender_display_name: 'OPERATOR',
        content: '测试',
        time: '2026-05-24 00:05:57',
        seq: 1,
        insert_immediately: false,
      },
    });
  });

  it('normalizes usage_updated token stats', () => {
    const event = normalizeWsEventPayload({
      event: 'usage_updated',
      model: 'gpt-4o',
      prompt_tokens: 120,
      completion_tokens: 80,
      total_tokens: 200,
    });

    expect(event).toEqual({
      type: 'usage_updated',
      model: 'gpt-4o',
      promptTokens: 120,
      completionTokens: 80,
      totalTokens: 200,
    });
  });

  it('normalizes usage_updated with missing numeric fields as zero', () => {
    const event = normalizeWsEventPayload({
      event: 'usage_updated',
      model: 'claude-3-5-sonnet',
    });

    expect(event).toEqual({
      type: 'usage_updated',
      model: 'claude-3-5-sonnet',
      promptTokens: 0,
      completionTokens: 0,
      totalTokens: 0,
    });
  });

  it('returns null for unknown usage payloads without an event type', () => {
    expect(normalizeWsEventPayload({ foo: 'bar' })).toBeNull();
  });
});
