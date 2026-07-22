<script setup lang="ts">
import { computed } from 'vue';

type Status = 'idle' | 'reading' | 'thinking' | 'speaking' | 'working' | 'retrying' | 'completed' | 'failed';

const props = withDefaults(defineProps<{
  name?: string;
  status?: Status;
  size?: 'sm' | 'md' | 'lg';
  active?: boolean;
  statusLabel?: string;
}>(), { status: 'idle', size: 'md', active: false });

const sizeMap = { sm: 32, md: 44, lg: 56 };

// 状态色（与深蓝底 #293f76 保证 ≥3:1 对比）
const statusColor: Record<Status, string> = {
  idle: 'var(--text-faint)',
  reading: 'var(--holo-silver)',
  thinking: 'var(--holo-cyan)',
  speaking: 'var(--holo-teal)',
  working: 'var(--holo-amber)',
  retrying: 'var(--holo-amber)',
  completed: 'var(--holo-teal)',
  failed: 'var(--holo-red)',
};

// 状态符号（直观区分，配合颜色双编码，色盲友好）
const statusIcon: Record<Status, string> = {
  idle: '',
  reading: '📄',
  thinking: '💭',
  speaking: '▶',
  working: '🔍',
  retrying: '↻',
  completed: '✓',
  failed: '✗',
};

// 默认状态文案（可被 statusLabel 覆盖）
const defaultLabel: Record<Status, string> = {
  idle: '静候',
  reading: '阅卷',
  thinking: '推演',
  speaking: '发言',
  working: '调用工具',
  retrying: '重试',
  completed: '已发言',
  failed: '受阻',
};

const initials = (name?: string) => name ? name.slice(0, 2) : '?';
const icon = computed(() => statusIcon[props.status]);
const label = computed(() => props.statusLabel ?? (props.status !== 'idle' ? defaultLabel[props.status] : ''));
const showBadge = computed(() => props.status !== 'idle');
</script>
<template>
  <div class="agent-orb" :class="{ 'orb-active': active || status !== 'idle' }" :style="{ '--orb-size': sizeMap[size] + 'px', '--orb-color': statusColor[status] }">
    <div class="orb-ring" v-if="active"></div>
    <div class="orb-core">
      <span class="orb-text">{{ initials(name) }}</span>
      <span v-if="showBadge" class="orb-status-icon" :class="`icon-${status}`">{{ icon }}</span>
    </div>
    <div class="orb-label" v-if="name">{{ name }}</div>
    <div class="orb-status-label" v-if="label" :style="{ color: statusColor[status] }">{{ label }}</div>
  </div>
</template>
<style scoped>
.agent-orb { position: relative; display: flex; flex-direction: column; align-items: center; gap: 2px; }
.orb-core {
  position: relative;
  width: var(--orb-size); height: var(--orb-size);
  border-radius: 50%;
  background: radial-gradient(circle at 30% 30%, var(--orb-color, var(--text-faint)) 0%, rgba(16, 28, 58, 0.8) 70%);
  border: 2px solid var(--orb-color, var(--glass-border));
  display: flex; align-items: center; justify-content: center;
  transition: all var(--dur-normal) var(--ease-out);
  box-shadow: 0 0 12px rgba(0, 0, 0, 0.3);
}
.orb-active .orb-core { box-shadow: 0 0 16px var(--orb-color), inset 0 0 12px rgba(255,255,255,0.05); animation: pulse-glow 2s ease-in-out infinite; }
.orb-ring {
  position: absolute; top: 0; left: 50%; transform: translateX(-50%);
  width: var(--orb-size); height: var(--orb-size);
  border-radius: 50%; border: 2px solid var(--orb-color);
  animation: pulse-ring 1.5s ease-out infinite; pointer-events: none;
}
.orb-text { font-size: var(--fs-xs); font-weight: 600; color: var(--text-primary); font-family: var(--font-mono); }
.orb-status-icon {
  position: absolute; bottom: -2px; right: -2px;
  width: 18px; height: 18px; border-radius: 50%;
  background: var(--bg-secondary, #0a1628);
  border: 1.5px solid var(--orb-color);
  display: flex; align-items: center; justify-content: center;
  font-size: 10px; line-height: 1; font-weight: 700;
}
.icon-thinking, .icon-reading { font-size: 9px; }
.icon-working { font-size: 8px; }
.orb-label { font-size: 10px; color: var(--text-muted); max-width: 64px; text-align: center; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.orb-status-label { font-size: 9px; font-weight: 500; letter-spacing: 0.3px; }
</style>
