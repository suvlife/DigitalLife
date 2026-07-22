<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { world } from '../../store/world';
import * as api from '../../api/client';
import GlassPanel from '../GlassPanel.vue';
import HoloCard from '../HoloCard.vue';
import GlowButton from '../GlowButton.vue';
import StatusDot from '../StatusDot.vue';
import FormField from '../form/FormField.vue';
import TextInput from '../form/TextInput.vue';
import FormSelect from '../form/FormSelect.vue';
import FormModal from '../form/FormModal.vue';

const teams = computed(() => world.state.teams);
const detail = ref<api.TeamDetail | null>(null);
const members = ref<api.TeamMemberDetail[]>([]);
const activeTeamId = ref<number | null>(null);
const loading = ref(false);
const error = ref(''); const notice = ref('');

const memberEditorOpen = ref(false);
const editingMember = ref<api.TeamMemberDetail | null>(null);
const memberForm = ref({ model: '', driver: 'native', allowToolsText: '', allowSkillsText: '' });
const savingMember = ref(false);

const roomEditorOpen = ref(false);
const roomForm = ref({ id: null as number | null, name: '', initial_topic: '', max_rounds: null as number | null });
const savingRoom = ref(false);
const deleteRoomTarget = ref<api.TeamRoomDetail | null>(null);
const deletingRoom = ref(false);

const driverOptions = [
  { value: 'native', label: 'Native (Function Calling)' },
  { value: 'tsp', label: 'TSP' },
  { value: 'claude_sdk', label: 'Claude SDK' },
];

async function selectTeam(teamId: number) {
  activeTeamId.value = teamId; loading.value = true; error.value = ''; detail.value = null;
  try {
    detail.value = await api.getTeamDetail(teamId);
    try { members.value = await api.getTeamMembers(teamId); } catch { members.value = []; }
    // 同步当前团队的 LLM 服务配置
    teamLlmService.value = String((detail.value?.config as any)?.llm_service_name || '');
  } catch (e: any) { error.value = e?.message || '加载团队详情失败'; }
  finally { loading.value = false; }
}

async function toggleTeam(team: any) {
  error.value = ''; notice.value = '';
  try { await api.setTeamEnabled(team.id, !team.enabled); notice.value = `已${team.enabled ? '停用' : '启用'} ${team.name}`; await world.loadTeams(); if (activeTeamId.value === team.id) selectTeam(team.id); }
  catch (e: any) { error.value = e?.message || '操作失败'; }
}

