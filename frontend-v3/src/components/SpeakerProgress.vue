<script setup lang="ts">
import { computed } from 'vue';
import AgentOrb from './AgentOrb.vue';
import DataPulse from './DataPulse.vue';
import StatusDot from './StatusDot.vue';
import GlassPanel from './GlassPanel.vue';
import type { Agent, Message } from '../domain/types';

const props = defineProps<{
  members: readonly Agent[];
  messages: readonly Message[];
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

/** 结论已提交 / 房间结束 */
const isFinished = computed(
  () => props.roomStatus === 'completed' || props.roomStatus === 'failed' || props.roomStatus === 'skipped',
);

/** 全员已发言 */
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

/** 每位大师的 Orb 状态 */
const orbStatus = (agent: Agent): 'idle' | 'speaking' | 'completed' => {
  if (agent.id === props.currentAgentId && !isFinished.value) return 'speaking';
  if (hasSpoken(agent.id)) return 'completed';
  return 'idle';
};

const orbActive = (agent: Agent) =>
  agent.id === props.currentAgentId && !isFinished.value;

const panelGlow = computed<'cyan' | 'teal' | 'none'>(() => {
  if (isFinished.value || allSpoken.value) return 'teal';
  if (props.roomStatus === 'discussing') return 'cyan';
  return 'none';
});
</script>

<template>
  <GlassPanel :glow="panelGlow" padding="md" class="speaker-progress">
    <!-- 顶部：状态灯 + 进度条 -->
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

    <!-- 结束态横幅 -->
    <div class="sp-finished" v-if="isFinished || allSpoken">
      <span class="sp-finished-text">
        {{ isFinished ? '本室讨论已结束' : '全部大师已发言' }}
      </span>
    </div>

    <!-- 大师头像行 -->
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
          :status="orbStatus(agent)"
          :active="orbActive(agent)"
          size="md"
        />
        <span class="sp-orb-tag" v-if="orbActive(agent)">执言中</span>
      </div>
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
.sp-finished-text {
  font-size: var(--fs-sm); color: var(--holo-teal);
  font-family: var(--font-display); letter-spacing: 1px;
}

.sp-orbs {
  display: flex; flex-wrap: wrap; gap: var(--space-3);
  padding-top: var(--space-2);
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}
.sp-orb-item { position: relative; display: flex; flex-direction: column; align-items: center; gap: 2px; }

/* 未发言：暗色 */
.sp-orb-item { opacity: 0.45; filter: saturate(0.5); transition: opacity var(--dur-normal) var(--ease-out), filter var(--dur-normal) var(--ease-out); }
/* 已发言：亮起 */
.sp-orb-item.orb-spoken { opacity: 1; filter: none; }
/* 当前执言者：高亮脉冲 */
.sp-orb-item.orb-current { opacity: 1; filter: none; }
.sp-orb-item.orb-current :deep(.orb-core) { box-shadow: var(--glow-cyan-strong); }

.sp-orb-tag {
  font-size: 10px; color: var(--holo-cyan);
  font-family: var(--font-mono); letter-spacing: 0.5px;
  animation: pulse-glow 1.5s ease-in-out infinite;
}
</style>
