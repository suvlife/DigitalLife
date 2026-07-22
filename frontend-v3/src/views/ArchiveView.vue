<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { world } from '../store/world';
import * as api from '../api/client';
import type { RunPhase, RunSnapshot } from '../domain/types';
import { useViewMode } from '../composables/useViewMode';
import GlassPanel from '../components/GlassPanel.vue';
import HoloCard from '../components/HoloCard.vue';
import GlowButton from '../components/GlowButton.vue';
import StatusDot from '../components/StatusDot.vue';
import MarkdownRender from '../components/MarkdownRender.vue';
import TimeAxis from '../components/TimeAxis.vue';

const { navigate } = useViewMode();

interface RunItem { id: string; teamId: number; title: string; question: string; phase: RunPhase; progress: number; publication: any; createdAt?: string; startedAt?: string; teamName?: string }

const runs = ref<RunItem[]>([]);
const loading = ref(false);
const teamFilter = ref<number | null>(null);

const detail = ref<api.DossierDetail | null>(null);
const timeline = ref<any[]>([]);
const runSnapshot = ref<RunSnapshot | null>(null);
const detailLoading = ref(false);
const activeTab = ref<'conclusion' | 'timeline' | 'rooms'>('conclusion');
const error = ref('');

const filteredRuns = computed(() => teamFilter.value === null ? runs.value : runs.value.filter(r => r.teamId === teamFilter.value));
const timelineAgents = computed(() => {
  const ids = [...new Set(timeline.value.map(m => Number(m.senderId)).filter(id => id > 0))];
  return ids.map(id => ({ id, teamId: detail.value?.run.teamId ?? 0, name: timeline.value.find(m => Number(m.senderId) === id)?.senderName || `大师 ${id}`, i18n: {}, status: 'idle' }));
});

async function loadRuns() {
  loading.value = true; error.value = '';
  try {
    const all: RunItem[] = [];
    for (const t of world.state.teams) {
      try { const rs = await api.getRuns(t.id); all.push(...rs.map(r => ({ ...r, teamName: t.name }))); } catch {}
    }
    runs.value = all.sort((a, b) => Number(b.id) - Number(a.id));
  } finally { loading.value = false; }
}

async function selectRun(run: RunItem) {
  detailLoading.value = true; detail.value = null; timeline.value = []; runSnapshot.value = null; error.value = ''; activeTab.value = 'conclusion';
  try {
    try { detail.value = await api.getDossier(run.id); } catch { detail.value = null; }
    try { timeline.value = await api.getRunTimeline(run.id); } catch { timeline.value = []; }
    try { runSnapshot.value = await api.getRun(run.id); } catch { runSnapshot.value = null; }
    // 若无卷宗正文但有 run，构造最小 detail 展示最终结论
    if (!detail.value) {
      const rd = await api.getRunFinalAnswer(run.id).catch(() => null);
      detail.value = { run, content: rd?.finalAnswer || '', reportPath: null, reportReady: false, hasConclusion: Boolean(rd?.finalAnswer) };
    }
  } finally { detailLoading.value = false; }
}

const retryingRoomId = ref<number | null>(null);
async function retryRoom(roomId: number) {
  if (!detail.value || retryingRoomId.value !== null) return;
  if (!window.confirm('重新讨论该房间？将保留上一轮发言供参考，大师们重新贡献一轮。')) return;
  retryingRoomId.value = roomId;
  try {
    await api.retryRoom(detail.value.run.id, roomId);
    // 重试后跳转到该房间的实时页面
    navigate({ mode: 'room', teamId: detail.value.run.teamId, roomId });
  } catch (e: any) {
    window.alert(e?.message || '重试失败');
  } finally { retryingRoomId.value = null; }
}

function downloadReport() {
  if (!detail.value?.reportPath || !detail.value.run.teamId) return;
  api.downloadFile(detail.value.reportPath, detail.value.run.teamId).catch(e => { error.value = e?.message || '下载失败'; });
}

function openBlog() {
  const url = detail.value?.run.publication?.url;
  if (url) window.open(url, '_blank', 'noopener');
}

function pubText(pub: any): string {
  const s = pub?.status;
  return s === 'published' ? '已发布' : s === 'publishing' ? '发布中' : s === 'failed' ? '发布失败' : '';
}
const phaseText: Record<string, string> = { queued: '排队', discussing: '讨论中', synthesizing: '汇总中', completed: '已完成', failed: '失败', partial_failed: '部分完成', publishing: '发布中' };

onMounted(loadRuns);
</script>

