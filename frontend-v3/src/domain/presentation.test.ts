import { describe, it, expect } from 'vitest';
import { localized, masterName, speakerName, taskStatusText, priorityText, roomStatusText, activityNarrative, activityDetail, activityNpcStatus, taskTheme } from './presentation';
import type { Activity, Agent, Task } from './types';

const agent = (name: string, i18n?: Record<string, Record<string, string>>): Agent => ({
  id: 1, teamId: 1, name, i18n: i18n || {}, status: 'idle',
});

describe('localized', () => {
  it('picks zh-CN first', () => {
    expect(localized({ display_name: { 'zh-CN': '中文名', zh: '别' } }, 'display_name')).toBe('中文名');
  });
  it('falls back to zh / zh_CN', () => {
    expect(localized({ display_name: { zh: '中文' } }, 'display_name')).toBe('中文');
    expect(localized({ display_name: { zh_CN: '中文2' } }, 'display_name')).toBe('中文2');
  });
  it('returns fallback when absent', () => {
    expect(localized({}, 'display_name', '兜底')).toBe('兜底');
    expect(localized(undefined, 'display_name', '兜底')).toBe('兜底');
  });
});

describe('masterName', () => {
  it('uses i18n display_name', () => {
    expect(masterName(agent('raw', { display_name: { 'zh-CN': '诸葛先生' } }))).toBe('诸葛先生');
  });
  it('uses alias when no i18n', () => {
    expect(masterName(agent('synthesizer'))).toBe('综合研判官');
    expect(masterName(agent('operator'))).toBe('问道之人');
  });
  it('falls back to name then 无名先生', () => {
    expect(masterName(agent('某大师'))).toBe('某大师');
    expect(masterName(null)).toBe('无名先生');
  });
});

describe('speakerName', () => {
  it('prefers agent masterName', () => {
    expect(speakerName('raw', agent('synthesizer'))).toBe('综合研判官');
  });
  it('uses alias for raw when no agent', () => {
    expect(speakerName('OPERATOR')).toBe('问道之人');
  });
  it('falls back to 来客', () => {
    expect(speakerName('')).toBe('来客');
  });
});

describe('task/priority/room status text', () => {
  it('maps task status', () => {
    expect(taskStatusText('TODO')).toBe('待参详');
    expect(taskStatusText('IN_PROGRESS')).toBe('推演中');
    expect(taskStatusText('DONE')).toBe('已圆满');
    expect(taskStatusText('FAILED')).toBe('遇阻');
  });
  it('maps priority', () => {
    expect(priorityText('HIGH')).toBe('紧要');
    expect(priorityText('LOW')).toBe('从容');
    expect(priorityText('UNKNOWN')).toBe('寻常');
  });
  it('maps room status', () => {
    expect(roomStatusText('discussing')).toBe('众师推演中');
    expect(roomStatusText('completed')).toBe('本室议毕');
    expect(roomStatusText(undefined)).toBe('静候开议');
  });
});

const activity = (patch: Partial<Activity> = {}): Activity => ({
  id: 1, agentId: 1, teamId: 1, roomId: 1, type: 'llm_infer', status: 'started',
  title: '', detail: '', startedAt: null, finishedAt: null, metadata: {}, ...patch,
});

describe('activity narrative/detail/npc', () => {
  it('narrative handles failed and succeeded', () => {
    expect(activityNarrative(activity({ status: 'failed' }), '诸葛')).toContain('阻碍');
    expect(activityNarrative(activity({ type: 'chat_reply', status: 'succeeded' }), '诸葛')).toContain('陈述');
  });
  it('detail hides internal activity types', () => {
    expect(activityDetail(activity({ title: 'reasoning' }))).toBe('');
    expect(activityDetail(activity({ title: '压缩上下文' }))).toBe('');
    expect(activityDetail(activity({ title: '可见的标题' }))).toBe('可见的标题');
  });
  it('activityNpcStatus maps types', () => {
    expect(activityNpcStatus(activity({ type: 'chat_reply' }))).toBe('speaking');
    expect(activityNpcStatus(activity({ type: 'tool_call' }))).toBe('working');
    expect(activityNpcStatus(activity({ status: 'failed' }))).toBe('failed');
  });
});

describe('taskTheme', () => {
  it('uses first task description', () => {
    const tasks: Task[] = [{ id: 1, teamId: 1, roomId: 1, assigneeId: 1, title: 'T', description: '题目', status: 'TODO', priority: 'NORMAL', result: '', updatedAt: null }];
    expect(taskTheme(tasks, null)).toBe('题目');
  });
  it('falls back to initialTopic then question then default', () => {
    expect(taskTheme([], '初始议题')).toBe('初始议题');
    expect(taskTheme([], null, '用户提问')).toBe('用户提问');
    expect(taskTheme([], null)).toContain('静候');
  });
});