async function exportPreset(team: any) {
  error.value = ''; notice.value = '';
  try {
    const preset = await api.exportTeam(team.id);
    const blob = new Blob([JSON.stringify(preset, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob); const a = document.createElement('a');
    a.href = url; a.download = `${team.name}-preset.json`; a.click(); URL.revokeObjectURL(url);
    notice.value = '预设已导出';
  } catch (e: any) { error.value = e?.message || '导出失败'; }
}

function openMemberEdit(m: api.TeamMemberDetail) {
  editingMember.value = m;
  memberForm.value = {
    model: m.model || '', driver: (m.driver || 'native'),
    allowToolsText: (m.allow_tools || []).join(', '), allowSkillsText: (m.allow_skills || []).join(', '),
  };
  memberEditorOpen.value = true;
}

async function saveMember() {
  if (!editingMember.value || activeTeamId.value === null) return;
  savingMember.value = true; error.value = ''; notice.value = '';
  try {
    const payload: api.TeamMemberSaveItem[] = members.value.map(m => ({
      id: m.id, name: m.name, role_template_id: m.role_template_id,
      model: m.id === editingMember.value!.id ? memberForm.value.model : (m.model || ''),
      driver: m.id === editingMember.value!.id ? memberForm.value.driver : (m.driver || 'native'),
      allow_tools: m.id === editingMember.value!.id ? (memberForm.value.allowToolsText ? memberForm.value.allowToolsText.split(',').map(s => s.trim()).filter(Boolean) : null) : m.allow_tools,
      allow_skills: m.id === editingMember.value!.id ? (memberForm.value.allowSkillsText ? memberForm.value.allowSkillsText.split(',').map(s => s.trim()).filter(Boolean) : null) : m.allow_skills,
    }));
    await api.saveTeamMembers(activeTeamId.value, payload);
    notice.value = '成员配置已保存';
    memberEditorOpen.value = false;
    await selectTeam(activeTeamId.value);
  } catch (e: any) { error.value = e?.message || '保存失败'; }
  finally { savingMember.value = false; }
}

function openRoomCreate() { roomForm.value = { id: null, name: '', initial_topic: '', max_rounds: null }; roomEditorOpen.value = true; }
function openRoomEdit(r: api.TeamRoomDetail) { roomForm.value = { id: r.id, name: r.name, initial_topic: r.initial_topic || '', max_rounds: r.max_rounds }; roomEditorOpen.value = true; }

async function saveRoom() {
  if (activeTeamId.value === null || !roomForm.value.name.trim()) { error.value = '房间名称必填'; return; }
  savingRoom.value = true; error.value = ''; notice.value = '';
  try {
    if (roomForm.value.id === null) {
      await api.createTeamRoom(activeTeamId.value, { name: roomForm.value.name.trim(), agent_ids: [], initial_topic: roomForm.value.initial_topic || null, max_rounds: roomForm.value.max_rounds });
      notice.value = '房间已创建';
    } else {
      await api.updateTeamRoom(activeTeamId.value, roomForm.value.id, { name: roomForm.value.name.trim(), initial_topic: roomForm.value.initial_topic || null, max_rounds: roomForm.value.max_rounds });
      notice.value = '房间已保存';
    }
    roomEditorOpen.value = false;
    await selectTeam(activeTeamId.value);
  } catch (e: any) { error.value = e?.message || '保存失败'; }
  finally { savingRoom.value = false; }
}

async function confirmDeleteRoom() {
  if (!deleteRoomTarget.value || activeTeamId.value === null) return;
  deletingRoom.value = true; error.value = '';
  try { await api.deleteTeamRoom(activeTeamId.value, deleteRoomTarget.value.id); notice.value = '房间已删除'; deleteRoomTarget.value = null; await selectTeam(activeTeamId.value); }
  catch (e: any) { error.value = e?.message || '删除失败'; }
  finally { deletingRoom.value = false; }
}

// 团队专属 LLM 服务（各团队独立服务，避免共享并发池争抢）
const llmServices = ref<api.LlmServiceInfo[]>([]);
const teamLlmService = ref<string>('');
const savingLlm = ref(false);
async function loadLlmServices() {
  try { llmServices.value = await api.getLlmServices(); } catch { llmServices.value = []; }
}
const llmOptions = computed(() => [
  { value: '', label: '使用全局默认' },
  ...llmServices.value.filter(s => s.enable).map(s => ({ value: s.name, label: `${s.name}${s.is_builtin ? '（内置）' : ''}` })),
]);
async function saveTeamLlmService() {
  if (activeTeamId.value === null || !detail.value) return;
  savingLlm.value = true; error.value = ''; notice.value = '';
  try {
    const newConfig = { ...detail.value.config, llm_service_name: teamLlmService.value || undefined };
    await api.modifyTeam(activeTeamId.value, { config: newConfig });
    notice.value = teamLlmService.value ? `已为该团队指定专属服务：${teamLlmService.value}` : '已恢复使用全局默认服务';
    await selectTeam(activeTeamId.value);
  } catch (e: any) { error.value = e?.message || '保存失败'; }
  finally { savingLlm.value = false; }
}

onMounted(() => { if (teams.value.length && activeTeamId.value === null) selectTeam(teams.value[0].id); loadLlmServices(); });
</script>

<template>
  <div class="team-manage">
    <div class="team-picker">
      <HoloCard v-for="team in teams" :key="team.id" :status="team.enabled ? 'discussing' : 'idle'" :clickable="true" :hover="true"
        :class="{ 'team-selected': activeTeamId === team.id }" @click="selectTeam(team.id)">
        <template #header>
          <div class="svc-header"><StatusDot :status="team.enabled ? 'online' : 'waiting'" /><span class="svc-name">{{ team.name }}</span></div>
        </template>
        <template #footer>
          <div class="svc-actions">
            <GlowButton variant="secondary" size="sm" @click.stop="toggleTeam(team)">{{ team.enabled ? '停用' : '启用' }}</GlowButton>
            <GlowButton variant="secondary" size="sm" @click.stop="exportPreset(team)">导出</GlowButton>
          </div>
        </template>
      </HoloCard>
    </div>
    <p v-if="error" class="msg-error">{{ error }}</p>
    <p v-if="notice" class="msg-ok">{{ notice }}</p>

    <template v-if="detail">
      <!-- 团队专属 LLM 服务（各团队独立服务，多团队并发时避免共享池争抢） -->
      <GlassPanel padding="md">
        <h3 class="panel-title">专属 LLM 服务</h3>
        <p class="panel-hint">为该团队指定独立的 LLM 服务，多团队并发时各自走独立并发池，互不争抢。留空则使用全局默认服务。</p>
        <div class="llm-service-row">
          <FormSelect v-model="teamLlmService" :options="llmOptions" />
          <GlowButton variant="primary" size="sm" :loading="savingLlm" @click="saveTeamLlmService">保存</GlowButton>
        </div>
      </GlassPanel>

      <!-- 成员管理 -->
      <GlassPanel padding="md">
        <h3 class="panel-title">团队成员（{{ members.length }}）</h3>
        <div class="member-list">
          <div v-for="m in members" :key="m.id" class="member-row">
            <span class="member-name">{{ m.name }}</span>
            <span class="member-meta">{{ m.model || '默认模型' }} · {{ m.driver || 'native' }}</span>
            <span v-if="m.allow_tools?.length" class="member-badge">{{ m.allow_tools.length }} 工具</span>
            <span v-if="m.allow_skills?.length" class="member-badge">{{ m.allow_skills.length }} 技能</span>
            <GlowButton variant="secondary" size="sm" @click="openMemberEdit(m)">编辑</GlowButton>
          </div>
          <p v-if="!members.length" class="empty-text">该团队暂无成员</p>
        </div>
      </GlassPanel>

      <!-- 房间管理 -->
      <GlassPanel padding="md">
        <div class="panel-header">
          <h3 class="panel-title">研究室（{{ detail.rooms.length }}）</h3>
          <GlowButton variant="primary" size="sm" @click="openRoomCreate">+ 新建房间</GlowButton>
        </div>
        <div class="room-list">
          <div v-for="r in detail.rooms" :key="r.id" class="room-row">
            <span class="room-name">{{ r.name }}</span>
            <span class="room-meta">{{ r.type }} · {{ r.agents.length }} 成员 · {{ r.max_rounds ?? '默认' }} 轮</span>
            <GlowButton variant="secondary" size="sm" @click="openRoomEdit(r)">编辑</GlowButton>
            <GlowButton variant="danger" size="sm" @click="deleteRoomTarget = r">删除</GlowButton>
          </div>
          <p v-if="!detail.rooms.length" class="empty-text">该团队暂无房间</p>
        </div>
      </GlassPanel>
    </template>
    <GlassPanel v-else-if="loading" padding="lg"><p class="empty-text">加载中...</p></GlassPanel>

    <!-- 成员编辑 -->
    <FormModal :open="memberEditorOpen" :title="`编辑成员：${editingMember?.name || ''}`" confirm-text="保存"
      :loading="savingMember" @close="memberEditorOpen = false" @confirm="saveMember">
      <FormField label="模型" hint="留空使用团队/全局默认模型">
        <TextInput v-model="memberForm.model" placeholder="如 qwen-plus" mono />
      </FormField>
      <FormField label="驱动">
        <FormSelect v-model="memberForm.driver" :options="driverOptions" />
      </FormField>
      <FormField label="允许的工具（逗号分隔，留空=全部允许）">
        <TextInput v-model="memberForm.allowToolsText" placeholder="如 web_search, web_fetch" />
      </FormField>
      <FormField label="允许的技能（逗号分隔，留空=全部允许）">
        <TextInput v-model="memberForm.allowSkillsText" placeholder="如 stock-analysis" />
      </FormField>
    </FormModal>

    <!-- 房间编辑/新建 -->
    <FormModal :open="roomEditorOpen" :title="roomForm.id === null ? '新建房间' : '编辑房间'" confirm-text="保存"
      :loading="savingRoom" @close="roomEditorOpen = false" @confirm="saveRoom">
      <FormField label="房间名称" required>
        <TextInput v-model="roomForm.name" placeholder="如：投研讨论室" />
      </FormField>
      <FormField label="初始议题" hint="进入房间时的默认讨论主题">
        <TextInput v-model="roomForm.initial_topic" placeholder="可选" />
      </FormField>
      <FormField label="最大轮次" hint="留空使用全局默认">
        <TextInput :model-value="roomForm.max_rounds ?? ''" type="number" @update:model-value="(v) => roomForm.max_rounds = v === '' ? null : Number(v)" />
      </FormField>
    </FormModal>

    <!-- 删除房间确认 -->
    <FormModal :open="deleteRoomTarget !== null" title="删除房间" confirm-text="删除" confirm-danger
      :loading="deletingRoom" @close="deleteRoomTarget = null" @confirm="confirmDeleteRoom">
      <p class="confirm-text">确定删除房间 <strong>{{ deleteRoomTarget?.name }}</strong> 吗？</p>
    </FormModal>
  </div>
</template>

<style scoped>
.team-manage { display: flex; flex-direction: column; gap: var(--space-4); }
.team-picker { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: var(--space-3); }
.team-selected { outline: 2px solid var(--holo-cyan); outline-offset: 1px; border-radius: var(--glass-radius); }
.svc-header { display: flex; align-items: center; gap: 8px; }
.svc-name { font-size: var(--fs-sm); font-weight: 500; color: var(--text-primary); }
.svc-actions { display: flex; gap: var(--space-2); }
.msg-error { font-size: var(--fs-sm); color: var(--holo-red); margin: 0; }
.msg-ok { font-size: var(--fs-sm); color: var(--holo-teal); margin: 0; }
.panel-title { font-size: var(--fs-sm); font-weight: 600; color: var(--text-primary); margin: 0 0 var(--space-3); }
.panel-hint { font-size: var(--fs-xs); color: var(--text-muted); margin: 0 0 var(--space-3); line-height: var(--lh-normal); }
.llm-service-row { display: flex; gap: var(--space-3); align-items: center; }
.llm-service-row :deep(.form-select) { flex: 1; }
.panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-3); }
.panel-header .panel-title { margin: 0; }
.member-list, .room-list { display: flex; flex-direction: column; gap: var(--space-2); }
.member-row, .room-row { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-2) 0; border-bottom: 1px solid rgba(255,255,255,0.03); flex-wrap: wrap; }
.member-name, .room-name { font-size: var(--fs-sm); font-weight: 500; color: var(--text-primary); min-width: 100px; }
.member-meta, .room-meta { font-size: var(--fs-xs); color: var(--text-muted); flex: 1; font-family: var(--font-mono); }
.member-badge { font-size: 10px; padding: 1px 6px; border-radius: 4px; background: rgba(0,217,255,0.1); color: var(--holo-cyan); border: 1px solid var(--glass-border); }
.empty-text { color: var(--text-muted); text-align: center; padding: var(--space-3) 0; }
.confirm-text { font-size: var(--fs-sm); color: var(--text-secondary); }
</style>
