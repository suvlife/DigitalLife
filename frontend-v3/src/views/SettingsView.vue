<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { world } from '../store/world';
import * as api from '../api/client';
import GlassPanel from '../components/GlassPanel.vue';
import HoloCard from '../components/HoloCard.vue';
import GlowButton from '../components/GlowButton.vue';
import StatusDot from '../components/StatusDot.vue';
const llmServices = ref<any[]>([]); const systemStatus = ref<any>(null);
const ghostConfig = ref<any>(null); const searchConfig = ref<any>(null);
const activeSection = ref('llm');
const sections = [
  { id: 'llm', name: '大模型服务', desc: '配置和管理 LLM 推理服务，支持多 Key 轮询与兜底链' },
  { id: 'teams', name: '协作空间', desc: '启用或停用团队，管理团队成员与房间' },
  { id: 'search', name: '搜索引擎', desc: '配置搜索 API Key，支持 Tavily / Brave / Bing' },
  { id: 'ghost', name: '博客发布', desc: '配置 Ghost CMS 自动发布，将讨论结论发布到博客' },
  { id: 'system', name: '系统维护', desc: '系统状态、数据库备份、调度控制' },
];
async function loadAll() {
  try { systemStatus.value = await api.getSystemStatus(); } catch {}
  try { const d = await api.getLlmServiceConfig(); llmServices.value = d.llm_services || []; } catch {}
  try { ghostConfig.value = await api.getGhostConfig(); } catch {}
  try { searchConfig.value = await api.getSearchConfig(); } catch {}
}
async function toggleTeam(team: any) { try { await api.setTeamEnabled(team.id, !team.enabled); await world.loadTeams(); } catch {} }
onMounted(loadAll);
</script>
<template>
  <div class="settings-view">
    <GlassPanel padding="lg" glow="cyan" class="settings-hero">
      <h1 class="page-title">系统配置</h1>
      <p class="page-desc">管理大模型服务、协作空间、搜索引擎与博客发布。所有配置变更即时生效。</p>
    </GlassPanel>
    <div class="settings-nav">
      <button v-for="s in sections" :key="s.id" class="nav-btn" :class="{ 'nav-active': activeSection === s.id }" @click="activeSection = s.id">{{ s.name }}</button>
    </div>
    <div class="settings-content">
      <!-- LLM 服务 -->
      <template v-if="activeSection === 'llm'">
        <GlassPanel padding="md" v-for="s in sections" :key="s.id" v-show="s.id === 'llm'">
          <p class="section-desc">{{ sections[0].desc }}</p>
          <div class="service-list">
            <HoloCard v-for="(svc, i) in llmServices" :key="i" :status="svc.enable ? 'discussing' : 'idle'">
              <template #header>
                <div class="svc-header">
                  <StatusDot :status="svc.enable ? 'online' : 'waiting'" />
                  <span class="svc-name">{{ svc.name }}</span>
                  <span v-if="svc.is_builtin" class="svc-badge">内置</span>
                </div>
              </template>
              <p class="svc-info">{{ svc.model || '未指定模型' }} · {{ svc.type }}</p>
              <p class="svc-url">{{ svc.base_url }}</p>
            </HoloCard>
            <GlassPanel v-if="!llmServices.length" padding="md"><p class="empty-text">暂未配置大模型服务</p></GlassPanel>
          </div>
        </GlassPanel>
      </template>
      <!-- 团队管理 -->
      <template v-if="activeSection === 'teams'">
        <GlassPanel padding="md">
          <p class="section-desc">{{ sections[1].desc }}</p>
          <div class="team-list">
            <HoloCard v-for="team in world.state.teams" :key="team.id" :status="team.enabled ? 'discussing' : 'idle'">
              <template #header>
                <div class="svc-header">
                  <StatusDot :status="team.enabled ? 'online' : 'waiting'" />
                  <span class="svc-name">{{ team.name }}</span>
                </div>
              </template>
              <template #footer>
                <GlowButton variant="secondary" size="sm" @click="toggleTeam(team)">{{ team.enabled ? '停用' : '启用' }}</GlowButton>
              </template>
            </HoloCard>
          </div>
        </GlassPanel>
      </template>
      <!-- 搜索引擎 -->
      <template v-if="activeSection === 'search'">
        <GlassPanel padding="md">
          <p class="section-desc">{{ sections[2].desc }}</p>
          <div v-if="searchConfig" class="search-providers">
            <HoloCard v-for="p in (searchConfig.providers || [])" :key="p.provider" :status="p.enable ? 'discussing' : 'idle'">
              <template #header><div class="svc-header"><StatusDot :status="p.enable ? 'online' : 'waiting'" /><span class="svc-name">{{ p.provider }}</span></div></template>
              <p class="svc-info">{{ p.api_keys_count }} 个 API Key</p>
            </HoloCard>
            <GlassPanel v-if="!searchConfig?.providers?.length" padding="md"><p class="empty-text">暂未配置搜索引擎</p></GlassPanel>
          </div>
        </GlassPanel>
      </template>
      <!-- Ghost 博客 -->
      <template v-if="activeSection === 'ghost'">
        <GlassPanel padding="md">
          <p class="section-desc">{{ sections[3].desc }}</p>
          <HoloCard v-if="ghostConfig" :status="ghostConfig.enabled ? 'discussing' : 'idle'">
            <template #header><div class="svc-header"><StatusDot :status="ghostConfig.enabled ? 'online' : 'waiting'" /><span class="svc-name">Ghost CMS</span></div></template>
            <p class="svc-info">自动发布: {{ ghostConfig.auto_publish ? '已开启' : '已关闭' }} · 状态: {{ ghostConfig.publish_status }}</p>
            <p class="svc-url" v-if="ghostConfig.api_url">{{ ghostConfig.api_url }}</p>
          </HoloCard>
        </GlassPanel>
      </template>
      <!-- 系统维护 -->
      <template v-if="activeSection === 'system'">
        <GlassPanel padding="md">
          <p class="section-desc">{{ sections[4].desc }}</p>
          <div class="system-info" v-if="systemStatus">
            <div class="info-row"><span class="info-label">调度状态</span><span class="info-val" :class="{ 'val-ok': systemStatus.scheduleState === 'RUNNING' }">{{ systemStatus.scheduleState }}</span></div>
            <div class="info-row"><span class="info-label">模型配置</span><span class="info-val">{{ systemStatus.initialized ? '已就绪' : '未配置' }}</span></div>
            <div class="info-row"><span class="info-label">版本</span><span class="info-val">{{ systemStatus.version }}</span></div>
            <div class="info-row" v-if="systemStatus.notRunningReason"><span class="info-label">阻塞原因</span><span class="info-val val-warn">{{ systemStatus.notRunningReason }}</span></div>
          </div>
        </GlassPanel>
      </template>
    </div>
  </div>
