<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { world } from '../store/world';
import * as api from '../api/client';
import { safeExternalUrl } from '../utils/safeUrl';
import SettingsConfirmDialog from '../components/settings-v2/SettingsConfirmDialog.vue';
import TeamConfigurationEditor from '../components/settings-v2/TeamConfigurationEditor.vue';

const route = useRoute();
const router = useRouter();
const sections = [
  { id: 'teams', label: '院落管理', note: '创建、资料与数据治理' },
  { id: 'models', label: '大模型服务', note: '预设、校验、首选与兜底' },
  { id: 'search', label: '搜网密钥', note: '搜索引擎与多 key 轮询' },
  { id: 'roles', label: '角色模板', note: '大师心法模板' },
  { id: 'capabilities', label: '武库清单', note: 'Skills 与 Tools（只读）' },
  { id: 'ghost', label: '博客刊行', note: 'Ghost 密钥与连通性' },
  { id: 'maintenance', label: '运行维护', note: '备份、版本与固定外观' },
] as const;
type SectionId = typeof sections[number]['id'];
const isSection = (value: unknown): value is SectionId => sections.some(item => item.id === value);
const section = ref<SectionId>(isSection(route.params.section) ? route.params.section : 'teams');
const selectedTeamId = ref(0);
const loading = ref(false);
const saving = ref(false);
const notice = ref('');
const error = ref('');
const currentSection = computed(() => sections.find(item => item.id === section.value)!);
const teams = computed(() => world.state.teams);

const teamDetail = ref<api.TeamDetail | null>(null);
const teamForm = reactive({ name: '', working_directory: '', slogan: '', rules: '' });
const newTeam = reactive({ name: '', working_directory: '' });
const deptTree = ref<api.DeptTreeNode | null>(null);
const presetFile = ref<HTMLInputElement | null>(null);

const llmServices = ref<api.LlmServiceInfo[]>([]);
const defaultLlm = ref<string | null>(null);
const llmEditing = ref<number | 'new' | null>(null);
const llmForm = reactive({ name: '', base_url: '', api_key: '', type: 'openai-compatible' as api.LlmServiceType, model: '', enable: true, temperature: '', extra_headers: '{}', provider_params: '{}' });
const llmTestResult = ref('');

// LLM 厂商预设（#5：预设下拉 + 多模型）
const providerCatalog = ref<api.LlmProviderCatalogEntry[]>([]);
const providerForm = reactive({ provider_id: '', api_key: '', model: '', name: '' });
const selectedProvider = computed(() => providerCatalog.value.find(p => p.id === providerForm.provider_id) || null);
const providerModels = computed(() => selectedProvider.value?.models || []);
const providerLabel = (entry: api.LlmProviderCatalogEntry) => api.providerDisplayName(entry);

// LLM 首选/兜底链（#3）
const fallbackServers = ref<string[]>([]);
const availableFallback = computed(() => llmServices.value.filter(s => s.name !== defaultLlm.value && !fallbackServers.value.includes(s.name)));

// 搜网密钥配置（#5：多引擎 + 多 key）
const search = reactive({ enabled: true, max_content_length: 8000, max_fetch_bytes: 5242880 });
const searchProviders = ref<api.SearchProviderInfo[]>([]);
const searchEditing = ref<number | 'new' | null>(null);
const searchForm = reactive({ provider: 'tavily', api_keys: '', enable: true });
const searchPresets = ['tavily', 'brave', 'bing'];

const roles = ref<api.RoleTemplate[]>([]);
const roleEditing = ref<number | 'new' | null>(null);
const roleForm = reactive({ name: '', soul: '' });
const skills = ref<api.SkillConfig[]>([]);
const tools = ref<api.ToolConfig[]>([]);

const ghost = reactive<api.GhostConfig>({ enabled: false, api_url: '', admin_api_key: '', content_api_key: '', auto_publish: true, publish_status: 'published', has_admin_key: false, has_content_key: false, skip_ssl_verify: false });
const ghostAdminKey = ref('');
const ghostContentKey = ref('');
const ghostTestResult = ref('');
const system = ref<api.SystemStatus | null>(null);
const backupResult = ref<api.DatabaseBackupResult | null>(null);
const updateResult = ref<api.UpdateCheckResult | null>(null);

const confirmation = reactive({ open: false, title: '', message: '', label: '', action: null as null | (() => Promise<void>) });
function ask(title: string, message: string, label: string, action: () => Promise<void>) {
  Object.assign(confirmation, { open: true, title, message, label, action });
}
async function confirmAction() {
  if (!confirmation.action || saving.value) return;
  saving.value = true; clearFeedback();
  try { await confirmation.action(); confirmation.open = false; }
  catch (e) { fail(e, '操作失败'); }
  finally { saving.value = false; }
}
function clearFeedback() { notice.value = ''; error.value = ''; }
function fail(e: unknown, fallback: string) { error.value = e instanceof Error ? e.message : fallback; }
function announce(message: string) { notice.value = message; error.value = ''; }
function parseObject(value: string, label: string): Record<string, unknown> {
  const parsed = JSON.parse(value || '{}');
  if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error(`${label}必须是 JSON 对象`);
  return parsed as Record<string, unknown>;
}
function downloadJson(data: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' });
  const url = URL.createObjectURL(blob); const link = document.createElement('a');
  link.href = url; link.download = filename; link.click(); URL.revokeObjectURL(url);
}

function routeTeamId() {
  const raw = Array.isArray(route.query.teamId) ? route.query.teamId[0] : route.query.teamId;
  const id = Number(raw || 0); return Number.isInteger(id) && id > 0 ? id : 0;
}
function syncRoute(nextSection = section.value, nextTeamId = selectedTeamId.value) {
  const params = nextSection === 'teams' ? {} : { section: nextSection };
  const query = nextTeamId ? { teamId: String(nextTeamId) } : {};
  const currentSectionParam = String(route.params.section || 'teams');
  if (currentSectionParam !== nextSection || String(route.query.teamId || '') !== String(nextTeamId || '')) {
    void router.replace({ name: 'settings', params, query });
  }
}
function chooseSection(id: SectionId) { section.value = id; syncRoute(id); }
function chooseTeam(id: number) { selectedTeamId.value = id; syncRoute(section.value, id); void loadTeamDetail(id); }
function leave() { void router.push(selectedTeamId.value ? { name: 'team', params: { teamId: selectedTeamId.value } } : { name: 'home' }); }

