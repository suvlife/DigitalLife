<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { world } from '../store/world';
import * as api from '../api/client';
import { useViewMode } from '../composables/useViewMode';
import GlassPanel from '../components/GlassPanel.vue';
import HoloCard from '../components/HoloCard.vue';
import GlowButton from '../components/GlowButton.vue';
import StatusDot from '../components/StatusDot.vue';
const { navigate } = useViewMode();
const systemStatus = ref<any>(null);
const recentActivities = ref<any[]>([]);
onMounted(async () => {
  try { systemStatus.value = await api.getSystemStatus(); } catch {}
  try { const d = await api.getRecentActivities(8); recentActivities.value = d; } catch {}
});
const phaseText: Record<string, string> = { queued: '排队等待', discussing: '讨论进行中', synthesizing: '正在汇总结论', completed: '已完成', failed: '执行失败', partial_failed: '部分完成' };
</script>
<template>
  <div class="dashboard">
    <!-- 全局信息区 -->
    <GlassPanel padding="lg" class="dash-hero" glow="cyan">
      <div class="hero-content">
        <h1 class="hero-title">多智能体协作操作系统</h1>
        <p class="hero-desc">DigitalLife 是一个面向复杂任务协作的多智能体平台。这里汇聚团队、房间、任务、文件与实时活动，所有推理、发言与工具调用都在同一条可追踪的运行链路中呈现。</p>
        <div class="hero-stats" v-if="systemStatus">
          <div class="hero-stat">
            <StatusDot :status="systemStatus.scheduleState === 'RUNNING' ? 'online' : 'failed'" :label="systemStatus.scheduleState === 'RUNNING' ? '系统运行正常' : '系统未就绪'" />
          </div>
          <div class="hero-stat">
            <span class="hero-stat-label">已配置模型</span>
            <span class="hero-stat-val">{{ systemStatus.initialized ? '是' : '否' }}</span>
          </div>
          <div class="hero-stat">
            <span class="hero-stat-label">协作空间</span>
            <span class="hero-stat-val">{{ world.state.teams.length }}</span>
          </div>
        </div>
      </div>
    </GlassPanel>

    <!-- 团队入口网格 -->
    <div class="dash-section">
      <h2 class="section-title">协作空间</h2>
      <div class="team-grid" v-if="world.state.teams.length">
        <HoloCard v-for="team in world.state.teams" :key="team.id" :status="team.enabled ? 'discussing' : 'idle'" :clickable="true" :hover="true" @click="navigate({ mode: 'team', teamId: team.id })">
          <template #header>
            <div class="team-card-header">
              <StatusDot :status="team.enabled ? 'online' : 'waiting'" />
              <span class="team-card-name">{{ team.name }}</span>
            </div>
          </template>
          <p class="team-card-desc">{{ team.enabled ? '已启用，可进入协作' : '未启用，需在设置中开启' }}</p>
          <template #footer>
            <GlowButton variant="secondary" size="sm">进入空间</GlowButton>
          </template>
        </HoloCard>
      </div>
      <GlassPanel v-else padding="lg" class="empty-state">
        <p class="empty-text">暂无协作空间。请在系统配置中启用团队。</p>
        <GlowButton variant="primary" size="sm" @click="navigate({ mode: 'settings' })">前往配置</GlowButton>
      </GlassPanel>
    </div>

    <!-- 实时活动流 -->
    <div class="dash-section" v-if="recentActivities.length">
      <h2 class="section-title">实时活动</h2>
      <GlassPanel padding="md">
        <div class="activity-list">
          <div v-for="act in recentActivities" :key="act.id" class="activity-item">
            <StatusDot :status="act.status === 'succeeded' ? 'completed' : act.status === 'failed' ? 'failed' : 'active'" size="sm" />
            <span class="act-agent">{{ act.agentName }}</span>
            <span class="act-type">{{ act.type }}</span>
            <span class="act-time">{{ new Date(act.startedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }}</span>
          </div>
        </div>
      </GlassPanel>
    </div>
  </div>
</template>
<style scoped>
.dashboard { padding: var(--space-6); display: flex; flex-direction: column; gap: var(--space-6); }
.dash-hero { animation: fade-in-scale var(--dur-slow) var(--ease-out); }
.hero-content { display: flex; flex-direction: column; gap: var(--space-4); }
.hero-title { font-family: var(--font-display); font-size: var(--fs-2xl); font-weight: 600; color: var(--text-primary); margin: 0; }
.hero-desc { font-size: var(--fs-base); color: var(--text-secondary); line-height: var(--lh-relaxed); max-width: 700px; }
.hero-stats { display: flex; gap: var(--space-8); flex-wrap: wrap; margin-top: var(--space-2); }
.hero-stat { display: flex; flex-direction: column; gap: 4px; }
.hero-stat-label { font-size: var(--fs-xs); color: var(--text-muted); }
.hero-stat-val { font-size: var(--fs-md); font-weight: 600; color: var(--holo-cyan); font-family: var(--font-mono); }
.dash-section { display: flex; flex-direction: column; gap: var(--space-3); }
.section-title { font-size: var(--fs-sm); font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.15em; }
.team-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: var(--space-4); }
.team-card-header { display: flex; align-items: center; gap: 6px; }
.team-card-name { font-size: var(--fs-md); font-weight: 500; color: var(--text-primary); }
.team-card-desc { font-size: var(--fs-sm); color: var(--text-secondary); }
.empty-state { display: flex; flex-direction: column; align-items: center; gap: var(--space-4); text-align: center; }
.empty-text { color: var(--text-muted); }
.activity-list { display: flex; flex-direction: column; gap: var(--space-2); }
.activity-item { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-2) 0; border-bottom: 1px solid rgba(255,255,255,0.03); }
.activity-item:last-child { border-bottom: none; }
.act-agent { font-size: var(--fs-sm); color: var(--text-primary); font-weight: 500; min-width: 80px; }
.act-type { font-size: var(--fs-xs); color: var(--text-secondary); flex: 1; }
.act-time { font-size: var(--fs-xs); color: var(--text-muted); font-family: var(--font-mono); }
</style>
