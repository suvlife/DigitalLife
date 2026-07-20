<script setup lang="ts">
const props = withDefaults(defineProps<{
  status?: 'discussing' | 'synthesizing' | 'completed' | 'failed' | 'waiting' | 'idle';
  title?: string;
  hover?: boolean;
  clickable?: boolean;
}>(), { status: 'idle', hover: true, clickable: false });

const emit = defineEmits<{ click: [] }>();
const statusColor = { discussing: 'var(--holo-cyan)', synthesizing: 'var(--holo-purple)', completed: 'var(--holo-teal)', failed: 'var(--holo-red)', waiting: 'var(--holo-silver)', idle: 'var(--text-faint)' };
const statusGlow = { discussing: 'var(--glow-cyan)', synthesizing: 'var(--glow-purple)', completed: 'var(--glow-teal)', failed: 'var(--glow-red)', waiting: '', idle: '' };
</script>
<template>
  <div class="holo-card" :class="{ 'holo-clickable': clickable }" :style="{ '--card-color': statusColor[status], '--card-glow': statusGlow[status] }" @click="clickable && emit('click')">
    <div class="holo-card-inner">
      <div v-if="title || $slots.header" class="holo-card-header">
        <slot name="header">
          <div class="holo-card-title-row">
            <span class="holo-status-bar" :style="{ background: statusColor[status] }"></span>
            <h3 class="holo-card-title">{{ title }}</h3>
          </div>
        </slot>
      </div>
      <div v-if="$slots.description" class="holo-card-desc"><slot name="description" /></div>
      <div v-if="$slots.default" class="holo-card-body"><slot /></div>
      <div v-if="$slots.footer" class="holo-card-footer"><slot name="footer" /></div>
    </div>
  </div>
</template>
<style scoped>
.holo-card {
  background: var(--glass-bg);
  backdrop-filter: blur(var(--glass-blur));
  -webkit-backdrop-filter: blur(var(--glass-blur));
  border: 1px solid var(--glass-border);
  border-radius: var(--glass-radius);
  box-shadow: var(--glass-shadow);
  transition: all var(--dur-normal) var(--ease-out);
  position: relative;
  overflow: hidden;
}
.holo-card::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: var(--glass-radius);
  border: 1px solid transparent;
  background: linear-gradient(135deg, var(--card-color, transparent) 0%, transparent 50%) border-box;
  -webkit-mask: linear-gradient(#fff 0 0) padding-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  opacity: 0.3;
  pointer-events: none;
}
.holo-card:hover { border-color: var(--glass-border-hover); background: var(--glass-bg-hover); }
.holo-card[style*="--card-color: var(--holo-cyan)"] { border-color: rgba(0,217,255,0.2); box-shadow: var(--card-glow), var(--glass-shadow); }
.holo-card[style*="--card-color: var(--holo-teal)"] { border-color: rgba(0,255,179,0.2); box-shadow: var(--card-glow), var(--glass-shadow); }
.holo-card[style*="--card-color: var(--holo-purple)"] { border-color: rgba(179,136,255,0.2); box-shadow: var(--card-glow), var(--glass-shadow); }
.holo-card[style*="--card-color: var(--holo-red)"] { border-color: rgba(255,82,82,0.2); box-shadow: var(--card-glow), var(--glass-shadow); }
.holo-clickable { cursor: pointer; }
.holo-clickable:hover { transform: translateY(-2px); border-color: var(--card-color); box-shadow: var(--card-glow), var(--glass-shadow); }
.holo-card-inner { padding: var(--space-5); display: flex; flex-direction: column; gap: var(--space-3); }
.holo-card-title-row { display: flex; align-items: center; gap: var(--space-3); }
.holo-status-bar { width: 3px; height: 18px; border-radius: 2px; flex-shrink: 0; }
.holo-card-title { font-family: var(--font-body); font-size: var(--fs-md); font-weight: 600; color: var(--text-primary); margin: 0; }
.holo-card-desc { font-size: var(--fs-sm); color: var(--text-secondary); line-height: var(--lh-normal); }
.holo-card-body { font-size: var(--fs-base); color: var(--text-secondary); line-height: var(--lh-relaxed); }
.holo-card-footer { display: flex; gap: var(--space-3); align-items: center; margin-top: var(--space-2); }
</style>
