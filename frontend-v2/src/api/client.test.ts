import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from './client';

function mockJson(body: unknown = { status: 'ok' }) {
  const response = () => new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
  const fetchMock = vi.fn().mockImplementation(async () => response());
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function requestAt(fetchMock: ReturnType<typeof vi.fn>, index = 0) {
  const [path, init] = fetchMock.mock.calls[index] as [string, RequestInit];
  return { path, init, body: init.body ? JSON.parse(String(init.body)) : undefined };
}

beforeEach(() => vi.restoreAllMocks());

describe('run snapshot API normalization', () => {
  it('normalizes backend snake_case snapshot payloads', () => {
    const run = api.normalizeRunSnapshot({ run: { id: 9, team_id: 2, root_room_id: 4, status: 'DISCUSSING', progress_percent: 58, query: '问策', final_answer: '', blog_publish_status: 'PENDING' }, rooms: [{ run_id: 9, room_id: 4, status: 'DISCUSSING', progress_percent: 50, current_agent_id: 72, current_activity: 'THINKING', completed_contributors: 1, expected_contributors: 2 }] });
    expect(run?.id).toBe('9');
    expect(run?.teamId).toBe(2);
    expect(run?.rootRoomId).toBe(4);
    expect(run?.progress).toBe(58);
    expect(run?.roomRuns[4].currentNpcStatus).toBe('thinking');
    expect(run?.activeAgentIds).toEqual([72]);
    expect(run?.publication.status).toBe('pending');
  });

  it('loads a run-bounded timeline and preserves room ids', async () => {
    const fetchMock = mockJson({ timeline: [{ db_id: 3, room_id: 8, sender_id: 2, content: '历史研判', send_time: '2026-07-01T10:00:00' }] });
    const messages = await api.getRunTimeline('12');
    expect(requestAt(fetchMock).path).toBe('/runs/12/timeline.json?limit=500');
    expect(messages[0]).toMatchObject({ id: 3, roomId: 8, content: '历史研判' });
  });
});

describe('run archive API normalization', () => {
  it('normalizes list records without fetching run details', () => {
    const run = api.normalizeRunArchiveEntry({ id: 12, team_id: 3, title: '年度规划', query: '如何安排下一年度？', status: 'TaskRunStatus.COMPLETED', progress_percent: 100, blog_publish_status: 'PUBLISHED', blog_post_url: 'https://example.test/post', created_at: '2026-07-11T08:00:00' });
    expect(run).toMatchObject({ id: '12', teamId: 3, title: '年度规划', question: '如何安排下一年度？', phase: 'completed', progress: 100 });
    expect(run.publication).toEqual({ status: 'published', url: 'https://example.test/post' });
  });
});

describe('settings API client', () => {
  it('loads the typed LLM configuration while retaining the settings-page list helper', async () => {
    const payload = { llm_services: [{ name: 'main', base_url: 'https://llm.test/v1', api_key: '', has_api_key: true, type: 'openai-compatible', model: 'gpt-test', enable: true, extra_headers: {} }], default_llm_server: 'main' };
    const fetchMock = mockJson(payload);

    await expect(api.getLlmServiceConfig()).resolves.toEqual(payload);
    await expect(api.getLlmServices()).resolves.toEqual(payload.llm_services);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(requestAt(fetchMock).path).toBe('/config/llm_services/list.json');
  });

  it('supports all LLM mutations and connection tests', async () => {
    const fetchMock = mockJson();
    const service: api.LlmServiceCreatePayload = { name: 'main', base_url: 'https://llm.test/v1', api_key: 'secret', type: 'openai-compatible', model: 'gpt-test', enable: true, extra_headers: {}, provider_params: {} };
    await api.createLlmService(service);
    await api.modifyLlmService(2, { model: 'gpt-next', enable: false });
    await api.deleteLlmService(2);
    await api.setDefaultLlmService(1);
    await api.testLlmService({ mode: 'saved', index: 1 });

    expect(requestAt(fetchMock, 0)).toMatchObject({ path: '/config/llm_services/create.json', body: service });
    expect(requestAt(fetchMock, 1)).toMatchObject({ path: '/config/llm_services/2/modify.json', body: { model: 'gpt-next', enable: false } });
    expect(requestAt(fetchMock, 2).path).toBe('/config/llm_services/2/delete.json');
    expect(requestAt(fetchMock, 3).path).toBe('/config/llm_services/1/set_default.json');
    expect(requestAt(fetchMock, 4)).toMatchObject({ path: '/config/llm_services/test.json', body: { mode: 'saved', index: 1 } });
    for (const index of [0, 1, 2, 3, 4]) expect(requestAt(fetchMock, index).init.method).toBe('POST');
  });

  it('gets, saves, and tests Ghost without clearing omitted secrets', async () => {
    const fetchMock = mockJson({ success: true });
    await api.getGhostConfig();
    await api.saveGhostConfig({ enabled: true, api_url: 'https://ghost.test', publish_status: 'draft' });
    await api.testGhostConfig({ api_url: 'https://ghost.test', admin_api_key: 'id:secret' });

    expect(requestAt(fetchMock, 0).path).toBe('/config/ghost.json');
    expect(requestAt(fetchMock, 1)).toMatchObject({ path: '/config/ghost.json', body: { enabled: true, api_url: 'https://ghost.test', publish_status: 'draft' } });
    expect(requestAt(fetchMock, 2)).toMatchObject({ path: '/config/ghost/test.json', body: { api_url: 'https://ghost.test', admin_api_key: 'id:secret' } });
  });

  it('supports system status, backup, update checking, and update preferences', async () => {
    const fetchMock = mockJson();
    await api.getSystemStatus();
    await api.backupDatabase();
    await api.checkUpdate(true);
    await api.updateSystemConfig({ auto_check_update: false });

    expect(requestAt(fetchMock, 0).path).toBe('/system/status.json');
    expect(requestAt(fetchMock, 1)).toMatchObject({ path: '/system/database/backup.json' });
    expect(requestAt(fetchMock, 1).init.method).toBe('POST');
    expect(requestAt(fetchMock, 2).path).toBe('/system/check_update.json?force=true');
    expect(requestAt(fetchMock, 3)).toMatchObject({ path: '/system/update_config.json', body: { auto_check_update: false } });
  });

  it('supports team create, enable, delete, clear, and export endpoints', async () => {
    const fetchMock = mockJson();
    await api.createTeam({ name: '新院', working_directory: '/tmp/new', config: { slogan: '求真' } });
    await api.setTeamEnabled(7, false);
    await api.deleteTeam(7);
    await api.clearTeamData(7);
    await api.exportTeam(7);

    expect(requestAt(fetchMock, 0)).toMatchObject({ path: '/teams/create.json', body: { name: '新院', working_directory: '/tmp/new', config: { slogan: '求真' } } });
    expect(requestAt(fetchMock, 1)).toMatchObject({ path: '/teams/7/set_enabled.json', body: { enabled: false } });
    expect(requestAt(fetchMock, 2).path).toBe('/teams/7/delete.json');
    expect(requestAt(fetchMock, 3).path).toBe('/teams/7/clear_data.json');
    expect(requestAt(fetchMock, 4).path).toBe('/teams/7/export_preset.json');
  });

  it('supports member, department, room, and per-agent operations', async () => {
    const fetchMock = mockJson({ agents: [] });
    await api.getTeamMembers(7); await api.saveTeamMembers(7, [{ id: null, name: '诸葛', role_template_id: 3, model: 'gpt-x', driver: 'native' }]); await api.clearAgentData(11); await api.getDeptTree(7); await api.saveDeptTree(7, { name: '总院', responsibility: '统筹', manager_id: 11, agent_ids: [11, 12], children: [] }); await api.createTeamRoom(7, { name: '中军帐', agent_ids: [-1, 11], initial_topic: '问策', max_rounds: 9 }); await api.updateTeamRoom(7, 5, { name: '新中军帐', initial_topic: '新题', max_rounds: 12 }); await api.updateTeamRoomAgents(7, 5, [-1, 12]); await api.deleteTeamRoom(7, 5);
    expect(requestAt(fetchMock, 0).path).toBe('/agents/list.json?team_id=7'); expect(requestAt(fetchMock, 1)).toMatchObject({ path: '/teams/7/agents/save.json', body: { agents: [{ id: null, name: '诸葛', role_template_id: 3, model: 'gpt-x', driver: 'native' }] } }); expect(requestAt(fetchMock, 2).path).toBe('/agents/11/clear_data.json'); expect(requestAt(fetchMock, 4).init.method).toBe('PUT'); expect(requestAt(fetchMock, 5)).toMatchObject({ path: '/teams/7/rooms/create.json', body: { name: '中军帐', agent_ids: [-1, 11], initial_topic: '问策', max_rounds: 9 } }); expect(requestAt(fetchMock, 7)).toMatchObject({ path: '/teams/7/rooms/5/agents/modify.json', body: { agent_ids: [-1, 12] } }); expect(requestAt(fetchMock, 8).path).toBe('/teams/7/rooms/5/delete.json');
  });

  it('normalizes role templates and supports complete CRUD', async () => {
    const fetchMock = mockJson({ role_templates: [{ id: 3, name: '谋士', i18n: { display_name: { 'zh-CN': '谋士' } }, soul: '善谋', type: 'USER' }] });
    await expect(api.getRoleTemplates()).resolves.toEqual([{ id: 3, name: '谋士', i18n: { display_name: { 'zh-CN': '谋士' } }, soul: '善谋', type: 'USER' }]);

    fetchMock.mockImplementation(async () => new Response(JSON.stringify({ id: 3, name: '谋士', soul: '善谋', type: 'USER' }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    await api.getRoleTemplate(3);
    await api.createRoleTemplate({ name: '学士', soul: '博学' });
    await api.modifyRoleTemplate(3, { name: '军师', soul: '决断' });
    await api.deleteRoleTemplate(3);

    expect(requestAt(fetchMock, 1).path).toBe('/role_templates/3.json');
    expect(requestAt(fetchMock, 2)).toMatchObject({ path: '/role_templates/create.json', body: { name: '学士', soul: '博学' } });
    expect(requestAt(fetchMock, 3)).toMatchObject({ path: '/role_templates/3/modify.json', body: { name: '军师', soul: '决断' } });
    expect(requestAt(fetchMock, 4).path).toBe('/role_templates/3/delete.json');
  });

  it('lists available skills and tools', async () => {
    const fetchMock = mockJson({ skills: [{ name: 'research', description: '研究', is_builtin: true, files: ['SKILL.md'] }] });
    await expect(api.getSkills()).resolves.toEqual([{ name: 'research', description: '研究', is_builtin: true, files: ['SKILL.md'] }]);
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ tools: [{ name: 'Read', category: 'READ' }] }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    await expect(api.getTools()).resolves.toEqual([{ name: 'Read', category: 'READ' }]);
    expect(requestAt(fetchMock, 0).path).toBe('/config/skills/list.json');
    expect(requestAt(fetchMock, 1).path).toBe('/config/tools/list.json');
  });

  it('adds the bearer token to settings requests', async () => {
    localStorage.setItem('teamagent_token', 'token-123');
    const fetchMock = mockJson({ initialized: true });
    await api.getSystemStatus();
    expect(new Headers(requestAt(fetchMock).init.headers).get('Authorization')).toBe('Bearer token-123');
  });
});

describe('provider preset, fallback, search, and dossier clients', () => {
  it('loads the provider catalog and creates a service from a preset', async () => {
    const fetchMock = mockJson({ providers: [{ id: 'kimi', display_name: { 'zh-CN': 'Kimi' }, type: 'openai-compatible', base_url: 'https://api.moonshot.cn/v1', default_model: 'kimi-latest', signup_url: 'https://x', models: ['kimi-latest', 'moonshot-v1-8k'] }] });
    const catalog = await api.getLlmProviderCatalog();
    expect(requestAt(fetchMock).path).toBe('/config/llm_providers/catalog.json');
    expect(catalog[0]).toMatchObject({ id: 'kimi', base_url: 'https://api.moonshot.cn/v1', models: ['kimi-latest', 'moonshot-v1-8k'] });
    expect(api.providerDisplayName(catalog[0])).toBe('Kimi');
    await api.createLlmServiceFromProvider({ provider_id: 'kimi', api_key: 'sk-1', model: 'kimi-latest', name: '主脑' });
    expect(requestAt(fetchMock, 1)).toMatchObject({ path: '/config/llm_services/from_provider.json', body: { provider_id: 'kimi', api_key: 'sk-1', model: 'kimi-latest', name: '主脑' } });
    expect(requestAt(fetchMock, 1).init.method).toBe('POST');
  });

  it('reads and writes the LLM fallback chain', async () => {
    const fetchMock = mockJson({ default_llm_server: 'main', fallback_llm_servers: ['backup-a', 'backup-b'] });
    const info = await api.getLlmFallback();
    expect(requestAt(fetchMock).path).toBe('/config/llm_services/fallback.json');
    expect(info).toEqual({ default_llm_server: 'main', fallback_llm_servers: ['backup-a', 'backup-b'] });
    await api.setLlmFallback(['backup-a']);
    expect(requestAt(fetchMock, 1)).toMatchObject({ path: '/config/llm_services/fallback.json', body: { fallback_llm_servers: ['backup-a'] } });
    expect(requestAt(fetchMock, 1).init.method).toBe('POST');
  });

  it('reads masked search config and mutates providers', async () => {
    const fetchMock = mockJson({ enabled: true, max_content_length: 8000, max_fetch_bytes: 5242880, providers: [{ provider: 'tavily', enable: true, api_keys: ['****abcd'], api_keys_count: 1, has_api_key: true }] });
    const config = await api.getSearchConfig();
    expect(requestAt(fetchMock).path).toBe('/config/search.json');
    expect(config.providers[0]).toMatchObject({ provider: 'tavily', api_keys_count: 1, has_api_key: true });
    await api.updateSearchSettings({ enabled: false, max_content_length: 9000, max_fetch_bytes: 1048576 });
    await api.createSearchProvider({ provider: 'brave', api_keys: ['k1', 'k2'], enable: true });
    await api.modifySearchProvider(0, { clear_api_keys: true });
    await api.deleteSearchProvider(1);
    expect(requestAt(fetchMock, 1)).toMatchObject({ path: '/config/search/settings.json', body: { enabled: false, max_content_length: 9000, max_fetch_bytes: 1048576 } });
    expect(requestAt(fetchMock, 2)).toMatchObject({ path: '/config/search/providers/create.json', body: { provider: 'brave', api_keys: ['k1', 'k2'], enable: true } });
    expect(requestAt(fetchMock, 3)).toMatchObject({ path: '/config/search/providers/0/modify.json', body: { clear_api_keys: true } });
    expect(requestAt(fetchMock, 4).path).toBe('/config/search/providers/1/delete.json');
    for (const index of [1, 2, 3, 4]) expect(requestAt(fetchMock, index).init.method).toBe('POST');
  });

  it('lists dossiers and reads a single dossier with normalized run', async () => {
    const listMock = mockJson({ dossiers: [{ run: { id: 5, team_id: 2, title: '卷一', query: '问', status: 'COMPLETED', progress_percent: 100, blog_publish_status: 'PUBLISHED', blog_post_url: 'https://p' }, report_path: 'outputs/a.md', report_ready: true, has_conclusion: true }] });
    const dossiers = await api.getDossiers(2, 30);
    expect(requestAt(listMock).path).toBe('/runs/dossiers/list.json?team_id=2&limit=30');
    expect(dossiers[0]).toMatchObject({ reportPath: 'outputs/a.md', reportReady: true, hasConclusion: true });
    expect(dossiers[0].run).toMatchObject({ id: '5', teamId: 2, phase: 'completed', progress: 100 });

    const detailMock = mockJson({ run: { id: 5, team_id: 2, title: '卷一', query: '问', status: 'COMPLETED' }, content: '# 结论', report_path: 'outputs/a.md', report_ready: true, has_conclusion: true });
    const dossier = await api.getDossier(5);
    expect(requestAt(detailMock).path).toBe('/runs/5/dossier.json');
    expect(dossier).toMatchObject({ content: '# 结论', reportPath: 'outputs/a.md', reportReady: true, hasConclusion: true });
  });
});

describe('authentication contract', () => {
  it('includes cookie credentials and exposes 401 as authentication-required state', async () => {
    const { auth } = await import('./auth');
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error_desc: '请登录或输入访问 Token' }), { status: 401, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(api.getTeams()).rejects.toMatchObject({ status: 401 });
    expect(requestAt(fetchMock).init.credentials).toBe('include');
    expect(auth.state.required).toBe(true);
  });
});

describe('team-scoped file URLs', () => {
  it('includes team_id while keeping the file path relative and encoded', () => {
    expect(api.fileDownloadUrl('outputs/综合报告.md', 17)).toBe('/files/download.json?team_id=17&path=outputs%2F%E7%BB%BC%E5%90%88%E6%8A%A5%E5%91%8A.md');
  });
});

describe('authenticated file downloads', () => {
  it('uses bearer and cookie credentials for blob downloads', async () => {
    localStorage.setItem('teamagent_token', 'file-token');
    const fetchMock = vi.fn().mockResolvedValue(new Response(new Blob(['report']), { status: 200, headers: { 'Content-Disposition': "attachment; filename*=UTF-8''report.md" } }));
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('URL', { ...URL, createObjectURL: vi.fn(() => 'blob:test'), revokeObjectURL: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    await api.downloadFile('outputs/report.md', 8);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.credentials).toBe('include');
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer file-token');
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test');
  });

  it('surfaces 401 and requests authentication', async () => {
    const { auth } = await import('./auth');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error_desc: '请先登录' }), { status: 401, headers: { 'Content-Type': 'application/json' } })));
    await expect(api.downloadFile('outputs/report.md', 8)).rejects.toMatchObject({ status: 401 });
    expect(auth.state.required).toBe(true);
  });
});

describe('XSRF token header', () => {
  it('sends X-Xsrftoken on POST requests when _xsrf cookie is present', async () => {
    document.cookie = '_xsrf=xsrf-test-token';
    const fetchMock = mockJson({ status: 'ok' });
    await api.deleteTeam(1);
    expect(new Headers(requestAt(fetchMock).init.headers).get('X-Xsrftoken')).toBe('xsrf-test-token');
  });

  it('does not send X-Xsrftoken on GET requests', async () => {
    document.cookie = '_xsrf=xsrf-test-token';
    const fetchMock = mockJson({ initialized: true });
    await api.getSystemStatus();
    expect(new Headers(requestAt(fetchMock).init.headers).get('X-Xsrftoken')).toBeNull();
  });

  it('omits X-Xsrftoken when no _xsrf cookie is set', async () => {
    document.cookie = '_xsrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT';
    const fetchMock = mockJson({ status: 'ok' });
    await api.deleteTeam(1);
    expect(new Headers(requestAt(fetchMock).init.headers).get('X-Xsrftoken')).toBeNull();
  });
});