<template>
  <div class="archive-view">
    <GlassPanel padding="lg" glow="purple" class="archive-hero">
      <h1 class="page-title">历史卷宗</h1>
      <p class="page-desc">浏览所有协作空间的历史讨论记录与最终结论。每条卷宗包含完整的讨论过程、专家发言和综合研判报告。</p>
    </GlassPanel>

    <div class="archive-filter" v-if="world.state.teams.length > 1">
      <button class="filter-btn" :class="{ 'filter-active': teamFilter === null }" @click="teamFilter = null">全部</button>
      <button v-for="t in world.state.teams" :key="t.id" class="filter-btn" :class="{ 'filter-active': teamFilter === t.id }" @click="teamFilter = t.id">{{ t.name }}</button>
    </div>

    <div class="archive-body">
      <!-- 卷宗列表 -->
      <div class="archive-list">
        <HoloCard v-for="run in filteredRuns" :key="run.id" :status="run.phase === 'completed' ? 'completed' : run.phase === 'failed' ? 'failed' : 'waiting'"
          :clickable="true" :hover="true" :class="{ 'run-selected': detail?.run.id === run.id }" @click="selectRun(run)">
          <template #header>
            <div class="run-card-header">
              <StatusDot :status="run.phase === 'completed' ? 'completed' : run.phase === 'failed' ? 'failed' : 'waiting'" />
              <span class="run-title">{{ run.title || run.question || `Run #${run.id}` }}</span>
            </div>
          </template>
          <p class="run-info">{{ phaseText[run.phase] || run.phase }} · {{ run.teamName }} · {{ run.createdAt ? new Date(run.createdAt).toLocaleDateString('zh-CN') : '' }}</p>
        </HoloCard>
        <GlassPanel v-if="!filteredRuns.length && !loading" padding="lg"><p class="empty-text">暂无历史卷宗</p></GlassPanel>
        <GlassPanel v-if="loading" padding="lg"><p class="empty-text">加载中...</p></GlassPanel>
      </div>

      <!-- 卷宗详情 -->
      <div class="archive-detail">
        <GlassPanel v-if="detailLoading" padding="lg"><p class="empty-text">加载卷宗...</p></GlassPanel>
        <template v-else-if="detail">
          <GlassPanel padding="lg">
            <div class="detail-head">
              <div>
                <h2 class="detail-title">{{ detail.run.title || detail.run.question || `Run #${detail.run.id}` }}</h2>
                <p class="detail-meta">
                  {{ phaseText[detail.run.phase] || detail.run.phase }}
                  <span v-if="pubText(detail.run.publication)" class="pub-badge" :class="`pub-${detail.run.publication?.status}`">{{ pubText(detail.run.publication) }}</span>
                </p>
              </div>
              <div class="detail-actions">
                <GlowButton v-if="detail.run.publication?.url" variant="secondary" size="sm" @click="openBlog">查看博客</GlowButton>
                <GlowButton v-if="detail.reportPath && detail.reportReady" variant="secondary" size="sm" @click="downloadReport">下载报告</GlowButton>
              </div>
            </div>

            <div class="detail-tabs">
              <button class="tab-btn" :class="{ 'tab-active': activeTab === 'conclusion' }" @click="activeTab = 'conclusion'">综合结论</button>
              <button class="tab-btn" :class="{ 'tab-active': activeTab === 'timeline' }" @click="activeTab = 'timeline'">讨论过程 ({{ timeline.length }})</button>
              <button class="tab-btn" :class="{ 'tab-active': activeTab === 'rooms' }" @click="activeTab = 'rooms'">房间 ({{ Object.keys(runSnapshot?.roomRuns || {}).length }})</button>
            </div>

            <div v-if="activeTab === 'conclusion'" class="detail-conclusion">
              <MarkdownRender v-if="detail.content" :content="detail.content" />
              <p v-else class="no-answer">本卷宗暂无综合结论</p>
            </div>
            <div v-else class="detail-timeline">
              <TimeAxis v-if="timeline.length" :messages="timeline" :agents="timelineAgents" />
              <div class="timeline-msgs">
                <div v-for="(m, i) in timeline" :key="i" class="tl-item" :class="{ 'tl-user': m.senderId < 0 }">
                  <span class="tl-sender">{{ m.senderName || (m.senderId < 0 ? '你' : `大师 ${m.senderId}`) }}</span>
                  <MarkdownRender :content="m.content" class="tl-content" />
                </div>
                <p v-if="!timeline.length" class="no-answer">暂无讨论记录</p>
              </div>
            </div>
            <!-- 房间列表 + 重试 -->
            <div v-if="activeTab === 'rooms'" class="detail-rooms">
              <div v-for="rr in Object.values(runSnapshot?.roomRuns || {})" :key="rr.roomId" class="room-retry-row">
                <span class="rr-name">{{ rr.roomId === runSnapshot?.rootRoomId ? '主问策' : `研究室 ${rr.roomId}` }}</span>
                <span class="rr-status" :class="`rr-st-${rr.status}`">{{ rr.status }}</span>
                <span class="rr-progress">{{ rr.completedTasks }}/{{ rr.totalTasks }} 已贡献</span>
                <GlowButton v-if="['completed','failed','skipped'].includes(rr.status)" variant="secondary" size="sm"
                  :loading="retryingRoomId === rr.roomId" @click="retryRoom(rr.roomId)">重新讨论</GlowButton>
              </div>
              <p v-if="!Object.keys(runSnapshot?.roomRuns || {}).length" class="no-answer">暂无房间数据</p>
            </div>
          </GlassPanel>
        </template>
        <GlassPanel v-else padding="lg" class="detail-empty"><p class="empty-text">选择左侧卷宗查看详情</p></GlassPanel>
      </div>
    </div>
    <p v-if="error" class="msg-error">{{ error }}</p>
  </div>
