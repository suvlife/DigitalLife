<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import MarkdownContent from '../components/MarkdownContent.vue';
import { downloadFile, getDossier, getRun, retryRoom } from '../api/client';
import type { DossierDetail } from '../api/client';
import type { RunSnapshot, RoomRuntime } from '../domain/types';

const route = useRoute();
const router = useRouter();
const teamId = computed(() => Number(route.params.teamId));
const runId = computed(() => String(route.params.runId));
const dossier = ref<DossierDetail | null>(null);
const runSnapshot = ref<RunSnapshot | null>(null);
const loading = ref(true);
const error = ref('');
const downloadError = ref('');
const retryingRoomId = ref<number | null>(null);
let requestId = 0;

const phaseLabels: Record<string, string> = {
  queued: '排队中', planning: '筹划中', dispatching: '分派中', discussing: '会商中',
  synthesizing: '定稿中', publishing: '刊行中', completed: '已完成',
  partial_failed: '部分受阻', failed: '执行失败', cancelled: '已取消',
};
const publicationLabels: Record<string, string> = {
  idle: '未发布', pending: '待发布', publishing: '发布中', published: '已发布', failed: '发布失败',
};

const title = computed(() => {
  const run = dossier.value?.run;
  if (!run) return `问策卷宗 ${runId.value}`;
  return run.title.trim() || run.question.trim().split(/\r?\n/)[0]?.slice(0, 48) || `问策卷宗 ${run.id}`;
});

function formatTime(value?: string): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date);
}

async function load() {
  const current = ++requestId;
  loading.value = true;
  error.value = '';
  downloadError.value = '';
  try {
    const result = await getDossier(runId.value);
    if (current === requestId) dossier.value = result;
    try { const snap = await getRun(runId.value); if (current === requestId) runSnapshot.value = snap; } catch { runSnapshot.value = null; }
  } catch (reason) {
    if (current === requestId) {
      dossier.value = null;
      error.value = reason instanceof Error ? reason.message : '卷宗调取失败';
    }
  } finally {
    if (current === requestId) loading.value = false;
  }
}

async function download() {
  const path = dossier.value?.reportPath;
  if (!path) return;
  downloadError.value = '';
  try {
    await downloadFile(path, teamId.value);
  } catch (reason) {
    downloadError.value = reason instanceof Error ? reason.message : '卷宗下载失败';
  }
}

async function retryRoomAction(roomId: number) {
  if (!dossier.value || retryingRoomId.value !== null) return;
  if (!confirm('重新讨论该房间？将保留上一轮发言供参考，诸位先生重新贡献一轮。')) return;
  retryingRoomId.value = roomId;
  try {
    await retryRoom(dossier.value.run.id, roomId);
    router.push({ name: 'room', params: { teamId: teamId.value, roomId } });
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '重试失败';
  } finally { retryingRoomId.value = null; }
}

const roomList = computed<RoomRuntime[]>(() => Object.values(runSnapshot.value?.roomRuns || {}));

onMounted(load);
watch([teamId, runId], load);
</script>

<template>
  <div class="page dossier-page">
    <header class="page-heading">
      <div>
        <span class="eyebrow">问策卷宗 · {{ runId }}</span>
        <h1>{{ title }}</h1>
        <p v-if="dossier?.run?.question" class="run-question">{{ dossier.run.question }}</p>
      </div>
      <div class="page-actions">
        <RouterLink :to="{ name: 'run', params: { teamId, runId } }">观其演武</RouterLink>
        <RouterLink :to="{ name: 'team-archive', params: { teamId } }">返回卷宗阁</RouterLink>
      </div>
    </header>

    <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
    <div v-if="loading" class="loading-panel">正在调取卷宗正文……</div>

    <section v-else-if="dossier" class="panel">
      <div class="dossier-meta">
        <span class="run-status" :class="dossier.run.phase">{{ phaseLabels[dossier.run.phase] || dossier.run.phase }}</span>
        <span class="blog-status" :class="dossier.run.publication.status">博客 · {{ publicationLabels[dossier.run.publication.status] }}</span>
        <span v-if="dossier.run.startedAt">起 {{ formatTime(dossier.run.startedAt) }}</span>
        <span v-if="dossier.run.finishedAt">结 {{ formatTime(dossier.run.finishedAt) }}</span>
        <a v-if="dossier.reportReady && dossier.reportPath" class="dossier-download" href="#" @click.prevent="download">下载卷宗文档 ↓</a>
        <a v-if="dossier.run.publication.status === 'published' && dossier.run.publication.url" class="dossier-download" :href="dossier.run.publication.url" target="_blank" rel="noopener noreferrer">查看博客刊行 ↗</a>
      </div>
      <p v-if="downloadError" class="error-banner" role="alert">{{ downloadError }}</p>
      <MarkdownContent v-if="dossier.content" class="dossier-body" :content="dossier.content" :team-id="teamId" />
      <div v-else class="dossier-empty">
        <h2>本卷尚无结论</h2>
        <p>该问策尚未产出最终综合结论，待推演完成后卷宗正文将在此呈现。</p>
      </div>
      <!-- 房间列表 + 重新讨论 -->
      <div v-if="roomList.length" class="dossier-rooms">
        <h3>各室研讨</h3>
        <div v-for="rr in roomList" :key="rr.roomId" class="room-retry-row">
          <span class="rr-name">{{ rr.roomId === runSnapshot?.rootRoomId ? '主问策室' : `研究室 ${rr.roomId}` }}</span>
          <span class="rr-status" :class="`rr-st-${rr.status}`">{{ rr.status }}</span>
          <span class="rr-progress">{{ rr.completedTasks }}/{{ rr.totalTasks }} 已贡献</span>
          <button v-if="['completed','failed','skipped'].includes(rr.status)" class="gold-button small" :disabled="retryingRoomId === rr.roomId" @click="retryRoomAction(rr.roomId)">{{ retryingRoomId === rr.roomId ? '重试中…' : '重新讨论' }}</button>
        </div>
      </div>
    </section>
  </div>
</template>
<style scoped>
.dossier-rooms{margin-top:1.5rem;padding-top:1rem;border-top:1px solid rgba(222,191,125,.18)}
.dossier-rooms h3{font-size:1rem;color:var(--gold-light);margin:0 0 .8rem}
.room-retry-row{display:flex;align-items:center;gap:.8rem;padding:.5rem .8rem;margin-bottom:.4rem;background:rgba(255,255,255,.03);border:1px solid var(--glass-border);border-radius:8px}
.rr-name{font-size:.85rem;font-weight:600;color:var(--text);min-width:90px}
.rr-status{font-size:.7rem;padding:1px 8px;border-radius:4px}
.rr-st-completed{background:rgba(0,230,180,.12);color:var(--jade-light)}
.rr-st-failed{background:rgba(255,82,82,.1);color:#f0b5a9}
.rr-st-skipped{background:rgba(255,255,255,.06);color:var(--muted)}
.rr-progress{font-size:.72rem;color:var(--muted);flex:1;font-family:var(--font-mono,"KaiTi",serif)}
.gold-button.small{padding:4px 12px;font-size:.78rem}
</style>