async function loadTeamDetail(id: number) {
  if (!id) { teamDetail.value = null; return; }
  loading.value = true; clearFeedback();
  try {
    const [detail, members, tree] = await Promise.all([api.getTeamDetail(id), api.getTeamMembers(id), api.getDeptTree(id)]); detail.agents = members; teamDetail.value = detail; deptTree.value = tree;
    Object.assign(teamForm, { name: detail.name, working_directory: detail.working_directory, slogan: String(detail.config.slogan || ''), rules: String(detail.config.rules || '') });
  } catch (e) { fail(e, '本院详情载入失败'); }
  finally { loading.value = false; }
}
async function refreshTeams(preferred = selectedTeamId.value) {
  await world.loadTeams();
  const available = teams.value;
  selectedTeamId.value = available.some(team => team.id === preferred) ? preferred : (available[0]?.id || 0);
  syncRoute(section.value, selectedTeamId.value);
  await loadTeamDetail(selectedTeamId.value);
}
async function createTeam() {
  if (!newTeam.name.trim()) { error.value = '请填写新院名称'; return; }
  saving.value = true; clearFeedback();
  try {
    const created = await api.createTeam({ name: newTeam.name.trim(), working_directory: newTeam.working_directory.trim() || undefined });
    newTeam.name = ''; newTeam.working_directory = ''; await refreshTeams(created.id); announce('新院已创建并选中');
  } catch (e) { fail(e, '创建失败'); } finally { saving.value = false; }
}
async function saveTeam() {
  if (!selectedTeamId.value || !teamForm.name.trim()) return;
  saving.value = true; clearFeedback();
  try {
    await api.modifyTeam(selectedTeamId.value, { name: teamForm.name.trim(), working_directory: teamForm.working_directory.trim(), config: { ...(teamDetail.value?.config || {}), slogan: teamForm.slogan, rules: teamForm.rules } });
    await refreshTeams(selectedTeamId.value); announce('本院基本资料已保存');
  } catch (e) { fail(e, '保存失败'); } finally { saving.value = false; }
}
async function toggleTeam() {
  if (!teamDetail.value) return;
  saving.value = true; clearFeedback();
  try { await api.setTeamEnabled(selectedTeamId.value, !teamDetail.value.enabled); await refreshTeams(); announce(teamDetail.value?.enabled ? '本院已启用' : '本院已停用'); }
  catch (e) { fail(e, '启停失败'); } finally { saving.value = false; }
}
function clearTeam() {
  if (!teamDetail.value) return;
  ask('清空院落运行数据', `将删除“${teamDetail.value.name}”的任务、消息、活动与运行房间，但保留院落配置。`, '确认清空', async () => {
    const result = await api.clearTeamData(selectedTeamId.value); announce(`数据已清理：任务 ${result.deleted.tasks}、消息 ${result.deleted.messages}、活动 ${result.deleted.activities}`);
  });
}
function removeTeam() {
  if (!teamDetail.value) return;
  const name = teamDetail.value.name;
  ask('删除院落', `将永久删除“${name}”及其配置。此操作不可撤销。`, '永久删除', async () => { await api.deleteTeam(selectedTeamId.value); await refreshTeams(0); announce(`“${name}”已删除`); });
}
async function exportCurrentTeam() {
  if (!teamDetail.value) return;
  saving.value = true; clearFeedback();
  try { const preset = await api.exportTeam(selectedTeamId.value); downloadJson(preset, `${teamDetail.value.name}-preset.json`); announce('院落预设已导出'); }
  catch (e) { fail(e, '导出失败'); } finally { saving.value = false; }
}

