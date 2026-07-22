<script setup lang="ts">
import { ref, onMounted } from 'vue';
import * as api from '../../api/client';
import GlassPanel from '../GlassPanel.vue';
import GlowButton from '../GlowButton.vue';
import StatusDot from '../StatusDot.vue';
import FormToggle from '../form/FormToggle.vue';

const status = ref<api.SystemStatus | null>(null);
const metrics = ref<any>(null);
const updateInfo = ref<api.UpdateCheckResult | null>(null);
const loading = ref(false);
const backingUp = ref(false);
const checking = ref(false);
const resuming = ref(false);
const error = ref(''); const notice = ref('');

async function load() {
  loading.value = true; error.value = '';
  try {
    status.value = await api.getSystemStatus();
    try { metrics.value = await (api as any).getMetrics?.() ?? null; } catch { metrics.value = null; }
  } catch (e: any) { error.value = e?.message || '加载失败'; }
  finally { loading.value = false; }
}

async function backup() {
  backingUp.value = true; error.value = ''; notice.value = '';
  try { const r = await api.backupDatabase(); notice.value = `备份成功：${r.backup_file_name}`; }
  catch (e: any) { error.value = e?.message || '备份失败'; }
  finally { backingUp.value = false; }
}

async function checkUpdate() {
  checking.value = true; error.value = ''; updateInfo.value = null;
  try { updateInfo.value = await api.checkUpdate(true); }
  catch (e: any) { error.value = e?.message || '检查失败'; }
  finally { checking.value = false; }
}

async function resumeSchedule() {
  resuming.value = true; error.value = ''; notice.value = '';
  try { await (api as any).resumeSchedule?.(); notice.value = '已尝试恢复调度'; await load(); }
  catch (e: any) { error.value = e?.message || '恢复失败'; }
  finally { resuming.value = false; }
}

async function toggleAutoUpdate(v: boolean) {
  error.value = ''; notice.value = '';
  try { await api.updateSystemConfig({ auto_check_update: v }); notice.value = '已保存'; await load(); }
  catch (e: any) { error.value = e?.message || '保存失败'; }
}

const stateText: Record<string, string> = { RUNNING: '运行中', STOPPED: '已停止', BLOCKED: '已阻塞' };
onMounted(load);
</script>

<template>
  <div class="system-section">
    <div class="section-actions">
      <GlowButton variant="secondary" size="sm" :loading="loading" @click="load">刷新状态</GlowButton>
      <GlowButton variant="primary" size="sm" :loading="backingUp" @click="backup">备份数据库</GlowButton>
      <GlowButton variant="secondary" size="sm" :loading="checking" @click="checkUpdate">检查更新</GlowButton>
      <GlowButton v-if="status?.schedule_state !== 'RUNNING'" variant="secondary" size="sm" :loading="resuming" @click="resumeSchedule">恢复调度</GlowButton>
    </div>
    <p v-if="error" class="msg-error">{{ error }}</p>
    <p v-if="notice" class="msg-ok">{{ notice }}</p>

    <GlassPanel padding="md" v-if="status" class="info-panel">
      <div class="info-row"><span class="info-label">调度状态</span>
        <span class="info-val" :class="{ 'val-ok': status.schedule_state === 'RUNNING', 'val-warn': status.schedule_state !== 'RUNNING' }">
          <StatusDot :status="status.schedule_state === 'RUNNING' ? 'online' : 'failed'" size="sm" /> {{ stateText[status.schedule_state || ''] || status.schedule_state }}
        </span>
      </div>
      <div class="info-row" v-if="status.not_running_reason"><span class="info-label">阻塞原因</span><span class="info-val val-warn">{{ status.not_running_reason }}</span></div>
      <div class="info-row"><span class="info-label">模型配置</span><span class="info-val">{{ status.initialized ? '已就绪' : '未配置' }}</span></div>
      <div class="info-row"><span class="info-label">默认服务</span><span class="info-val">{{ status.default_llm_server || '—' }}</span></div>
      <div class="info-row"><span class="info-label">版本</span><span class="info-val">{{ status.version }}</span></div>
      <div class="info-row"><span class="info-label">语言</span><span class="info-val">{{ status.language }}</span></div>
      <div class="info-row" v-if="(status as any).health"><span class="info-label">数据库</span>
        <span class="info-val" :class="{ 'val-ok': (status as any).health?.db_ready }">{{ (status as any).health?.db_ready ? '连接正常' : '未连接' }}</span>
      </div>
      <div class="info-row" v-if="(status as any).health?.memory_rss_mb"><span class="info-label">内存占用</span><span class="info-val">{{ (status as any).health.memory_rss_mb }} MB</span></div>
    </GlassPanel>

    <GlassPanel padding="md" class="info-panel">
      <FormToggle :model-value="status?.auto_check_update ?? true" label="启动时自动检查更新" @update:model-value="toggleAutoUpdate" />
      <div v-if="updateInfo" class="update-result">
        <div class="info-row"><span class="info-label">当前版本</span><span class="info-val">{{ updateInfo.current_version }}</span></div>
        <div class="info-row"><span class="info-label">最新版本</span>
          <span class="info-val" :class="{ 'val-ok': updateInfo.has_update }">{{ updateInfo.latest_version }}{{ updateInfo.has_update ? ' (有更新)' : '' }}</span>
        </div>
        <div v-if="updateInfo.release_url" class="update-link">
          <a :href="updateInfo.release_url" target="_blank" rel="noopener" class="link">查看 Release →</a>
        </div>
      </div>
    </GlassPanel>

    <GlassPanel v-if="metrics" padding="md" class="info-panel">
      <h3 class="panel-subtitle">运行指标</h3>
      <div class="info-row"><span class="info-label">运行时长</span><span class="info-val">{{ Math.round(metrics.uptime_seconds || 0) }}s</span></div>
      <div class="info-row" v-for="(v, k) in (metrics.counters || {})" :key="k"><span class="info-label">{{ k }}</span><span class="info-val">{{ v }}</span></div>
    </GlassPanel>
  </div>
</template>

<style scoped>
.system-section { display: flex; flex-direction: column; gap: var(--space-4); }
.section-actions { display: flex; gap: var(--space-3); flex-wrap: wrap; }
.msg-error { font-size: var(--fs-sm); color: var(--holo-red); margin: 0; }
.msg-ok { font-size: var(--fs-sm); color: var(--holo-teal); margin: 0; }
.info-panel { display: flex; flex-direction: column; gap: var(--space-2); }
.panel-subtitle { font-size: var(--fs-sm); font-weight: 600; color: var(--text-primary); margin: 0 0 var(--space-2); }
.info-row { display: flex; justify-content: space-between; align-items: center; padding: var(--space-2) 0; border-bottom: 1px solid rgba(255,255,255,0.03); }
.info-label { font-size: var(--fs-sm); color: var(--text-muted); }
.info-val { font-size: var(--fs-sm); color: var(--text-secondary); font-family: var(--font-mono); display: flex; align-items: center; gap: 6px; }
.val-ok { color: var(--holo-teal); }
.val-warn { color: var(--holo-amber); }
.update-result { margin-top: var(--space-3); display: flex; flex-direction: column; gap: var(--space-2); }
.update-link { margin-top: var(--space-2); }
.link { color: var(--holo-cyan); font-size: var(--fs-sm); text-decoration: none; }
.link:hover { text-decoration: underline; }
</style>
