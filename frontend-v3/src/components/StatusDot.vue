<script setup lang="ts">
const props = withDefaults(defineProps<{
  status?: 'online' | 'active' | 'thinking' | 'waiting' | 'completed' | 'failed' | 'retrying' | 'connecting';
  label?: string;
  size?: 'sm' | 'md';
}>(), { status: 'waiting', size: 'sm' });

const colorMap = { online: 'var(--holo-teal)', active: 'var(--holo-cyan)', thinking: 'var(--holo-cyan)', waiting: 'var(--holo-silver)', completed: 'var(--holo-teal)', failed: 'var(--holo-red)', retrying: 'var(--holo-amber)', connecting: 'var(--holo-amber)' };
const pulseMap = { online: false, active: true, thinking: true, waiting: false, completed: false, failed: false, retrying: true, connecting: true };
const labelMap = { online: '在线', active: '活跃', thinking: '推理中', waiting: '等待中', completed: '已完成', failed: '失败', retrying: '重试中', connecting: '连接中' };
</script>
<template>
  <span class="status-dot" :class="{ 'dot-pulse': pulseMap[status], 'dot-sm': size === 'sm' }" :style="{ '--dot-color': colorMap[status] }">
    <span class="dot-core"></span>
    <span class="dot-label" v-if="label !== undefined">{{ label || labelMap[status] }}</span>
  </span>
</template>
<style scoped>
.status-dot { display: inline-flex; align-items: center; gap: 6px; }
.dot-core { width: 8px; height: 8px; border-radius: 50%; background: var(--dot-color); box-shadow: 0 0 6px var(--dot-color); flex-shrink: 0; }
.dot-pulse .dot-core { animation: pulse-glow 1.5s ease-in-out infinite; }
.dot-sm .dot-core { width: 6px; height: 6px; }
.dot-label { font-size: var(--fs-xs); color: var(--text-secondary); white-space: nowrap; }
</style>
