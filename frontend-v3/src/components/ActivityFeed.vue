<script setup lang="ts">
import { computed, ref } from 'vue';
import type { Activity, Agent } from '../domain/types';
import GlassPanel from './GlassPanel.vue';
import StatusDot from './StatusDot.vue';

const props = withDefaults(defineProps<{
  activities: readonly Activity[];
  agents: readonly Agent[];
  maxItems?: number;
}>(), { maxItems: 20 });

/* ── 活动类型配置：颜色 / 图标 / 标签 ── */
interface TypeConfig {
  label: string;
  color: string;
  icon: string; // svg path (viewBox 0 0 24 24)
}
const TYPE_CONFIG: Record<string, TypeConfig> = {
  llm_infer:        { label: '推理',   color: 'var(--holo-cyan)',   icon: 'M12 2a7 7 0 0 1 7 7c0 2.4-1.2 4.1-2.6 5.6-.9 1-1.4 1.8-1.4 3.4h-6c0-1.6-.5-2.4-1.4-3.4C6.2 13.1 5 11.4 5 9a7 7 0 0 1 7-7zm-3 18h6v1a1 1 0 0 1-1 1h-4a1 1 0 0 1-1-1v-1z' },
  reasoning:        { label: '推理',   color: 'var(--holo-cyan)',   icon: 'M12 2a7 7 0 0 1 7 7c0 2.4-1.2 4.1-2.6 5.6-.9 1-1.4 1.8-1.4 3.4h-6c0-1.6-.5-2.4-1.4-3.4C6.2 13.1 5 11.4 5 9a7 7 0 0 1 7-7zm-3 18h6v1a1 1 0 0 1-1 1h-4a1 1 0 0 1-1-1v-1z' },
  chat_reply:       { label: '发言',   color: 'var(--holo-teal)',   icon: 'M4 3h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2z' },
  tool_call:        { label: '工具',   color: 'var(--holo-amber)',  icon: 'M14.7 6.3a4.5 4.5 0 0 0-6 5.6L3 17.6V21h3.4l5.7-5.7a4.5 4.5 0 0 0 5.6-6l-3.2 3.2-2.5-.7-.7-2.5 3.4-3z' },
  retry:            { label: '重试',   color: 'var(--holo-amber)',  icon: 'M12 5V1L7 6l5 5V7a5 5 0 1 1-5 5H5a7 7 0 1 0 7-7z' },
  llm_retry:        { label: '重试',   color: 'var(--holo-amber)',  icon: 'M12 5V1L7 6l5 5V7a5 5 0 1 1-5 5H5a7 7 0 1 0 7-7z' },
  compact:          { label: '压缩',   color: 'var(--holo-purple)', icon: 'M4 4h16v4H4V4zm1 6h14v10a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V10zm4 3v2h6v-2H9z' },
  task_received:    { label: '接收任务', color: 'var(--holo-ice)',  icon: 'M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zm8 7L4 6v2l8 5 8-5V6l-8 5z' },
  message_received: { label: '接收消息', color: 'var(--holo-ice)',  icon: 'M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zm8 7L4 6v2l8 5 8-5V6l-8 5z' },
};
const DEFAULT_TYPE: TypeConfig = { label: '活动', color: 'var(--holo-ice)', icon: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm1 5v6l4 2-.8 1.7L11 14V7h2z' };

const typeConfig = (type: string): TypeConfig => TYPE_CONFIG[type] ?? DEFAULT_TYPE;

/* ── 活动状态 -> StatusDot status ── */
type DotStatus = 'online' | 'active' | 'thinking' | 'waiting' | 'completed' | 'failed' | 'retrying' | 'connecting';
const STATUS_MAP: Record<string, DotStatus> = {
  running: 'active',
  in_progress: 'active',
  started: 'active',
  pending: 'waiting',
  waiting: 'waiting',
  completed: 'completed',
  done: 'completed',
  success: 'completed',
  succeeded: 'completed',
  failed: 'failed',
  error: 'failed',
  retrying: 'retrying',
};
const dotStatus = (status: string): DotStatus => STATUS_MAP[status] ?? 'waiting';

/* ── Agent 名称解析 ── */
const agentNameMap = computed(() => {
  const map = new Map<number, string>();
  for (const a of props.agents) map.set(a.id, a.name);
  return map;
});
const agentName = (activity: Activity): string => {
  const fromProp = agentNameMap.value.get(activity.agentId);
  if (fromProp) return fromProp;
  const fromActivity = (activity as Activity & { agentName?: string }).agentName;
  if (fromActivity) return fromActivity;
  return `Agent #${activity.agentId}`;
};

/* ── 展示列表：取最近 maxItems 条，新的在前 ── */
const visibleActivities = computed(() =>
  [...props.activities].slice(-props.maxItems).reverse(),
);

/* ── 时间格式化 ── */
const formatTime = (iso: string | null): string => {
  if (!iso) return '--:--:--';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString('zh-CN', { hour12: false });
};

/* ── 摘要 / 详情 ── */
const summary = (a: Activity): string => a.title || a.detail || typeConfig(a.type).label;
const hasDetail = (a: Activity): boolean => !!a.detail && a.detail !== a.title;

const expanded = ref<Set<number>>(new Set());
const toggle = (id: number) => {
  const next = new Set(expanded.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  expanded.value = next;
};
const isExpanded = (id: number) => expanded.value.has(id);
</script>

<template>
  <GlassPanel padding="none" class="activity-feed">
    <header class="feed-header">
      <span class="feed-title">活动流</span>
      <span class="feed-subtitle">ACTIVITY FEED</span>
      <span class="feed-count">{{ visibleActivities.length }}</span>
    </header>

    <div class="feed-body">
      <div v-if="visibleActivities.length === 0" class="feed-empty">
        <svg class="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="9" opacity="0.4" />
          <path d="M12 7v5l3 3" stroke-linecap="round" />
        </svg>
        <span>暂无活动记录</span>
      </div>

      <div v-else class="timeline">
        <div
          v-for="activity in visibleActivities"
          :key="activity.id"
          class="timeline-item"
          :class="{ 'item-expanded': isExpanded(activity.id), 'item-clickable': hasDetail(activity) }"
          :style="{ '--type-color': typeConfig(activity.type).color }"
          @click="hasDetail(activity) && toggle(activity.id)"
        >
          <div class="timeline-node">
            <span class="node-dot"></span>
          </div>

          <div class="timeline-content">
            <div class="item-head">
              <svg class="type-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path :d="typeConfig(activity.type).icon" />
              </svg>
              <span class="agent-name">{{ agentName(activity) }}</span>
              <span class="type-label">{{ typeConfig(activity.type).label }}</span>
              <span class="item-time">{{ formatTime(activity.startedAt) }}</span>
              <StatusDot :status="dotStatus(activity.status)" />
            </div>

            <div class="item-summary">{{ summary(activity) }}</div>

            <div v-if="isExpanded(activity.id) && hasDetail(activity)" class="item-detail">
              {{ activity.detail }}
            </div>
          </div>
        </div>
      </div>
    </div>
  </GlassPanel>
</template>

<style scoped>
.activity-feed { display: flex; flex-direction: column; height: 100%; min-height: 0; overflow: hidden; }

/* ── 头部 ── */
.feed-header {
  display: flex; align-items: baseline; gap: var(--space-2);
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--glass-border);
  flex-shrink: 0;
}
.feed-title { font-family: var(--font-display); font-size: var(--fs-sm); font-weight: 600; color: var(--text-primary); letter-spacing: 0.08em; }
.feed-subtitle { font-family: var(--font-mono); font-size: 9px; color: var(--text-muted); letter-spacing: 0.2em; }
.feed-count {
  margin-left: auto;
  font-family: var(--font-mono); font-size: var(--fs-xs);
  color: var(--holo-cyan); background: var(--glass-bg-active);
  border: 1px solid var(--glass-border); border-radius: 10px;
  padding: 1px 8px;
}

/* ── 滚动区 ── */
.feed-body { flex: 1; min-height: 0; overflow-y: auto; padding: var(--space-4) var(--space-5); scrollbar-width: thin; scrollbar-color: var(--glass-border-hover) transparent; }
.feed-body::-webkit-scrollbar { width: 4px; }
.feed-body::-webkit-scrollbar-thumb { background: var(--glass-border-hover); border-radius: 2px; }
.feed-body::-webkit-scrollbar-track { background: transparent; }

/* ── 空状态 ── */
.feed-empty {
  height: 100%; min-height: 160px;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--space-3);
  color: var(--text-muted); font-size: var(--fs-sm);
}
.empty-icon { width: 32px; height: 32px; opacity: 0.5; }

