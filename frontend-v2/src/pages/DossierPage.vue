<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import MarkdownContent from '../components/MarkdownContent.vue';
import { downloadFile, getDossier } from '../api/client';
import type { DossierDetail } from '../api/client';

const route = useRoute();
const teamId = computed(() => Number(route.params.teamId));
const runId = computed(() => String(route.params.runId));
const dossier = ref<DossierDetail | null>(null);
const loading = ref(true);
const error = ref('');
const downloadError = ref('');
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
    </section>
  </div>
</template>
