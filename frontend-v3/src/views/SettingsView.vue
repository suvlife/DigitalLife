<script setup lang="ts">
import { ref } from 'vue';
import GlassPanel from '../components/GlassPanel.vue';
import LlmServiceSection from '../components/settings/LlmServiceSection.vue';
import TeamManageSection from '../components/settings/TeamManageSection.vue';
import SearchSection from '../components/settings/SearchSection.vue';
import GhostSection from '../components/settings/GhostSection.vue';
import RoleTemplateSection from '../components/settings/RoleTemplateSection.vue';
import SystemSection from '../components/settings/SystemSection.vue';

const activeSection = ref('llm');
const sections = [
  { id: 'llm', name: '大模型服务', desc: '配置 LLM 推理服务：多 Key 轮询、首选与兜底链、本地服务' },
  { id: 'teams', name: '协作空间', desc: '启用或停用团队，管理成员、房间与部门结构' },
  { id: 'roles', name: '角色模板', desc: '定义可复用的角色系统提示词与人格风格' },
  { id: 'search', name: '搜索引擎', desc: '配置搜索 API Key，支持 Tavily / Brave / Bing 多 Key 轮询' },
  { id: 'ghost', name: '博客发布', desc: '配置 Ghost CMS，将讨论结论自动发布到博客' },
  { id: 'system', name: '系统维护', desc: '系统状态、数据库备份、更新检查与调度控制' },
];
</script>

<template>
  <div class="settings-view">
    <GlassPanel padding="lg" glow="cyan" class="settings-hero">
      <h1 class="page-title">系统配置</h1>
      <p class="page-desc">管理大模型服务、协作空间、角色模板、搜索引擎与博客发布。所有配置变更即时生效。</p>
    </GlassPanel>

    <div class="settings-nav">
      <button v-for="s in sections" :key="s.id" class="nav-btn" :class="{ 'nav-active': activeSection === s.id }" @click="activeSection = s.id">{{ s.name }}</button>
    </div>

    <div class="settings-content">
      <p class="section-desc">{{ sections.find(s => s.id === activeSection)?.desc }}</p>
      <LlmServiceSection v-if="activeSection === 'llm'" />
      <TeamManageSection v-else-if="activeSection === 'teams'" />
      <RoleTemplateSection v-else-if="activeSection === 'roles'" />
      <SearchSection v-else-if="activeSection === 'search'" />
      <GhostSection v-else-if="activeSection === 'ghost'" />
      <SystemSection v-else-if="activeSection === 'system'" />
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
.section-desc { font-size: var(--fs-sm); color: var(--text-secondary); margin: 0; }
</style>
