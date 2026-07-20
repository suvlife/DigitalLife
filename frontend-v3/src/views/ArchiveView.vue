<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { world } from '../store/world';
import * as api from '../api/client';
import GlassPanel from '../components/GlassPanel.vue';
import HoloCard from '../components/HoloCard.vue';
import GlowButton from '../components/GlowButton.vue';
import StatusDot from '../components/StatusDot.vue';
import MarkdownRender from '../components/MarkdownRender.vue';
const runs = ref<any[]>([]); const selectedRun = ref<any>(null); const loading = ref(false);
const teamFilter = ref<number | null>(null);
async function loadRuns() {
  loading.value = true;
  try { const teams = world.state.teams; const all: any[] = [];
    for (const t of teams) { try { const runs = await api.getRuns(t.id); all.push(...runs); } catch {} }
    runs.value = all.sort((a, b) => b.id - a.id);
  } finally { loading.value = false; }
}
async function selectRun(run: any) { try { selectedRun.value = await api.getRunDetail(run.id); } catch {} }
onMounted(loadRuns);
</script>
<template>
  <div class="archive-view">
    <GlassPanel padding="lg" glow="purple" class="archive-hero">
      <h1 class="page-title">历史卷宗</h1>
      <p class="page-desc">浏览所有协作空间的历史讨论记录与最终结论。每条卷宗包含完整的讨论过程、专家发言和综合研判报告。</p>
    </GlassPanel>
    <div class="archive-body">
      <div class="archive-list">
        <HoloCard v-for="run in runs" :key="run.id" :status="run.status === 'COMPLETED' ? 'completed' : run.status === 'FAILED' ? 'failed' : 'waiting'" :clickable="true" :hover="true" @click="selectRun(run)">
          <template #header>
            <div class="run-card-header">
              <StatusDot :status="run.status === 'COMPLETED' ? 'completed' : run.status === 'FAILED' ? 'failed' : 'waiting'" />
              <span class="run-title">{{ run.title || run.query || `Run #${run.id}` }}</span>
            </div>
          </template>
          <p class="run-info">{{ run.status }} · {{ new Date(run.createdAt || run.startedAt).toLocaleDateString('zh-CN') }}</p>
        </HoloCard>
        <GlassPanel v-if="!runs.length && !loading" padding="lg"><p class="empty-text">暂无历史卷宗</p></GlassPanel>
      </div>
      <div class="archive-detail" v-if="selectedRun">
        <GlassPanel padding="lg">
          <h2 class="detail-title">{{ selectedRun.title || selectedRun.query }}</h2>
          <p class="detail-meta">{{ selectedRun.status }} · 创建于 {{ new Date(selectedRun.createdAt).toLocaleString('zh-CN') }}</p>
          <div class="detail-answer" v-if="selectedRun.finalAnswer">
            <h3 class="answer-title">最终结论</h3>
            <MarkdownRender :content="selectedRun.finalAnswer" />
          </div>
          <p v-else class="no-answer">本卷宗暂无最终结论</p>
        </GlassPanel>
      </div>
    </div>
  </div>
</template>
<style scoped>
.archive-view { padding: var(--space-6); display: flex; flex-direction: column; gap: var(--space-6); }
.archive-hero { animation: fade-in-up var(--dur-normal) var(--ease-out); }
.page-title { font-family: var(--font-display); font-size: var(--fs-xl); font-weight: 600; color: var(--text-primary); margin: 0 0 var(--space-2); }
.page-desc { font-size: var(--fs-base); color: var(--text-secondary); line-height: var(--lh-normal); }
.archive-body { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-5); }
.archive-list { display: flex; flex-direction: column; gap: var(--space-3); max-height: 70vh; overflow-y: auto; }
.run-card-header { display: flex; align-items: center; gap: 6px; }
.run-title { font-size: var(--fs-sm); font-weight: 500; color: var(--text-primary); }
.run-info { font-size: var(--fs-xs); color: var(--text-muted); font-family: var(--font-mono); }
.archive-detail { max-height: 70vh; overflow-y: auto; }
.detail-title { font-size: var(--fs-lg); font-weight: 600; color: var(--text-primary); margin: 0 0 var(--space-1); }
.detail-meta { font-size: var(--fs-xs); color: var(--text-muted); margin-bottom: var(--space-4); }
.answer-title { font-size: var(--fs-sm); font-weight: 600; color: var(--holo-purple); margin: 0 0 var(--space-2); text-transform: uppercase; letter-spacing: 0.1em; }
.no-answer { color: var(--text-muted); font-style: italic; }
.empty-text { color: var(--text-muted); text-align: center; }
</style>