async function saveMembers(members: api.TeamMemberDetail[]) {
  if (!teamDetail.value) return;
  if (members.some(member => !member.name.trim() || !member.role_template_id)) { error.value = '每位成员都必须填写姓名并选择角色模板'; return; }
  saving.value = true; clearFeedback();
  try { await api.saveTeamMembers(selectedTeamId.value, members.map(member => ({ id: member.id > 0 ? member.id : null, name: member.name.trim(), role_template_id: member.role_template_id, model: member.model?.trim() || '', driver: member.driver || 'native', allow_tools: member.allow_tools, allow_skills: member.allow_skills }))); await loadTeamDetail(selectedTeamId.value); announce('成员名册、角色与模型配置已保存'); }
  catch (e) { fail(e, '成员保存失败'); } finally { saving.value = false; }
}
function clearAgent(member: api.TeamMemberDetail) { ask('清理成员历史数据', `将清理“${member.name}”的执行历史，但保留成员配置。`, '确认清理', async () => { const result = await api.clearAgentData(member.id); announce(`“${member.name}”数据已清理：历史 ${result.deleted.histories || 0} 条`); }); }
function validateDept(node: api.DeptTreeNode): string | null { if (!node.name.trim()) return '部门名称不能为空'; if (node.agent_ids.length < 2) return `部门“${node.name}”至少需要两位成员`; if (!node.manager_id || !node.agent_ids.includes(node.manager_id)) return `部门“${node.name}”必须从本部门成员中选择负责人`; for (const child of node.children) { const found = validateDept(child); if (found) return found; } return null; }
async function saveDept(tree: api.DeptTreeNode) { const validation = validateDept(tree); if (validation) { error.value = validation; return; } saving.value = true; clearFeedback(); try { await api.saveDeptTree(selectedTeamId.value, tree); await loadTeamDetail(selectedTeamId.value); announce('组织与部门树已保存，部门研究室已同步'); } catch (e) { fail(e, '组织树保存失败'); } finally { saving.value = false; } }
async function saveRoom(room: api.TeamRoomDetail) { if (!room.name.trim()) { error.value = '请填写研究室名称'; return; } if (!room.agent_ids.length) { error.value = '研究室至少需要一位成员或操作者'; return; } saving.value = true; clearFeedback(); try { const payload = { name: room.name.trim(), type: room.type || 'group', initial_topic: room.initial_topic || '', max_rounds: room.max_rounds || 10 }; if (room.id > 0) { await api.updateTeamRoom(selectedTeamId.value, room.id, payload); await api.updateTeamRoomAgents(selectedTeamId.value, room.id, room.agent_ids); } else await api.createTeamRoom(selectedTeamId.value, { ...payload, agent_ids: room.agent_ids }); await loadTeamDetail(selectedTeamId.value); announce(`研究室“${room.name}”已保存`); } catch (e) { fail(e, '研究室保存失败'); } finally { saving.value = false; } }
function deleteRoom(room: api.TeamRoomDetail) { ask('删除研究室', `将永久删除“${room.name}”及其房间配置。`, '确认删除', async () => { await api.deleteTeamRoom(selectedTeamId.value, room.id); await loadTeamDetail(selectedTeamId.value); announce(`研究室“${room.name}”已删除`); }); }
async function saveTeamLlm(name: string) { if (!teamDetail.value) return; saving.value = true; clearFeedback(); try { await api.modifyTeam(selectedTeamId.value, { config: { ...teamDetail.value.config, llm_service_name: name || null } }); await loadTeamDetail(selectedTeamId.value); announce('团队默认模型已保存'); } catch (e) { fail(e, '团队模型保存失败'); } finally { saving.value = false; } }
function presetDeptToTree(node: Record<string, any>, ids: Map<string, number>): api.DeptTreeNode { return { name: String(node.dept_name || node.name || ''), responsibility: String(node.responsibility || ''), manager_id: ids.get(String(node.manager || '')) || null, agent_ids: (node.agents || []).map((name: unknown) => ids.get(String(name))).filter((id: number|undefined): id is number => Boolean(id)), children: (node.children || []).map((child: Record<string,any>) => presetDeptToTree(child, ids)) }; }
async function importPreset(event: Event) {
  const input = event.target as HTMLInputElement; const file = input.files?.[0]; input.value = ''; if (!file || !teamDetail.value) return; saving.value = true; clearFeedback();
  try { const preset = JSON.parse(await file.text()) as api.TeamPresetExport; if (!Array.isArray(preset.agents) || !Array.isArray(preset.preset_rooms)) throw new Error('预设缺少 agents 或 preset_rooms'); let availableRoles = [...roles.value]; for (const raw of preset.rule_templates || []) { const rule = raw as Record<string,unknown>; const name = String(rule.name || '').trim(); if (name && !availableRoles.some(role => role.name === name)) await api.createRoleTemplate({ name, soul: String(rule.soul || '') }); } roles.value = await api.getRoleTemplates(); availableRoles = roles.value; const members: api.TeamMemberSaveItem[] = preset.agents.map(raw => { const item=raw as Record<string,any>; const roleName=String(item.role_template || item.role || ''); const role=availableRoles.find(candidate=>candidate.name===roleName); if(!role) throw new Error(`找不到角色模板：${roleName}`); return { id:null, name:String(item.name||''), role_template_id:role.id, model:String(item.model||''), driver:String(item.driver||'native'), allow_tools:Array.isArray(item.allow_tools)?item.allow_tools.map(String):null, allow_skills:Array.isArray(item.allow_skills)?item.allow_skills.map(String):null }; }); await api.saveTeamMembers(selectedTeamId.value, members); const savedMembers = await api.getTeamMembers(selectedTeamId.value); const ids = new Map(savedMembers.map(member => [member.name, member.id])); if (preset.dept_tree) await api.saveDeptTree(selectedTeamId.value, presetDeptToTree(preset.dept_tree as Record<string,any>, ids)); const existing = (await api.getTeamDetail(selectedTeamId.value)).rooms.filter(room => !(room.biz_id || '').startsWith('DEPT:')); for (const room of existing) await api.deleteTeamRoom(selectedTeamId.value, room.id); for (const raw of preset.preset_rooms) { const room=raw as Record<string,any>; const agentIds=(room.agents||[]).map((name:unknown)=>String(name)==='OPERATOR'?-1:ids.get(String(name))).filter((id:number|undefined):id is number=>id!=null); await api.createTeamRoom(selectedTeamId.value,{name:String(room.name||''),type:'group',agent_ids:agentIds,initial_topic:String(room.initial_topic||''),max_rounds:Number(room.max_rounds||10)}); } await api.modifyTeam(selectedTeamId.value,{config:{...teamDetail.value.config,...(preset.config||{})}}); await loadTeamDetail(selectedTeamId.value); announce('团队预设已导入，成员、组织与研究室已重建'); } catch (e) { fail(e, '预设导入失败'); } finally { saving.value = false; }
}