/* ── 时间线 ── */
.timeline { position: relative; padding-left: 18px; }
.timeline::before {
  content: ''; position: absolute; left: 4px; top: 6px; bottom: 6px;
  width: 1px;
  background: linear-gradient(to bottom, transparent, var(--glass-border-hover) 12%, var(--glass-border-hover) 88%, transparent);
}

.timeline-item { position: relative; padding: var(--space-2) var(--space-2) var(--space-2) var(--space-3); border-radius: var(--glass-radius-sm); transition: background var(--dur-fast) var(--ease-out); }
.timeline-item + .timeline-item { margin-top: var(--space-1); }
.item-clickable { cursor: pointer; }
.item-clickable:hover { background: var(--glass-bg-active); }

/* 节点 */
.timeline-node { position: absolute; left: -18px; top: 12px; width: 9px; height: 9px; display: flex; align-items: center; justify-content: center; }
.node-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--type-color);
  box-shadow: 0 0 8px var(--type-color);
  transition: box-shadow var(--dur-normal) var(--ease-out);
}
.timeline-item:hover .node-dot { box-shadow: 0 0 12px var(--type-color), 0 0 4px var(--type-color); }

/* 内容 */
.timeline-content { min-width: 0; }
.item-head { display: flex; align-items: center; gap: var(--space-2); min-width: 0; }
.type-icon { width: 13px; height: 13px; color: var(--type-color); flex-shrink: 0; filter: drop-shadow(0 0 3px var(--type-color)); }
.agent-name { font-size: var(--fs-sm); font-weight: 600; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 120px; }
.type-label {
  font-size: 10px; font-family: var(--font-mono); letter-spacing: 0.05em;
  color: var(--type-color);
  border: 1px solid var(--type-color); border-radius: 4px;
  padding: 0 5px; line-height: 1.5;
  opacity: 0.85; flex-shrink: 0;
}
.item-time { margin-left: auto; font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); flex-shrink: 0; }

.item-summary {
  margin-top: 2px;
  font-size: var(--fs-xs); line-height: var(--lh-normal);
  color: var(--text-secondary);
  overflow: hidden; text-overflow: ellipsis;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
}
.item-expanded .item-summary { -webkit-line-clamp: unset; display: block; }

.item-detail {
  margin-top: var(--space-2);
  padding: var(--space-2) var(--space-3);
  font-family: var(--font-mono); font-size: var(--fs-xs); line-height: var(--lh-normal);
  color: var(--text-secondary);
  background: rgba(0, 0, 0, 0.25);
  border-left: 2px solid var(--type-color);
  border-radius: 0 var(--glass-radius-sm) var(--glass-radius-sm) 0;
  white-space: pre-wrap; word-break: break-word;
}
</style>