</template>

<style scoped>
.archive-view { padding: var(--space-6); display: flex; flex-direction: column; gap: var(--space-5); }
.archive-hero { animation: fade-in-up var(--dur-normal) var(--ease-out); }
.page-title { font-family: var(--font-display); font-size: var(--fs-xl); font-weight: 600; color: var(--text-primary); margin: 0 0 var(--space-2); }
.page-desc { font-size: var(--fs-base); color: var(--text-secondary); line-height: var(--lh-normal); }
.archive-filter { display: flex; gap: var(--space-2); flex-wrap: wrap; }
.filter-btn { padding: 6px 14px; font-size: var(--fs-xs); color: var(--text-muted); background: rgba(255,255,255,0.02); border: 1px solid var(--glass-border); border-radius: var(--glass-radius-sm); cursor: pointer; }
.filter-active { color: var(--holo-purple); border-color: rgba(180,120,255,0.4); background: rgba(180,120,255,0.08); }
.archive-body { display: grid; grid-template-columns: 340px 1fr; gap: var(--space-5); align-items: start; }
@media (max-width: 900px) { .archive-body { grid-template-columns: 1fr; } }
.archive-list { display: flex; flex-direction: column; gap: var(--space-3); max-height: 72vh; overflow-y: auto; }
.run-selected { outline: 2px solid var(--holo-purple); outline-offset: 1px; }
.run-card-header { display: flex; align-items: center; gap: 6px; }
.run-title { font-size: var(--fs-sm); font-weight: 500; color: var(--text-primary); }
.run-info { font-size: var(--fs-xs); color: var(--text-muted); font-family: var(--font-mono); }
.archive-detail { max-height: 72vh; overflow-y: auto; }
.detail-head { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--space-4); margin-bottom: var(--space-4); flex-wrap: wrap; }
.detail-title { font-size: var(--fs-lg); font-weight: 600; color: var(--text-primary); margin: 0 0 var(--space-1); }
.detail-meta { font-size: var(--fs-xs); color: var(--text-muted); display: flex; align-items: center; gap: var(--space-2); }
.pub-badge { font-size: 10px; padding: 0 6px; border-radius: 4px; }
.pub-published { background: rgba(0,230,180,0.12); color: var(--holo-teal); }
.pub-failed { background: rgba(255,82,82,0.1); color: var(--holo-red); }
.pub-publishing { background: rgba(255,200,80,0.1); color: var(--holo-amber); }
.detail-actions { display: flex; gap: var(--space-2); }
.detail-tabs { display: flex; gap: var(--space-2); margin-bottom: var(--space-4); border-bottom: 1px solid var(--glass-border); }
.tab-btn { padding: 6px 14px; font-size: var(--fs-sm); color: var(--text-muted); background: none; border: none; border-bottom: 2px solid transparent; cursor: pointer; }
.tab-active { color: var(--holo-purple); border-bottom-color: var(--holo-purple); }
.detail-conclusion { min-height: 200px; }
.detail-timeline { display: flex; flex-direction: column; gap: var(--space-3); }
.timeline-msgs { display: flex; flex-direction: column; gap: var(--space-3); }
.tl-item { background: rgba(255,255,255,0.02); border: 1px solid var(--glass-border); border-radius: var(--glass-radius-sm); padding: var(--space-3); }
.tl-user { background: rgba(0,217,255,0.04); border-color: rgba(0,217,255,0.2); }
.tl-sender { font-size: var(--fs-xs); font-weight: 600; color: var(--text-secondary); display: block; margin-bottom: 4px; }
.tl-content { font-size: var(--fs-sm); }
.no-answer { color: var(--text-muted); font-style: italic; }
.detail-rooms { display: flex; flex-direction: column; gap: var(--space-2); }
.room-retry-row { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-2) var(--space-3); background: rgba(255,255,255,0.02); border: 1px solid var(--glass-border); border-radius: var(--glass-radius-sm); }
.rr-name { font-size: var(--fs-sm); font-weight: 500; color: var(--text-primary); min-width: 80px; }
.rr-status { font-size: var(--fs-xs); padding: 1px 8px; border-radius: 4px; }
.rr-st-completed { background: rgba(0,230,180,0.12); color: var(--holo-teal); }
.rr-st-failed { background: rgba(255,82,82,0.1); color: var(--holo-red); }
.rr-st-skipped { background: rgba(255,255,255,0.06); color: var(--text-muted); }
.rr-progress { font-size: var(--fs-xs); color: var(--text-muted); flex: 1; font-family: var(--font-mono); }
.empty-text { color: var(--text-muted); text-align: center; }
.detail-empty { display: flex; align-items: center; justify-content: center; min-height: 300px; }
.msg-error { font-size: var(--fs-sm); color: var(--holo-red); margin: 0; }
</style>