async function loadLlm() { const data = await api.getLlmServiceConfig(); llmServices.value = data.llm_services; defaultLlm.value = data.default_llm_server; }
function editLlm(index: number | 'new') {
  if (index !== 'new') {
    const svc = llmServices.value[index];
    if (!svc || svc.is_builtin) return; // 内置服务不可编辑
  }
  llmEditing.value = index; llmTestResult.value = '';
  const value = index === 'new' ? null : llmServices.value[index];
  Object.assign(llmForm, value ? { name: value.name, base_url: value.base_url, api_key: '', type: value.type, model: value.model, enable: value.enable, temperature: value.temperature == null ? '' : String(value.temperature), extra_headers: JSON.stringify(value.extra_headers || {}, null, 2), provider_params: JSON.stringify(value.provider_params || {}, null, 2) } : { name: '', base_url: '', api_key: '', type: 'openai-compatible', model: '', enable: true, temperature: '', extra_headers: '{}', provider_params: '{}' });
}
function llmPayload() {
  const payload: api.LlmServiceCreatePayload = { name: llmForm.name.trim(), base_url: llmForm.base_url.trim(), api_key: llmForm.api_key, type: llmForm.type, model: llmForm.model.trim(), enable: llmForm.enable, extra_headers: parseObject(llmForm.extra_headers, '额外请求头') as Record<string, string>, provider_params: parseObject(llmForm.provider_params, '供应商参数') };
  if (llmForm.temperature !== '') payload.temperature = Number(llmForm.temperature);
  return payload;
}
async function saveLlm() {
  saving.value = true; clearFeedback();
  try {
    const payload = llmPayload(); if (!payload.name || !payload.base_url) throw new Error('服务名称和地址不能为空');
    if (llmEditing.value === 'new') await api.createLlmService(payload);
    else if (typeof llmEditing.value === 'number') { const svc = llmServices.value[llmEditing.value]; const realIndex = svc?.index ?? llmEditing.value; const { name: _name, ...rest } = payload; const patch: api.LlmServiceModifyPayload = { ...rest }; if (!patch.api_key) delete patch.api_key; await api.modifyLlmService(realIndex, patch); }
    await loadLlm(); llmEditing.value = null; announce('模型服务已保存');
  } catch (e) { fail(e, '模型服务保存失败'); } finally { saving.value = false; }
}
async function testEditingLlm() {
  saving.value = true; clearFeedback(); llmTestResult.value = '';
  try {
    const payload = llmPayload(); const result = await api.testLlmService({ mode: 'temp', base_url: payload.base_url, api_key: payload.api_key, type: payload.type, model: payload.model, extra_headers: payload.extra_headers, provider_params: payload.provider_params });
    llmTestResult.value = result.message + (result.detail?.duration_ms ? `（${result.detail.duration_ms}ms）` : '');
  } catch (e) { fail(e, '连接测试失败'); } finally { saving.value = false; }
}
async function testSavedLlm(index: number) {
  const svc = llmServices.value[index];
  if (!svc) return;
  // 使用后端返回的真实 index（内置服务为 -1，由后端特殊处理）
  const realIndex = svc.index ?? index;
  saving.value = true; clearFeedback();
  try { const result = await api.testLlmService({ mode: 'saved', index: realIndex }); announce(`${svc.name}：${result.message}`); }
  catch (e) { fail(e, '连接测试失败'); } finally { saving.value = false; }
}
async function makeDefaultLlm(index: number) {
  const svc = llmServices.value[index];
  if (!svc || svc.is_builtin) return;
  const realIndex = svc.index ?? index;
  saving.value = true; clearFeedback();
  try { await api.setDefaultLlmService(realIndex); await loadLlm(); await loadFallback(); announce('默认模型服务已更新'); }
  catch (e) { fail(e, '设置默认失败'); } finally { saving.value = false; }
}
function removeLlm(index: number) {
  const svc = llmServices.value[index];
  if (!svc || svc.is_builtin) return;
  const realIndex = svc.index ?? index;
  const name = svc.name; ask('删除模型服务', `确定删除”${name}”吗？`, '删除服务', async () => { await api.deleteLlmService(realIndex); await loadLlm(); await loadFallback(); announce(`”${name}”已删除`); }); }

watch(() => providerForm.provider_id, () => { providerForm.model = selectedProvider.value?.default_model || ''; });
async function loadProviderCatalog() { providerCatalog.value = await api.getLlmProviderCatalog(); }
async function createFromProvider() {
  if (!providerForm.provider_id) { error.value = '请选择厂商预设'; return; }
  if (!providerForm.api_key.trim()) { error.value = '请填写 API Key'; return; }
  saving.value = true; clearFeedback();
  try {
    const res = await api.createLlmServiceFromProvider({ provider_id: providerForm.provider_id, api_key: providerForm.api_key.trim(), model: providerForm.model.trim() || undefined, name: providerForm.name.trim() || undefined });
    Object.assign(providerForm, { provider_id: '', api_key: '', model: '', name: '' });
    await loadLlm(); announce(`已按预设创建「${res.service?.name || '模型服务'}」`);
  } catch (e) { fail(e, '按预设创建失败'); } finally { saving.value = false; }
}

async function loadFallback() { const data = await api.getLlmFallback(); fallbackServers.value = data.fallback_llm_servers; if (data.default_llm_server != null) defaultLlm.value = data.default_llm_server; }
function addFallback(name: string) { if (name && !fallbackServers.value.includes(name)) fallbackServers.value = [...fallbackServers.value, name]; }
function removeFallback(name: string) { fallbackServers.value = fallbackServers.value.filter(item => item !== name); }
function moveFallback(index: number, delta: number) { const next = index + delta; if (next < 0 || next >= fallbackServers.value.length) return; const arr = [...fallbackServers.value]; [arr[index], arr[next]] = [arr[next], arr[index]]; fallbackServers.value = arr; }
async function saveFallback() { saving.value = true; clearFeedback(); try { await api.setLlmFallback(fallbackServers.value); await loadFallback(); announce('兜底链已保存'); } catch (e) { fail(e, '兜底链保存失败'); } finally { saving.value = false; } }

async function loadSearch() { const data = await api.getSearchConfig(); Object.assign(search, { enabled: data.enabled, max_content_length: data.max_content_length, max_fetch_bytes: data.max_fetch_bytes }); searchProviders.value = data.providers; }
async function saveSearchSettings() { saving.value = true; clearFeedback(); try { await api.updateSearchSettings({ enabled: search.enabled, max_content_length: Number(search.max_content_length) || 0, max_fetch_bytes: Number(search.max_fetch_bytes) || 0 }); await loadSearch(); announce('搜索全局设置已保存'); } catch (e) { fail(e, '搜索设置保存失败'); } finally { saving.value = false; } }
function editSearch(index: number | 'new') { searchEditing.value = index; const value = index === 'new' ? null : searchProviders.value[index]; Object.assign(searchForm, value ? { provider: value.provider, api_keys: '', enable: value.enable } : { provider: 'tavily', api_keys: '', enable: true }); }
function parseSearchKeys(raw: string): string[] { return raw.split(/[\n,]+/).map(item => item.trim()).filter(Boolean); }
async function saveSearchProvider() {
  if (!searchForm.provider.trim()) { error.value = '请填写搜索引擎名称'; return; }
  saving.value = true; clearFeedback();
  try {
    const keys = parseSearchKeys(searchForm.api_keys);
    if (searchEditing.value === 'new') await api.createSearchProvider({ provider: searchForm.provider.trim(), api_keys: keys, enable: searchForm.enable });
    else if (typeof searchEditing.value === 'number') { const patch: api.SearchProviderModifyPayload = { provider: searchForm.provider.trim(), enable: searchForm.enable }; if (keys.length) patch.api_keys = keys; await api.modifySearchProvider(searchEditing.value, patch); }
    await loadSearch(); searchEditing.value = null; announce('搜索引擎已保存');
  } catch (e) { fail(e, '搜索引擎保存失败'); } finally { saving.value = false; }
}
function clearSearchKeys(index: number) { const name = searchProviders.value[index].provider; ask('清空搜索密钥', `将清空「${name}」的全部 API Key，引擎配置保留。`, '确认清空', async () => { await api.modifySearchProvider(index, { clear_api_keys: true }); await loadSearch(); announce(`「${name}」密钥已清空`); }); }
function removeSearchProvider(index: number) { const name = searchProviders.value[index].provider; ask('删除搜索引擎', `确定删除「${name}」吗？`, '删除引擎', async () => { await api.deleteSearchProvider(index); await loadSearch(); announce(`「${name}」已删除`); }); }

