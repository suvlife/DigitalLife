<script setup lang="ts">
const props = withDefaults(defineProps<{
  name?: string;
  status?: 'idle' | 'thinking' | 'speaking' | 'working' | 'retrying' | 'completed' | 'failed';
  size?: 'sm' | 'md' | 'lg';
  active?: boolean;
}>(), { status: 'idle', size: 'md', active: false });

const sizeMap = { sm: 32, md: 44, lg: 56 };
const statusColor = { idle: 'var(--text-faint)', thinking: 'var(--holo-cyan)', speaking: 'var(--holo-teal)', working: 'var(--holo-amber)', retrying: 'var(--holo-amber)', completed: 'var(--holo-teal)', failed: 'var(--holo-red)' };
const initials = (name?: string) => name ? name.slice(0, 2) : '?';
</script>
<template>
  <div class="agent-orb" :class="{ 'orb-active': active || status !== 'idle' }" :style="{ '--orb-size': sizeMap[size] + 'px', '--orb-color': statusColor[status] }">
    <div class="orb-ring" v-if="active"></div>
    <div class="orb-core">
      <span class="orb-text">{{ initials(name) }}</span>
    </div>
    <div class="orb-label" v-if="name">{{ name }}</div>
  </div>
</template>
<style scoped>
.agent-orb { position: relative; display: flex; flex-direction: column; align-items: center; gap: 4px; }
.orb-core {
  width: var(--orb-size); height: var(--orb-size);
  border-radius: 50%;
  background: radial-gradient(circle at 30% 30%, var(--orb-color, var(--text-faint)) 0%, rgba(10, 20, 35, 0.8) 70%);
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
.orb-label { font-size: 10px; color: var(--text-muted); max-width: 60px; text-align: center; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
