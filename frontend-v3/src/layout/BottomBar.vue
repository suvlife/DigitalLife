<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { world } from '../store/world';
import * as api from '../api/client';
const scheduleState = ref(''); const activeAgents = ref(0); const tokenUsage = ref('');
async function loadStatus() {
  try {
    const s = await api.getSystemStatus();
    scheduleState.value = s.schedule_state === 'RUNNING' ? '调度运行中' : s.schedule_state === 'BLOCKED' ? `调度阻塞: ${s.not_running_reason}` : '调度已停止';
    if (s.schedule_state === 'RUNNING') { const u = await api.getUsageRealtime(); tokenUsage.value = `${u.realtimeTokens || 0} tokens/s`; activeAgents.value = u.activeAgents || 0; }
  } catch {}
}
onMounted(() => { loadStatus(); setInterval(loadStatus, 15000); });
</script>
<template>
  <footer class="bottom-bar">
    <div class="bar-section">
      <span class="bar-label">调度</span>
      <span class="bar-value" :class="{ 'val-ok': scheduleState.includes('运行'), 'val-warn': scheduleState.includes('阻塞') }">{{ scheduleState }}</span>
    </div>
    <div class="bar-section">
      <span class="bar-label">实时用量</span>
      <span class="bar-value">{{ tokenUsage || '—' }}</span>
    </div>
    <div class="bar-section">
      <span class="bar-label">活跃Agent</span>
      <span class="bar-value">{{ activeAgents }}</span>
    </div>
    <div class="bar-section bar-right-section">
      <span class="bar-version">v0.9.0 · V3 Holographic</span>
    </div>
  </footer>
</template>
<style scoped>
.bottom-bar { height: 28px; display: flex; align-items: center; gap: var(--space-6); padding: 0 var(--space-5); background: rgba(5, 8, 16, 0.6); backdrop-filter: blur(12px); border-top: 1px solid var(--glass-border); flex-shrink: 0; font-size: var(--fs-xs); }
.bar-section { display: flex; align-items: center; gap: 6px; }
.bar-right-section { margin-left: auto; }
.bar-label { color: var(--text-muted); }
.bar-value { color: var(--text-secondary); font-family: var(--font-mono); }
.val-ok { color: var(--holo-teal); }
.val-warn { color: var(--holo-amber); }
.bar-version { color: var(--text-faint); font-family: var(--font-mono); }
</style>
