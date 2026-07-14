<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { getRuns, getTeams } from '../api/client';
import type { RunArchiveEntry, Team } from '../domain/types';

const route = useRoute();
const router = useRouter();
const teams = ref<Team[]>([]);
const runs = ref<RunArchiveEntry[]>([]);
const selectedTeamId = ref(0);
const statusFilter = ref('all');
const page = ref(1);
const pageSize = 10;
const loading = ref(true);
const error = ref('');
let requestId = 0;

const phaseLabels: Record<string, string> = {
  queued: '排队中', planning: '筹划中', dispatching: '分派中', discussing: '会商中',
  synthesizing: '定稿中', publishing: '刊行中', completed: '已完成',
  partial_failed: '部分受阻', failed: '执行失败', cancelled: '已取消',
};
const publicationLabels: Record<string, string> = {
  idle: '未发布', pending: '待发布', publishing: '发布中', published: '已发布', failed: '发布失败',
};
const statusOptions = computed(() => {
  const present = new Set(runs.value.map(run => run.phase));
  return Object.entries(phaseLabels).filter(([value]) => present.has(value as RunArchiveEntry['phase']));
});
const filteredRuns = computed(() => statusFilter.value === 'all' ? runs.value : runs.value.filter(run => run.phase === statusFilter.value));
const pageCount = computed(() => Math.max(1, Math.ceil(filteredRuns.value.length / pageSize)));
const pagedRuns = computed(() => filteredRuns.value.slice((page.value - 1) * pageSize, page.value * pageSize));
const selectedTeam = computed(() => teams.value.find(team => team.id === selectedTeamId.value));
const rangeText = computed(() => {
  if (!filteredRuns.value.length) return '共 0 卷';
  const start = (page.value - 1) * pageSize + 1;
  return `第 ${start}–${Math.min(start + pageSize - 1, filteredRuns.value.length)} 卷，共 ${filteredRuns.value.length} 卷`;
});

function formatTime(value?: string): string {
  if (!value) return '时间未记载';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date);
}
function titleOf(run: RunArchiveEntry): string {
  return run.title.trim() || run.question.trim().split(/\r?\n/)[0]?.slice(0, 48) || `问策卷宗 ${run.id}`;
}
function summaryOf(run: RunArchiveEntry): string {
  return run.question.trim() || '本卷未留问题摘要。';
}
function goToPage(next: number) { page.value = Math.min(pageCount.value, Math.max(1, next)); }
async function loadRuns(teamId: number) {
  const currentRequest = ++requestId;
  loading.value = true;
  error.value = '';
  try {
    const result = await getRuns(teamId, 200);
    if (currentRequest === requestId) runs.value = result;
  } catch (reason) {
    if (currentRequest === requestId) {
      runs.value = [];
      error.value = reason instanceof Error ? reason.message : '卷宗调取失败';
    }
  } finally {
    if (currentRequest === requestId) loading.value = false;
  }
}
async function selectTeam(teamId: number) {
  if (!teamId || teamId === selectedTeamId.value) return;
  selectedTeamId.value = teamId;
  statusFilter.value = 'all';
  page.value = 1;
  if (route.params.teamId) await router.replace({ name: 'team-archive', params: { teamId } });
  else await router.replace({ query: { ...route.query, team: String(teamId) } });
  await loadRuns(teamId);
}

watch(statusFilter, () => { page.value = 1; });
watch(pageCount, count => { if (page.value > count) page.value = count; });

onMounted(async () => {
  loading.value = true;
  try {
    teams.value = await getTeams();
    const routeTeamId = Number(route.params.teamId || route.query.team || 0);
    selectedTeamId.value = teams.value.some(team => team.id === routeTeamId) ? routeTeamId : (teams.value[0]?.id || 0);
    if (selectedTeamId.value) await loadRuns(selectedTeamId.value);
    else loading.value = false;
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '团队名录调取失败';
    loading.value = false;
  }
});
</script>

