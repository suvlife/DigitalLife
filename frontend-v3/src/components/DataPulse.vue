<script setup lang="ts">
const props = withDefaults(defineProps<{
  value: number; max?: number; label?: string; color?: 'cyan' | 'teal' | 'amber' | 'red' | 'purple';
}>(), { max: 100, color: 'cyan' });
const colorMap = { cyan: 'var(--holo-cyan)', teal: 'var(--holo-teal)', amber: 'var(--holo-amber)', red: 'var(--holo-red)', purple: 'var(--holo-purple)' };
const percent = () => Math.min(100, Math.max(0, (props.value / props.max) * 100));
</script>
<template>
  <div class="data-pulse">
    <div class="pulse-header" v-if="label">
      <span class="pulse-label">{{ label }}</span>
      <span class="pulse-value">{{ value }}{{ max !== 100 ? `/${max}` : '%' }}</span>
    </div>
    <div class="pulse-track">
      <div class="pulse-fill" :style="{ width: percent() + '%', background: colorMap[color], boxShadow: `0 0 8px ${colorMap[color]}` }">
        <div class="pulse-shimmer"></div>
      </div>
    </div>
  </div>
</template>
<style scoped>
.data-pulse { display: flex; flex-direction: column; gap: 4px; }
.pulse-header { display: flex; justify-content: space-between; align-items: center; }
.pulse-label { font-size: var(--fs-xs); color: var(--text-muted); }
.pulse-value { font-size: var(--fs-xs); color: var(--text-secondary); font-family: var(--font-mono); }
.pulse-track { height: 4px; background: rgba(255,255,255,0.04); border-radius: 2px; overflow: hidden; position: relative; }
.pulse-fill { height: 100%; border-radius: 2px; transition: width var(--dur-slow) var(--ease-out); position: relative; overflow: hidden; }
.pulse-shimmer { position: absolute; inset: 0; background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent); animation: shimmer 2s infinite; }
</style>