</template>
<style scoped>
.settings-view { padding: var(--space-6); display: flex; flex-direction: column; gap: var(--space-5); }
.settings-hero { animation: fade-in-up var(--dur-normal) var(--ease-out); }
.page-title { font-family: var(--font-display); font-size: var(--fs-xl); font-weight: 600; color: var(--text-primary); margin: 0 0 var(--space-2); }
.page-desc { font-size: var(--fs-base); color: var(--text-secondary); line-height: var(--lh-normal); }
.settings-nav { display: flex; gap: var(--space-2); flex-wrap: wrap; }
.nav-btn { padding: 8px 16px; font-size: var(--fs-sm); font-family: var(--font-body); color: var(--text-muted); background: rgba(255,255,255,0.02); border: 1px solid var(--glass-border); border-radius: var(--glass-radius-sm); cursor: pointer; transition: all var(--dur-fast); }
.nav-btn:hover { color: var(--text-secondary); border-color: var(--glass-border-hover); }
.nav-active { color: var(--holo-cyan); border-color: var(--glass-border-active); background: var(--glass-bg-active); }
.settings-content { display: flex; flex-direction: column; gap: var(--space-4); }
.section-desc { font-size: var(--fs-sm); color: var(--text-secondary); margin-bottom: var(--space-3); }
.service-list, .team-list, .search-providers { display: flex; flex-direction: column; gap: var(--space-3); }
.svc-header { display: flex; align-items: center; gap: 6px; }
.svc-name { font-size: var(--fs-base); font-weight: 500; color: var(--text-primary); }
.svc-badge { font-size: 10px; padding: 1px 6px; border-radius: 4px; background: rgba(0, 217, 255, 0.1); color: var(--holo-cyan); border: 1px solid var(--glass-border); }
.svc-info { font-size: var(--fs-sm); color: var(--text-secondary); }
.svc-url { font-size: var(--fs-xs); color: var(--text-muted); font-family: var(--font-mono); word-break: break-all; }
.empty-text { color: var(--text-muted); text-align: center; }
.system-info { display: flex; flex-direction: column; gap: var(--space-2); }
.info-row { display: flex; justify-content: space-between; padding: var(--space-2) 0; border-bottom: 1px solid rgba(255,255,255,0.03); }
.info-label { font-size: var(--fs-sm); color: var(--text-muted); }
.info-val { font-size: var(--fs-sm); color: var(--text-secondary); font-family: var(--font-mono); }
.val-ok { color: var(--holo-teal); }
.val-warn { color: var(--holo-amber); }
</style>
