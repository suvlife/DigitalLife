<script setup lang="ts">
import { computed } from 'vue';
import AgentOrb from './AgentOrb.vue';
import DataPulse from './DataPulse.vue';
import StatusDot from './StatusDot.vue';
import GlassPanel from './GlassPanel.vue';
import { npcStatusFromActivity, activityLabel } from '../domain/status';
import type { Agent, Activity, Message, NpcStatus } from '../domain/types';

const props = defineProps<{
  members: readonly Agent[];
  messages: readonly Message[];
  activities: readonly Activity[];
  currentAgentId: number | null;
  roomStatus: string;
}>();

/** 已发言的大师 ID 集合（senderId > 0 表示真实大师发言，排除系统消息） */
const spokenIds = computed<Set<number>>(() => {
  const ids = new Set<number>();
  for (const m of props.messages) {
    if (m.senderId > 0) ids.add(m.senderId);
  }
  return ids;
});

const hasSpoken = (id: number) => spokenIds.value.has(id);

const spokenCount = computed(
  () => props.members.filter((m) => spokenIds.value.has(m.id)).length,
);
const totalCount = computed(() => props.members.length);

const isFinished = computed(
  () => props.roomStatus === 'completed' || props.roomStatus === 'failed' || props.roomStatus === 'skipped',
);
const allSpoken = computed(
  () => totalCount.value > 0 && spokenCount.value >= totalCount.value,
);

const pulseLabel = computed(() => {
  if (isFinished.value) return '本室讨论已结束';
  if (allSpoken.value) return '全部大师已发言 · 已完成';
  return '大师发言进度';
});
const pulseColor = computed<'cyan' | 'teal'>(() =>
  isFinished.value || allSpoken.value ? 'teal' : 'cyan',
);

const statusDotState = computed(() => {
  if (props.roomStatus === 'completed') return 'completed' as const;
  if (props.roomStatus === 'failed') return 'failed' as const;
  if (props.roomStatus === 'discussing') return 'active' as const;
  return 'waiting' as const;
});
const statusLabel = computed(() => {
  if (isFinished.value) return '本室讨论已结束';
  if (allSpoken.value) return '已完成';
  if (props.roomStatus === 'discussing') return '讨论中';
  return '等待中';
});

/** 每位大师的最新活动（按 startedAt 降序取首条，限本室或本人） */
function latestActivityFor(agentId: number): Activity | null {
  const acts = props.activities
    .filter((a) => a.agentId === agentId)
    .sort((x, y) => Date.parse(y.startedAt || '') - Date.parse(x.startedAt || ''));
  return acts[0] ?? null;
}

/** 每位大师的实时状态：从最新活动派生（推演/查找/发言/重试...），无活动则按发言记录 */
function orbStatusFor(agent: Agent): NpcStatus {
  if (isFinished.value && hasSpoken(agent.id)) return 'completed';
  const latest = latestActivityFor(agent.id);
  if (latest) {
    const s = npcStatusFromActivity(latest);
    // 已发言且当前无活跃动作 -> completed
    if (s === 'idle' && hasSpoken(agent.id) && agent.id !== props.currentAgentId) return 'completed';
    return s;
  }
  if (agent.id === props.currentAgentId && !isFinished.value) return 'speaking';
  if (hasSpoken(agent.id)) return 'completed';
  return 'idle';
}

const orbActive = (agent: Agent) =>
  agent.id === props.currentAgentId && !isFinished.value;

/** 状态标签：当前活跃动作的中文描述 */
function statusTextFor(agent: Agent): string {
  const s = orbStatusFor(agent);
  if (s === 'idle') return '';
  if (s === 'completed') return '已发言';
  const latest = latestActivityFor(agent.id);
  if (latest) {
    const name = agent.name;
    return activityLabel(s, name);
  }
  return activityLabel(s, agent.name);
}

const panelGlow = computed<'cyan' | 'teal' | 'none'>(() => {
  if (isFinished.value || allSpoken.value) return 'teal';
  if (props.roomStatus === 'discussing') return 'cyan';
  return 'none';
});

