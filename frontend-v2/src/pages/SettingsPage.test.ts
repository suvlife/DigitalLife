import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import SettingsPage from './SettingsPage.vue';

const mocks = vi.hoisted(() => {
  const teams = [{ id: 1, name: '青云院', enabled: true, config: {}, i18n: {} }];
  return {
    teams,
    loadTeams: vi.fn(async () => undefined),
    getTeamDetail: vi.fn(async (id: number) => ({ id, name: id === 2 ? '新院' : '青云院', i18n: {}, working_directory: '/tmp/qingyun', config: { slogan: '求真' }, enabled: true, agents: [], rooms: [] })),
    getTeamMembers: vi.fn(async () => []), getDeptTree: vi.fn(async () => null), saveTeamMembers: vi.fn(), clearAgentData: vi.fn(), saveDeptTree: vi.fn(), createTeamRoom: vi.fn(), updateTeamRoom: vi.fn(), updateTeamRoomAgents: vi.fn(), deleteTeamRoom: vi.fn(),
    createTeam: vi.fn(async () => ({ status: 'ok', id: 2, name: '新院' })),
    modifyTeam: vi.fn(async () => ({ status: 'ok', name: '青云院' })),
    setTeamEnabled: vi.fn(async () => ({ status: 'ok', enabled: false })),
    deleteTeam: vi.fn(async () => ({ status: 'ok', name: '青云院' })),
    clearTeamData: vi.fn(async () => ({ status: 'ok', team_id: 1, deleted: { tasks: 1, histories: 0, messages: 2, rooms: 0, activities: 3 } })),
    exportTeam: vi.fn(async () => ({ name: '青云院', config: {}, rule_templates: [], agents: [], preset_rooms: [], auto_start: false })),
    getLlmServiceConfig: vi.fn(async () => ({ llm_services: [{ name: '主模型', base_url: 'https://llm.test', api_key: '', has_api_key: true, type: 'openai-compatible', model: 'model-a', enable: true, extra_headers: {} }], default_llm_server: '主模型' })),
    createLlmService: vi.fn(), modifyLlmService: vi.fn(), deleteLlmService: vi.fn(), setDefaultLlmService: vi.fn(), testLlmService: vi.fn(async () => ({ status: 'ok', message: '连接成功' })),
    getLlmProviderCatalog: vi.fn(async () => ([{ id: 'kimi', display_name: { 'zh-CN': 'Kimi' }, type: 'openai-compatible', base_url: 'https://api.moonshot.cn/v1', default_model: 'kimi-latest', signup_url: '', models: ['kimi-latest', 'moonshot-v1-8k'] }])),
    providerDisplayName: (entry: { display_name?: Record<string, string>; id: string }) => entry.display_name?.['zh-CN'] || entry.id,
    createLlmServiceFromProvider: vi.fn(async () => ({ status: 'ok', index: 1, service: { name: 'Kimi' } })),
    getLlmFallback: vi.fn(async () => ({ default_llm_server: '主模型', fallback_llm_servers: [] })),
    setLlmFallback: vi.fn(async () => ({ status: 'ok' })),
    getSearchConfig: vi.fn(async () => ({ enabled: true, max_content_length: 8000, max_fetch_bytes: 5242880, providers: [] })),
    updateSearchSettings: vi.fn(async () => ({ status: 'ok' })), createSearchProvider: vi.fn(async () => ({ status: 'ok', index: 0 })), modifySearchProvider: vi.fn(async () => ({ status: 'ok' })), deleteSearchProvider: vi.fn(async () => ({ status: 'ok', deleted_provider: 'tavily' })),
    getRoleTemplates: vi.fn(async () => []), createRoleTemplate: vi.fn(), modifyRoleTemplate: vi.fn(), deleteRoleTemplate: vi.fn(),
    getSkills: vi.fn(async () => []), getTools: vi.fn(async () => []),
    getGhostConfig: vi.fn(async () => ({ enabled: false, api_url: '', admin_api_key: '', content_api_key: '', auto_publish: true, publish_status: 'published', has_admin_key: false, has_content_key: false })),
    saveGhostConfig: vi.fn(), testGhostConfig: vi.fn(async () => ({ success: true, message: '连接成功' })),
    getSystemStatus: vi.fn(async () => ({ initialized: true, version: '2.0.0', auto_check_update: false })), backupDatabase: vi.fn(), checkUpdate: vi.fn(), updateSystemConfig: vi.fn(),
  };
});

vi.mock('../store/world', () => ({ world: { state: { teams: mocks.teams, team: null }, loadTeams: mocks.loadTeams } }));
vi.mock('../api/client', () => mocks);

function makeRouter(path: string) {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', name: 'home', component: { template: '<div />' } },
    { path: '/teams/:teamId', name: 'team', component: { template: '<div />' } },
    { path: '/settings/:section?', name: 'settings', component: SettingsPage },
  ] });
  return router.push(path).then(() => router.isReady()).then(() => router);
}
async function mountAt(path: string) { const router = await makeRouter(path); const wrapper = mount(SettingsPage, { global: { plugins: [router] } }); await flushPromises(); return { wrapper, router }; }

beforeEach(() => {
  vi.clearAllMocks();
  mocks.teams.splice(0, mocks.teams.length, { id: 1, name: '青云院', enabled: true, config: {}, i18n: {} });
  mocks.loadTeams.mockImplementation(async () => undefined);
  mocks.createTeam.mockImplementation(async () => { mocks.teams.push({ id: 2, name: '新院', enabled: true, config: {}, i18n: {} }); return { status: 'ok', id: 2, name: '新院' }; });
});

describe('SettingsPage V2', () => {
  it('normalizes an illegal section and keeps a valid team query in sync', async () => {
    const { wrapper, router } = await mountAt('/settings/not-a-section?teamId=1');
    expect(wrapper.text()).toContain('院落管理');
    expect(router.currentRoute.value.params.section).toBeUndefined();
    expect(router.currentRoute.value.query.teamId).toBe('1');
  });

  it('creates a team, refreshes the roster, selects it, and updates the route', async () => {
    const { wrapper, router } = await mountAt('/settings/teams?teamId=1');
    await wrapper.get('input[aria-label="新院名称"]').setValue('新院');
    await wrapper.get('input[aria-label="新院工作目录"]').setValue('/tmp/new');
    const create = wrapper.findAll('button').find(button => button.text() === '创建院落');
    expect(create).toBeTruthy(); await create!.trigger('click'); await flushPromises();
    expect(mocks.createTeam).toHaveBeenCalledWith({ name: '新院', working_directory: '/tmp/new' });
    expect(mocks.getTeamDetail).toHaveBeenCalledWith(2);
    expect(router.currentRoute.value.query.teamId).toBe('2');
    expect(wrapper.text()).toContain('新院已创建并选中');
  });

  it('tests a saved LLM service entirely inside the V2 models section', async () => {
    const { wrapper } = await mountAt('/settings/models?teamId=1');
    const testButton = wrapper.findAll('button').find(button => button.text() === '测试');
    expect(testButton).toBeTruthy(); await testButton!.trigger('click'); await flushPromises();
    expect(mocks.testLlmService).toHaveBeenCalledWith({ mode: 'saved', index: 0 });
    expect(wrapper.text()).toContain('主模型：连接成功');
    expect(wrapper.find('a[href*="legacy"]').exists()).toBe(false);
  });
});