function editRole(role: api.RoleTemplate | null) { roleEditing.value = role?.id ?? 'new'; roleForm.name = role?.name || ''; roleForm.soul = role?.soul || ''; }
async function saveRole() { saving.value = true; clearFeedback(); try { if (!roleForm.name.trim() || !roleForm.soul.trim()) throw new Error('模板名称和心法内容不能为空'); const body = { name: roleForm.name.trim(), soul: roleForm.soul.trim() }; if (roleEditing.value === 'new') await api.createRoleTemplate(body); else if (typeof roleEditing.value === 'number') await api.modifyRoleTemplate(roleEditing.value, body); roles.value = await api.getRoleTemplates(); roleEditing.value = null; announce('角色模板已保存'); } catch (e) { fail(e, '模板保存失败'); } finally { saving.value = false; } }
function removeRole(role: api.RoleTemplate) { ask('删除角色模板', `确定删除“${role.name}”吗？已被成员引用的模板可能无法删除。`, '删除模板', async () => { await api.deleteRoleTemplate(role.id); roles.value = await api.getRoleTemplates(); announce(`“${role.name}”已删除`); }); }

async function saveGhost() {
  saving.value = true; clearFeedback();
  try { const patch: api.GhostConfigPatch = { enabled: ghost.enabled, api_url: ghost.api_url.trim(), auto_publish: ghost.auto_publish, publish_status: ghost.publish_status, skip_ssl_verify: ghost.skip_ssl_verify }; if (ghostAdminKey.value) patch.admin_api_key = ghostAdminKey.value; if (ghostContentKey.value) patch.content_api_key = ghostContentKey.value; await api.saveGhostConfig(patch); ghostAdminKey.value = ''; ghostContentKey.value = ''; Object.assign(ghost, await api.getGhostConfig()); announce('Ghost 设置与密钥已保存'); }
  catch (e) { fail(e, 'Ghost 保存失败'); } finally { saving.value = false; }
}
async function clearGhostKey(kind: 'admin' | 'content') { saving.value = true; clearFeedback(); try { await api.saveGhostConfig(kind === 'admin' ? { clear_admin_api_key: true } : { clear_content_api_key: true }); Object.assign(ghost, await api.getGhostConfig()); announce(`${kind === 'admin' ? 'Admin' : 'Content'} API Key 已清除`); } catch (e) { fail(e, '密钥清除失败'); } finally { saving.value = false; } }
async function testGhost() { saving.value = true; clearFeedback(); ghostTestResult.value = ''; try { const result = await api.testGhostConfig({ api_url: ghost.api_url.trim() || undefined, admin_api_key: ghostAdminKey.value || undefined, skip_ssl_verify: ghost.skip_ssl_verify }); ghostTestResult.value = `${result.message}${result.site_title ? ` · ${result.site_title}` : ''}`; } catch (e) { fail(e, 'Ghost 测试失败'); } finally { saving.value = false; } }
async function backup() { saving.value = true; clearFeedback(); try { backupResult.value = await api.backupDatabase(); announce(`备份已生成：${backupResult.value.backup_file_name}`); } catch (e) { fail(e, '数据库备份失败'); } finally { saving.value = false; } }
async function checkForUpdate() { saving.value = true; clearFeedback(); try { updateResult.value = await api.checkUpdate(true); announce(updateResult.value.has_update ? `发现新版本 ${updateResult.value.latest_version}` : '当前已是最新版本'); } catch (e) { fail(e, '更新检查失败'); } finally { saving.value = false; } }
async function setAutoUpdate() { if (!system.value) return; saving.value = true; clearFeedback(); try { const result = await api.updateSystemConfig({ auto_check_update: !system.value.auto_check_update }); system.value.auto_check_update = result.auto_check_update; announce('自动更新检查设置已保存'); } catch (e) { fail(e, '设置保存失败'); } finally { saving.value = false; } }

async function loadAll() {
  loading.value = true; clearFeedback();
  try {
    await world.loadTeams(); const requested = routeTeamId(); selectedTeamId.value = teams.value.some(team => team.id === requested) ? requested : (teams.value[0]?.id || 0); syncRoute(section.value, selectedTeamId.value);
    await Promise.all([loadTeamDetail(selectedTeamId.value), loadLlm(), loadFallback(), loadProviderCatalog(), loadSearch(), api.getRoleTemplates().then(v => roles.value = v), api.getSkills().then(v => skills.value = v), api.getTools().then(v => tools.value = v), api.getGhostConfig().then(v => Object.assign(ghost, v)), api.getSystemStatus().then(v => system.value = v)]);
  } catch (e) { fail(e, '设置资料载入失败'); } finally { loading.value = false; }
}
watch(() => route.params.section, value => { const next = isSection(value) ? value : 'teams'; section.value = next; if (!isSection(value) && value != null) syncRoute(next); });
watch(() => route.query.teamId, () => { const id = routeTeamId(); if (id && id !== selectedTeamId.value && teams.value.some(team => team.id === id)) { selectedTeamId.value = id; void loadTeamDetail(id); } else if (id && teams.value.length && !teams.value.some(team => team.id === id)) syncRoute(section.value, selectedTeamId.value); });
onMounted(loadAll);
</script>