/** 图例：各状态符号说明 */
const legend = computed(() => {
  const items = [
    { icon: '💭', label: '推演', color: 'var(--holo-cyan)' },
    { icon: '🔍', label: '查找', color: 'var(--holo-amber)' },
    { icon: '▶', label: '发言', color: 'var(--holo-teal)' },
    { icon: '✓', label: '已发言', color: 'var(--holo-teal)' },
    { icon: '↻', label: '重试', color: 'var(--holo-amber)' },
    { icon: '✗', label: '受阻', color: 'var(--holo-red)' },
  ];
  return items;
});
</script>

<template>
  <GlassPanel :glow="panelGlow" padding="md" class="speaker-progress">
    <div class="sp-header">
      <StatusDot :status="statusDotState" :label="statusLabel" />
      <span class="sp-count">{{ spokenCount }}/{{ totalCount }} 大师已发言</span>
    </div>

    <DataPulse
      :value="spokenCount"
      :max="Math.max(totalCount, 1)"
      :label="pulseLabel"
      :color="pulseColor"
    />

    <div class="sp-finished" v-if="isFinished || allSpoken">
      <span class="sp-finished-text">
        {{ isFinished ? '本室讨论已结束' : '全部大师已发言' }}
      </span>
    </div>

    <!-- 大师头像行（实时状态符号 + 标签） -->
    <div class="sp-orbs">
      <div
        v-for="agent in members"
        :key="agent.id"
        class="sp-orb-item"
        :class="{
          'orb-spoken': hasSpoken(agent.id),
          'orb-current': orbActive(agent),
        }"
      >
        <AgentOrb
          :name="agent.name"
          :status="orbStatusFor(agent)"
          :active="orbActive(agent)"
          :status-label="statusTextFor(agent)"
          size="md"
        />
      </div>
    </div>

    <!-- 状态图例 -->
    <div class="sp-legend">
      <span v-for="item in legend" :key="item.label" class="legend-item">
        <span class="legend-icon" :style="{ color: item.color }">{{ item.icon }}</span>
        <span class="legend-text">{{ item.label }}</span>
      </span>
    </div>
  </GlassPanel>
</template>

<style scoped>
.speaker-progress { display: flex; flex-direction: column; gap: var(--space-3); }
.sp-header { display: flex; justify-content: space-between; align-items: center; }
.sp-count { font-size: var(--fs-xs); color: var(--text-secondary); font-family: var(--font-mono); }
.sp-finished {
  display: flex; justify-content: center;
  padding: var(--space-2) var(--space-3);
  border: 1px solid rgba(0, 255, 179, 0.25);
  border-radius: var(--glass-radius-sm);
  background: rgba(0, 255, 179, 0.06);
  box-shadow: var(--glow-teal);
}
.sp-finished-text { font-size: var(--fs-sm); color: var(--holo-teal); font-family: var(--font-display); letter-spacing: 1px; }
.sp-orbs { display: flex; flex-wrap: wrap; gap: var(--space-4); padding-top: var(--space-2); border-top: 1px solid rgba(255, 255, 255, 0.05); }
.sp-orb-item { position: relative; display: flex; flex-direction: column; align-items: center; gap: 2px; }
.sp-orb-item { opacity: 0.5; filter: saturate(0.5); transition: opacity var(--dur-normal) var(--ease-out), filter var(--dur-normal) var(--ease-out); }
.sp-orb-item.orb-spoken { opacity: 1; filter: none; }
.sp-orb-item.orb-current { opacity: 1; filter: none; }
.sp-orb-item.orb-current :deep(.orb-core) { box-shadow: var(--glow-cyan-strong); }
.sp-legend { display: flex; flex-wrap: wrap; gap: var(--space-3); padding-top: var(--space-2); border-top: 1px solid rgba(255, 255, 255, 0.05); }
.legend-item { display: flex; align-items: center; gap: 4px; }
.legend-icon { font-size: 11px; font-weight: 700; }
.legend-text { font-size: 10px; color: var(--text-muted); }
</style>
