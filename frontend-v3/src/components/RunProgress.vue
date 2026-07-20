<script setup lang="ts">
import { computed } from 'vue';
import type { RunSnapshot } from '../domain/types';
import HoloCard from './HoloCard.vue';
import DataPulse from './DataPulse.vue';
import StatusDot from './StatusDot.vue';
import { safeExternalUrl } from '../utils/safeUrl';

const props = defineProps<{ run: RunSnapshot | null; roomId: number }>();
const phaseText: Record<string, string> = {
  queued: '排队等待', planning: '谋划任务', dispatching: '分派各院',
  discussing: '讨论进行中', synthesizing: '正在汇总结论', publishing: '刊行卷宗',
  completed: '已完成', partial_failed: '部分完成', failed: '执行失败', cancelled: '已取消',
};
const phaseColor: Record<string, string> = {
  queued: 'var(--holo-silver)', planning: 'var(--holo-cyan)', dispatching: 'var(--holo-cyan)',
  discussing: 'var(--holo-cyan)', synthesizing: 'var(--holo-purple)', publishing: 'var(--holo-amber)',
  completed: 'var(--holo-teal)', partial_failed: 'var(--holo-amber)', failed: 'var(--holo-red)', cancelled: 'var(--holo-silver)',
};
const roomStatusText: Record<string, string> = { queued: '排队', discussing: '讨论中', synthesizing: '汇总中', completed: '完成', failed: '失败', waiting: '等待', skipped: '跳过' };
const roomStatusColor: Record<string, string> = { queued: 'var(--holo-silver)', discussing: 'var(--holo-cyan)', synthesizing: 'var(--holo-purple)', completed: 'var(--holo-teal)', failed: 'var(--holo-red)', waiting: 'var(--text-faint)', skipped: 'var(--text-faint)' };
const roomList = computed(() => {
  if (!props.run?.roomRuns) return [];
  return Object.values(props.run.roomRuns).map(rr => ({ ...rr, isCurrent: rr.roomId === props.roomId }));
});
const blogUrl = computed(() => props.run?.publication?.url || null);
</script>
<template>
  <HoloCard v-if="run" :status="run.phase === 'completed' ? 'completed' : run.phase === 'discussing' || run.phase === 'synthesizing' ? 'discussing' : 'idle'" :hover="false">
    <template #header>
      <div class="rp-header">
        <span class="rp-title">当前运行</span>
        <span class="rp-phase" :style="{ color: phaseColor[run.phase] || 'var(--text-secondary)' }">{{ phaseText[run.phase] || run.phase }}</span>
      </div>
    </template>
    <div class="rp-body">
      <div class="rp-question" v-if="run.question">
        <span class="rp-q-label">问题</span>
        <p class="rp-q-text">{{ run.question }}</p>
      </div>
      <DataPulse :value="run.progress" label="整体进度" :color="run.phase === 'completed' ? 'teal' : 'cyan'" />
      <div class="rp-rooms" v-if="roomList.length">
        <span class="rp-rooms-title">房间进度</span>
        <div v-for="rr in roomList" :key="rr.roomId" class="rp-room" :class="{ 'rp-current': rr.isCurrent }">
          <span class="rp-room-name">{{ rr.isCurrent ? '▸ ' : '' }}{{ rr.roomId === run.rootRoomId ? '主问策' : `研究室 ${rr.roomId}` }}</span>
          <span class="rp-room-status" :style="{ color: roomStatusColor[rr.status] || 'var(--text-muted)' }">{{ roomStatusText[rr.status] || rr.status }}</span>
          <DataPulse :value="rr.progress" :color="rr.status === 'completed' ? 'teal' : 'cyan'" />
        </div>
      </div>
      <div class="rp-final" v-if="run.finalAnswer">
        <span class="rp-final-label">最终结论</span>
        <p class="rp-final-text">{{ run.finalAnswer.slice(0, 150) }}{{ run.finalAnswer.length > 150 ? '...' : '' }}</p>
        <a v-if="blogUrl" :href="safeExternalUrl(blogUrl)" target="_blank" rel="noopener noreferrer" class="rp-blog-link">查看博客文章 →</a>
      </div>
      <div class="rp-agents" v-if="run.activeAgentIds.length">
        <span class="rp-agents-label">{{ run.activeAgentIds.length }} 位大师正在推演</span>
      </div>
    </div>
  </HoloCard>
  <HoloCard v-else status="idle" :hover="false">
    <template #header><span class="rp-title">当前运行</span></template>
    <p class="rp-empty">暂无运行中的任务</p>
  </HoloCard>
</template>
<style scoped>
.rp-header { display: flex; justify-content: space-between; align-items: center; width: 100%; }
.rp-title { font-size: var(--fs-sm); font-weight: 600; color: var(--text-secondary); }
.rp-phase { font-size: var(--fs-sm); font-weight: 500; }
.rp-body { display: flex; flex-direction: column; gap: var(--space-3); }
.rp-question { display: flex; flex-direction: column; gap: 4px; }
.rp-q-label { font-size: var(--fs-xs); color: var(--text-muted); }
.rp-q-text { font-size: var(--fs-sm); color: var(--text-secondary); line-height: var(--lh-normal); margin: 0; }
.rp-rooms { display: flex; flex-direction: column; gap: var(--space-2); }
.rp-rooms-title { font-size: var(--fs-xs); color: var(--text-muted); }
.rp-room { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-2); border-radius: var(--glass-radius-sm); background: rgba(255,255,255,0.02); }
.rp-current { background: var(--glass-bg-active); border: 1px solid var(--glass-border); }
.rp-room-name { font-size: var(--fs-xs); color: var(--text-secondary); min-width: 80px; }
.rp-room-status { font-size: var(--fs-xs); min-width: 40px; }
.rp-final { display: flex; flex-direction: column; gap: var(--space-1); }
.rp-final-label { font-size: var(--fs-xs); color: var(--holo-purple); font-weight: 600; }
.rp-final-text { font-size: var(--fs-sm); color: var(--text-secondary); line-height: var(--lh-normal); margin: 0; }
.rp-blog-link { font-size: var(--fs-xs); color: var(--holo-cyan); text-decoration: none; }
.rp-blog-link:hover { color: var(--holo-teal); }
.rp-agents { display: flex; align-items: center; gap: var(--space-2); }
.rp-agents-label { font-size: var(--fs-xs); color: var(--holo-cyan); }
.rp-empty { font-size: var(--fs-sm); color: var(--text-muted); text-align: center; }
</style>