<template>
  <div class="page settings-v2-page">
    <header class="page-heading settings-v2-heading"><div><span class="eyebrow">院务总录 · V2 管理台</span><h1>书院内务</h1><p>团队、模型、模板与系统维护均在 V2 完成；外观固定为武侠书院主题。</p></div><button class="settings-back" type="button" @click="leave">← 返回院落</button></header>
    <div class="settings-v2-layout">
      <aside class="settings-nav panel" aria-label="设置分类"><div class="settings-nav-seal">院</div><button v-for="item in sections" :key="item.id" :class="{ active: section === item.id }" type="button" @click="chooseSection(item.id)"><b>{{ item.label }}</b><small>{{ item.note }}</small></button></aside>
      <main class="settings-content panel" :aria-busy="loading"><header class="settings-content-head"><div><span class="eyebrow">{{ currentSection.note }}</span><h2>{{ currentSection.label }}</h2></div><span v-if="selectedTeamId" class="settings-team-badge">当前：{{ teams.find(team => team.id === selectedTeamId)?.name || teamForm.name }}</span></header>
        <p v-if="notice" class="settings-notice" role="status">{{ notice }}</p><p v-if="error" class="error-banner" role="alert">{{ error }}</p>

        <section v-if="section === 'teams'" class="settings-section">
          <div class="settings-subsection"><div class="subsection-head"><div><h3>院落名册</h3><p>选择院落后可完成资料、启停、导出与数据治理。</p></div><select aria-label="当前院落" :value="selectedTeamId" @change="chooseTeam(Number(($event.target as HTMLSelectElement).value))"><option v-if="!teams.length" value="0">尚无院落</option><option v-for="team in teams" :key="team.id" :value="team.id">{{ team.name }}{{ team.enabled ? '' : '（停用）' }}</option></select></div></div>
          <div class="settings-subsection create-strip"><h3>创建新院</h3><input v-model="newTeam.name" aria-label="新院名称" placeholder="院落名称" /><input v-model="newTeam.working_directory" aria-label="新院工作目录" placeholder="工作目录（可选）" /><button class="gold-button" type="button" :disabled="saving" @click="createTeam">创建院落</button></div>
          <template v-if="teamDetail"><div class="settings-form-grid"><label>院落名称<input v-model="teamForm.name" /></label><label>工作目录<input v-model="teamForm.working_directory" /></label><label class="wide">院训<input v-model="teamForm.slogan" /></label><label class="wide">协作规则<textarea v-model="teamForm.rules" rows="5" /></label></div><div class="settings-actions"><button class="gold-button" type="button" :disabled="saving" @click="saveTeam">保存基本资料</button><button class="quiet-button" type="button" :disabled="saving" @click="toggleTeam">{{ teamDetail.enabled ? '停用本院' : '启用本院' }}</button><button class="quiet-button" type="button" :disabled="saving" @click="exportCurrentTeam">导出预设</button><button class="quiet-button" type="button" :disabled="saving" @click="presetFile?.click()">导入预设</button><input ref="presetFile" class="visually-hidden" type="file" accept="application/json,.json" aria-label="导入团队预设" @change="importPreset" /><button class="danger-button" type="button" :disabled="saving" @click="clearTeam">清空运行数据</button><button class="danger-button" type="button" :disabled="saving" @click="removeTeam">删除院落</button></div><div class="settings-stat-grid"><div><b>{{ teamDetail.agents.length }}</b><small>位大师</small></div><div><b>{{ teamDetail.rooms.length }}</b><small>间研究室</small></div><div><b>{{ teamDetail.enabled ? '启' : '停' }}</b><small>当前状态</small></div></div><TeamConfigurationEditor :members="teamDetail.agents" :rooms="teamDetail.rooms" :roles="roles" :llm-services="llmServices" :team-llm="String(teamDetail.config.llm_service_name || '')" :dept-tree="deptTree" :busy="saving" @save-members="saveMembers" @clear-agent="clearAgent" @save-room="saveRoom" @delete-room="deleteRoom" @save-dept="saveDept" @save-team-llm="saveTeamLlm" /></template>
        </section>

        <section v-else-if="section === 'models'" class="settings-section">
          <div class="settings-subsection provider-preset"><div class="subsection-head"><div><h3>厂商预设速建</h3><p>选择厂商与模型，填入 API Key 即可一键生成模型服务。</p></div></div><div class="settings-form-grid"><label>厂商预设<select v-model="providerForm.provider_id" aria-label="厂商预设"><option value="">选择厂商…</option><option v-for="entry in providerCatalog" :key="entry.id" :value="entry.id">{{ providerLabel(entry) }}</option></select></label><label>模型<select v-model="providerForm.model" aria-label="预设模型" :disabled="!providerModels.length"><option v-if="!providerModels.length" value="">先选择厂商</option><option v-for="m in providerModels" :key="m" :value="m">{{ m }}</option></select></label><label>API Key<input v-model="providerForm.api_key" type="password" placeholder="输入该厂商密钥" /></label><label>自定义服务名（可选）<input v-model="providerForm.name" :placeholder="selectedProvider ? providerLabel(selectedProvider) : '留空自动命名'" /></label></div><p v-if="selectedProvider" class="inline-result">{{ selectedProvider.base_url }} · {{ selectedProvider.type }}<a v-if="selectedProvider.signup_url" :href="safeExternalUrl(selectedProvider.signup_url)" target="_blank" rel="noopener noreferrer" class="preset-signup">获取密钥 ↗</a></p><div class="settings-actions"><button class="gold-button" type="button" :disabled="saving || !providerForm.provider_id" @click="createFromProvider">按预设创建</button></div></div>

          <div class="subsection-head"><p class="section-intro">维护强类型模型连接，保存前可用临时配置测试。</p><button class="gold-button" type="button" @click="editLlm('new')">新增服务</button></div><div v-if="!llmServices.length" class="empty-state">尚未配置模型服务。</div><article v-for="(service, index) in llmServices" :key="`${service.name}-${index}`" class="service-card"><div><b>{{ service.name }} <em v-if="defaultLlm === service.name" class="default-mark">首选</em> <em v-if="service.is_builtin" class="readonly-mark">内置</em></b><small>{{ service.model || '未指定模型' }} · {{ service.type }} · {{ service.base_url }}</small></div><div class="settings-actions compact"><span :class="service.enable ? 'status-good' : 'status-muted'">{{ service.enable ? '已启用' : '已停用' }}</span><button class="text-button" @click="testSavedLlm(index)">测试</button><template v-if="!service.is_builtin"><button class="text-button" @click="makeDefaultLlm(index)">设首选</button><button class="text-button" @click="editLlm(index)">编辑</button><button class="text-button danger-text" @click="removeLlm(index)">删除</button></template><span v-else class="status-muted">只读</span></div></article>
          <div v-if="llmEditing !== null" class="settings-editor"><div class="subsection-head"><h3>{{ llmEditing === 'new' ? '新增模型服务' : '编辑模型服务' }}</h3><button class="text-button" @click="llmEditing = null">关闭</button></div><div class="settings-form-grid"><label>服务名称<input v-model="llmForm.name" :disabled="llmEditing !== 'new'" /></label><label>类型<select v-model="llmForm.type"><option value="openai-compatible">OpenAI Compatible</option><option value="anthropic">Anthropic</option><option value="google">Google</option><option value="deepseek">DeepSeek</option></select></label><label class="wide">Base URL<input v-model="llmForm.base_url" /></label><label>模型名<input v-model="llmForm.model" /></label><label>API Key<input v-model="llmForm.api_key" type="password" :placeholder="llmEditing === 'new' ? '输入密钥' : '留空则保留原密钥'" /></label><label>Temperature<input v-model="llmForm.temperature" type="number" step="0.1" /></label><label class="toggle"><input v-model="llmForm.enable" type="checkbox" />启用服务</label><label class="wide">额外请求头（JSON）<textarea v-model="llmForm.extra_headers" rows="4" /></label><label class="wide">供应商参数（JSON）<textarea v-model="llmForm.provider_params" rows="4" /></label></div><p v-if="llmTestResult" class="inline-result">{{ llmTestResult }}</p><div class="settings-actions"><button class="gold-button" :disabled="saving" @click="saveLlm">保存服务</button><button class="quiet-button" :disabled="saving" @click="testEditingLlm">测试当前填写</button></div></div>

          <div class="settings-subsection fallback-chain"><div class="subsection-head"><div><h3>首选与兜底链</h3><p>首选服务不可用时，按顺序自动切换到兜底服务。首选可在上方“设首选”调整。</p></div></div><p class="inline-result">首选：<b>{{ defaultLlm || '未设置' }}</b></p><ol v-if="fallbackServers.length" class="fallback-list"><li v-for="(name, index) in fallbackServers" :key="name"><span class="fallback-order">{{ index + 1 }}</span><b>{{ name }}</b><div class="settings-actions compact"><button class="text-button" :disabled="index === 0" @click="moveFallback(index, -1)">上移</button><button class="text-button" :disabled="index === fallbackServers.length - 1" @click="moveFallback(index, 1)">下移</button><button class="text-button danger-text" @click="removeFallback(name)">移除</button></div></li></ol><p v-else class="empty-state">尚未配置兜底服务。</p><div class="settings-actions"><select aria-label="添加兜底服务" :disabled="!availableFallback.length" @change="addFallback(($event.target as HTMLSelectElement).value); ($event.target as HTMLSelectElement).value=''"><option value="">{{ availableFallback.length ? '添加兜底服务…' : '无可用服务' }}</option><option v-for="svc in availableFallback" :key="svc.name" :value="svc.name">{{ svc.name }}</option></select><button class="gold-button" type="button" :disabled="saving" @click="saveFallback">保存兜底链</button></div></div>
        </section>

        <section v-else-if="section === 'search'" class="settings-section">
          <div class="settings-subsection"><div class="subsection-head"><div><h3>搜索全局设置</h3><p>控制联网搜索开关与抓取上限。未配置任何引擎时仍会回退到内置兜底。</p></div></div><div class="settings-form-grid"><label class="toggle"><input v-model="search.enabled" type="checkbox" />启用联网搜索</label><label>正文最大字符<input v-model.number="search.max_content_length" type="number" min="1000" step="1000" /></label><label>抓取字节上限<input v-model.number="search.max_fetch_bytes" type="number" min="65536" step="65536" /></label></div><div class="settings-actions"><button class="gold-button" type="button" :disabled="saving" @click="saveSearchSettings">保存全局设置</button></div></div>

          <div class="subsection-head"><p class="section-intro">按引擎维护多个 API Key，运行时轮询并在失败时自动切换。已保存的 key 仅显示掩码。</p><button class="gold-button" type="button" @click="editSearch('new')">新增引擎</button></div>
          <div v-if="!searchProviders.length" class="empty-state">尚未配置搜索引擎。</div>
          <article v-for="(provider, index) in searchProviders" :key="`${provider.provider}-${index}`" class="service-card"><div><b>{{ provider.provider }}</b><small>{{ provider.api_keys_count }} 个 key<template v-if="provider.api_keys.length"> · {{ provider.api_keys.join(' · ') }}</template></small></div><div class="settings-actions compact"><span :class="provider.enable ? 'status-good' : 'status-muted'">{{ provider.enable ? '已启用' : '已停用' }}</span><button class="text-button" @click="editSearch(index)">编辑</button><button v-if="provider.has_api_key" class="text-button danger-text" @click="clearSearchKeys(index)">清空密钥</button><button class="text-button danger-text" @click="removeSearchProvider(index)">删除</button></div></article>
          <div v-if="searchEditing !== null" class="settings-editor"><div class="subsection-head"><h3>{{ searchEditing === 'new' ? '新增搜索引擎' : '编辑搜索引擎' }}</h3><button class="text-button" @click="searchEditing = null">关闭</button></div><div class="settings-form-grid"><label>引擎<select v-model="searchForm.provider"><option v-for="name in searchPresets" :key="name" :value="name">{{ name }}</option></select></label><label class="toggle"><input v-model="searchForm.enable" type="checkbox" />启用引擎</label><label class="wide">API Keys（每行一个，或逗号分隔）<textarea v-model="searchForm.api_keys" rows="4" :placeholder="searchEditing === 'new' ? '输入一个或多个 key' : '留空则保留原有 key；bing 可无 key'" /></label></div><div class="settings-actions"><button class="gold-button" :disabled="saving" @click="saveSearchProvider">保存引擎</button></div></div>
        </section>


        <section v-else-if="section === 'roles'" class="settings-section"><div class="subsection-head"><p class="section-intro">角色模板定义大师的长期心法与行事准则。</p><button class="gold-button" @click="editRole(null)">新增模板</button></div><div class="card-grid"><article v-for="role in roles" :key="role.id" class="settings-list-card"><h3>{{ role.name }}</h3><p>{{ role.soul }}</p><div class="settings-actions compact"><button class="text-button" @click="editRole(role)">编辑</button><button class="text-button danger-text" @click="removeRole(role)">删除</button></div></article></div><div v-if="roleEditing !== null" class="settings-editor"><h3>{{ roleEditing === 'new' ? '新增角色模板' : '编辑角色模板' }}</h3><div class="settings-form-grid"><label>模板名称<input v-model="roleForm.name" /></label><label class="wide">角色心法<textarea v-model="roleForm.soul" rows="10" /></label></div><div class="settings-actions"><button class="gold-button" :disabled="saving" @click="saveRole">保存模板</button><button class="quiet-button" @click="roleEditing = null">取消</button></div></div></section>

        <section v-else-if="section === 'capabilities'" class="settings-section"><p class="section-intro">此处只读展示服务端已装载的 Skills 与 Tools；变更由部署环境负责。</p><div class="capability-columns"><div><h3>Skills · {{ skills.length }}</h3><article v-for="skill in skills" :key="skill.name" class="settings-list-card"><b>{{ skill.name }}</b><span class="readonly-mark">{{ skill.is_builtin ? '内置' : '扩展' }}</span><p>{{ skill.description || '暂无说明' }}</p><small v-if="skill.files.length">{{ skill.files.join(' · ') }}</small></article></div><div><h3>Tools · {{ tools.length }}</h3><article v-for="tool in tools" :key="`${tool.category}-${tool.name}`" class="settings-list-card"><b>{{ tool.name }}</b><small>{{ tool.category || '未分类' }}</small></article></div></div></section>

        <section v-else-if="section === 'ghost'" class="settings-section"><p class="section-intro">密钥只提交至服务端，已保存的密钥不会回显。</p><div class="settings-form-grid"><label class="wide toggle"><input v-model="ghost.enabled" type="checkbox" />启用 Ghost 最终结论刊行</label><label class="wide">Ghost 地址<input v-model="ghost.api_url" placeholder="https://blog.example.com" /></label><label>Admin API Key<input v-model="ghostAdminKey" type="password" :placeholder="ghost.has_admin_key ? '已配置；留空则保留' : '尚未配置'" /></label><label>Content API Key<input v-model="ghostContentKey" type="password" :placeholder="ghost.has_content_key ? '已配置；留空则保留' : '尚未配置'" /></label><label>发布状态<select v-model="ghost.publish_status"><option value="published">直接发布</option><option value="draft">保存为草稿</option></select></label><label class="toggle"><input v-model="ghost.auto_publish" type="checkbox" />结论完成后自动刊行</label><label class="toggle"><input v-model="ghost.skip_ssl_verify" type="checkbox" />跳过 SSL 证书验证（自签名证书时启用）</label></div><div class="key-row"><span>Admin Key：{{ ghost.has_admin_key ? '已录入' : '未录入' }}</span><button v-if="ghost.has_admin_key" class="text-button danger-text" @click="clearGhostKey('admin')">清除</button><span>Content Key：{{ ghost.has_content_key ? '已录入' : '未录入' }}</span><button v-if="ghost.has_content_key" class="text-button danger-text" @click="clearGhostKey('content')">清除</button></div><p v-if="ghostTestResult" class="inline-result">{{ ghostTestResult }}</p><div class="settings-actions"><button class="gold-button" :disabled="saving" @click="saveGhost">保存设置与新密钥</button><button class="quiet-button" :disabled="saving" @click="testGhost">测试连接</button></div></section>

        <section v-else class="settings-section maintenance"><div class="maintenance-grid"><article class="maintenance-card"><span>数据库护卷</span><h3>立即创建备份</h3><p>由服务端生成完整数据库备份，路径与文件名会在成功后显示。</p><button class="gold-button" :disabled="saving" @click="backup">创建数据库备份</button><small v-if="backupResult">{{ backupResult.backup_path }}</small></article><article class="maintenance-card"><span>版本巡检</span><h3>{{ system?.version ? `当前版本 ${system.version}` : '系统更新检查' }}</h3><p>强制向更新源检查最新版本；不会在此页面自动执行升级。</p><button class="gold-button" :disabled="saving" @click="checkForUpdate">检查更新</button><div v-if="updateResult" class="update-result"><b>{{ updateResult.has_update ? `可更新至 ${updateResult.latest_version}` : '已是最新版本' }}</b><p>{{ updateResult.release_notes }}</p><a v-if="updateResult.release_url" :href="safeExternalUrl(updateResult.release_url)" target="_blank" rel="noopener noreferrer">查看发行说明</a></div></article><article class="maintenance-card"><span>巡检偏好</span><h3>自动检查更新</h3><p>控制服务端是否按其既定周期检查新版本。</p><button class="quiet-button" :disabled="saving || !system" @click="setAutoUpdate">{{ system?.auto_check_update ? '已开启 · 点击关闭' : '已关闭 · 点击开启' }}</button></article><article class="maintenance-card"><span>外观说明</span><h3>V2 固定武侠主题</h3><p>当前 V2 以武侠书院为唯一视觉语言，不提供旧版主题或旧后台跳转。</p></article></div></section>
      </main>
    </div>
    <SettingsConfirmDialog :open="confirmation.open" :title="confirmation.title" :message="confirmation.message" :confirm-label="confirmation.label" :busy="saving" danger @cancel="confirmation.open = false" @confirm="confirmAction" />
  </div>
</template>