<template>
  <div class="page archive-page">
    <header class="page-heading">
      <div>
        <span class="eyebrow">问策卷宗</span>
        <h1>历次推演</h1>
        <p>按书院与状态查阅历史问策、执行进度及博客刊行结果。</p>
      </div>
      <RouterLink v-if="selectedTeamId" :to="{ name: 'team', params: { teamId: selectedTeamId } }">返回当前院落</RouterLink>
    </header>

    <section class="archive-toolbar panel" aria-label="卷宗筛选">
      <label>书院
        <select :value="selectedTeamId" aria-label="团队筛选" @change="selectTeam(Number(($event.target as HTMLSelectElement).value))">
          <option v-for="team in teams" :key="team.id" :value="team.id">{{ team.name }}</option>
        </select>
      </label>
      <label>状态
        <select v-model="statusFilter" aria-label="状态筛选">
          <option value="all">全部状态</option>
          <option v-for="([value, label]) in statusOptions" :key="value" :value="value">{{ label }}</option>
        </select>
      </label>
      <div class="archive-summary"><b>{{ selectedTeam?.name || '尚无书院' }}</b><span>{{ rangeText }}</span></div>
    </section>

    <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
    <div v-if="loading" class="loading-panel">正在调取历次卷宗……</div>
    <section v-else-if="pagedRuns.length" class="archive-list" aria-label="历史 Run 列表">
      <article v-for="run in pagedRuns" :key="run.id" class="archive-card panel">
        <div class="archive-card-head">
          <span class="run-status" :class="run.phase">{{ phaseLabels[run.phase] || run.phase }}</span>
          <time :datetime="run.startedAt || run.createdAt">{{ formatTime(run.startedAt || run.createdAt) }}</time>
        </div>
        <RouterLink class="archive-card-title" :to="{ name: 'dossier', params: { teamId: run.teamId, runId: run.id } }"><h2>{{ titleOf(run) }}</h2></RouterLink>
        <p class="run-question">{{ summaryOf(run) }}</p>
        <div class="run-progress" :aria-label="`进度 ${run.progress}%`">
          <span><i :style="{ width: `${run.progress}%` }"></i></span><b>{{ run.progress }}%</b>
        </div>
        <footer>
          <span class="blog-status" :class="run.publication.status">博客 · {{ publicationLabels[run.publication.status] }}</span>
          <span v-if="run.finishedAt">结卷 {{ formatTime(run.finishedAt) }}</span>
          <RouterLink class="open-run" :to="{ name: 'dossier', params: { teamId: run.teamId, runId: run.id } }">查看卷宗 →</RouterLink>
          <RouterLink class="open-run" :to="{ name: 'run', params: { teamId: run.teamId, runId: run.id } }">观其演武 →</RouterLink>
        </footer>
      </article>
    </section>
    <section v-else class="panel archive-empty">
      <span aria-hidden="true">卷</span><h2>暂无相符卷宗</h2><p>可切换书院或状态筛选查看其他历史问策。</p>
    </section>

    <nav v-if="!loading && filteredRuns.length > pageSize" class="archive-pagination" aria-label="卷宗分页">
      <button :disabled="page === 1" @click="goToPage(page - 1)">上一页</button>
      <span>第 {{ page }} / {{ pageCount }} 页</span>
      <button :disabled="page === pageCount" @click="goToPage(page + 1)">下一页</button>
    </nav>
    <p v-if="runs.length === 200" class="archive-limit-note">当前展示最近 200 卷；更早卷宗可按书院缩小范围后查阅。</p>
  </div>
</template>

<style scoped>
.archive-toolbar{display:flex;align-items:end;gap:1rem;padding:1rem 1.2rem;margin-bottom:1rem}.archive-toolbar label{display:flex;flex-direction:column;gap:.35rem;color:var(--gold-light);font-size:.8rem}.archive-toolbar select{min-width:180px;padding:.6rem .75rem;border:1px solid rgba(222,191,125,.3);border-radius:7px;background:#13241c;color:var(--text);font:inherit}.archive-summary{margin-left:auto;display:flex;flex-direction:column;align-items:flex-end;gap:.2rem}.archive-summary span,.archive-card time{color:var(--muted);font-size:.78rem}.archive-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:1rem}.archive-card{display:flex;flex-direction:column;min-height:245px;padding:1.2rem;color:var(--text);text-decoration:none;transition:transform .18s ease,border-color .18s ease}.archive-card:hover,.archive-card:focus-visible{transform:translateY(-3px);border-color:rgba(222,191,125,.55)}.archive-card-head,.archive-card footer,.run-progress{display:flex;align-items:center;justify-content:space-between;gap:.8rem}.run-status,.blog-status{display:inline-flex;padding:.24rem .5rem;border-radius:999px;background:rgba(103,128,103,.22);color:#c8d8c1;font-size:.72rem}.run-status.completed,.blog-status.published{background:rgba(70,132,91,.25);color:#bde1bd}.run-status.failed,.run-status.partial_failed,.blog-status.failed{background:rgba(154,63,54,.25);color:#f0b5a9}.run-status.discussing,.run-status.synthesizing,.run-status.publishing,.blog-status.pending,.blog-status.publishing{background:rgba(183,139,67,.2);color:var(--gold-light)}.archive-card h2{margin:.9rem 0 .45rem;font-size:1.25rem}.archive-card-title{color:inherit;text-decoration:none;display:block}.archive-card-title:hover h2,.archive-card-title:focus-visible h2{color:var(--gold-light)}.run-question{display:-webkit-box;min-height:3.5em;margin:0 0 1rem;overflow:hidden;color:#bdb29c;line-height:1.7;-webkit-line-clamp:2;-webkit-box-orient:vertical}.run-progress{margin-top:auto}.run-progress>span{height:6px;flex:1;overflow:hidden;border-radius:999px;background:rgba(255,255,255,.08)}.run-progress i{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,var(--jade),var(--gold))}.run-progress b{min-width:3em;text-align:right;color:var(--gold-light)}.archive-card footer{margin-top:1rem;padding-top:.8rem;border-top:1px solid rgba(222,191,125,.12);color:var(--muted);font-size:.75rem;flex-wrap:wrap}.open-run{margin-left:auto;color:var(--gold-light)}.archive-empty{text-align:center;padding:4rem 1rem;color:var(--muted)}.archive-empty>span{display:grid;place-items:center;width:64px;height:64px;margin:auto;border:1px solid var(--gold);border-radius:50%;color:var(--gold);font-size:1.6rem}.archive-empty h2{color:var(--text)}.archive-pagination{display:flex;align-items:center;justify-content:center;gap:1rem;margin-top:1.4rem}.archive-pagination button{padding:.55rem .9rem;border:1px solid rgba(222,191,125,.3);border-radius:7px;background:#1d3228;color:var(--text);cursor:pointer}.archive-pagination button:disabled{opacity:.4;cursor:not-allowed}.archive-limit-note{text-align:center;color:var(--muted);font-size:.78rem}@media(max-width:700px){.archive-toolbar{align-items:stretch;flex-direction:column}.archive-toolbar select{width:100%}.archive-summary{margin-left:0;align-items:flex-start}.archive-list{grid-template-columns:1fr}.page-heading{align-items:flex-start;flex-direction:column}}
</style>
