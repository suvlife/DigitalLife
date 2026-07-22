<script setup lang="ts">
import { onMounted, ref, computed } from 'vue';
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
const usage = ref<{ realtimeTokens: number; activeAgents: number } | null>(null);

const notInitialized = computed(() => systemStatus.value && !systemStatus.value.initialized);

onMounted(async () => {
  try { systemStatus.value = await api.getSystemStatus(); } catch {}
  // 活动流需按 team 维度拉取（后端 /activities.json 要求 room/team/agent 之一），
  // 汇总所有团队最近活动并按时间排序取前 8 条。
  try {
    const all: any[] = [];
    for (const t of world.state.teams) {
      try { const acts = await api.getActivities(t.id); all.push(...acts); } catch {}
    }
    recentActivities.value = all
      .sort((a, b) => new Date(b.startedAt || 0).getTime() - new Date(a.startedAt || 0).getTime())
      .slice(0, 8);
  } catch {}
  try { usage.value = await api.getUsageRealtime(); } catch {}
});

const phaseText: Record<string, string> = { queued: '排队等待', discussing: '讨论进行中', synthesizing: '正在汇总结论', completed: '已完成', failed: '执行失败', partial_failed: '部分完成' };
</script>

<template>
  <div class="dashboard">
    <!-- 未初始化：快速初始化引导 -->
    <GlassPanel v-if="notInitialized" padding="lg" glow="amber" class="init-banner">
      <div class="init-content">
        <h2 class="init-title">欢迎使用 DigitalLife</h2>
        <p class="init-desc">尚未配置大模型服务。配置至少一个 LLM 服务后，即可创建团队并发起多智能体协作讨论。</p>
        <div class="init-steps">
          <div class="init-step"><span class="step-num">1</span><span class="step-text">添加 LLM 服务（支持 OpenAI 兼容 / Anthropic / Gemini / 本地 Ollama）</span></div>
          <div class="init-step"><span class="step-num">2</span><span class="step-text">启用一个内置团队，或创建自己的团队</span></div>
          <div class="init-step"><span class="step-num">3</span><span class="step-text">进入主问策房间，输入任务开始协作</span></div>
        </div>
        <GlowButton variant="primary" size="md" @click="navigate({ mode: 'settings' })">前往配置大模型 →</GlowButton>
      </div>
    </GlassPanel>

    <!-- 全局信息区 -->
    <GlassPanel padding="lg" class="dash-hero" glow="cyan">
      <div class="hero-content">
        <h1 class="hero-title">多智能体协作操作系统</h1>
        <p class="hero-desc">DigitalLife 是一个面向复杂任务协作的多智能体平台。这里汇聚团队、房间、任务、文件与实时活动，所有推理、发言与工具调用都在同一条可追踪的运行链路中呈现。</p>
        <div class="hero-stats" v-if="systemStatus">
          <div class="hero-stat">
            <StatusDot :status="systemStatus.schedule_state === 'RUNNING' ? 'online' : 'failed'" :label="systemStatus.schedule_state === 'RUNNING' ? '系统运行正常' : '系统未就绪'" />
          </div>
          <div class="hero-stat">
            <span class="hero-stat-label">协作空间</span>
            <span class="hero-stat-val">{{ world.state.teams.length }}</span>
          </div>
          <div class="hero-stat" v-if="usage">
            <span class="hero-stat-label">活跃 Agent</span>
            <span class="hero-stat-val">{{ usage.activeAgents }}</span>
          </div>
          <div class="hero-stat" v-if="usage">
            <span class="hero-stat-label">实时 Token</span>
            <span class="hero-stat-val">{{ usage.realtimeTokens }}/s</span>
          </div>
          <div class="hero-stat" v-if="systemStatus.health?.memory_rss_mb">
            <span class="hero-stat-label">内存</span>
            <span class="hero-stat-val">{{ systemStatus.health.memory_rss_mb }}M</span>
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
            <span class="act-agent">{{ act.agentName || `大师 ${act.agentId}` }}</span>
            <span class="act-type">{{ act.title || act.type }}</span>
            <span class="act-time">{{ act.startedAt ? new Date(act.startedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '' }}</span>
          </div>
        </div>
      </GlassPanel>
    </div>
  </div>
</template>

<style scoped>
.dashboard { padding: var(--space-6); display: flex; flex-direction: column; gap: var(--space-6); }
.init-banner { animation: fade-in-up var(--dur-normal) var(--ease-out); }
.init-content { display: flex; flex-direction: column; gap: var(--space-4); }
.init-title { font-family: var(--font-display); font-size: var(--fs-lg); font-weight: 600; color: var(--text-primary); margin: 0; }
.init-desc { font-size: var(--fs-base); color: var(--text-secondary); line-height: var(--lh-normal); }
.init-steps { display: flex; flex-direction: column; gap: var(--space-2); }
.init-step { display: flex; align-items: center; gap: var(--space-3); }
.step-num { width: 22px; height: 22px; border-radius: 50%; background: rgba(255,200,80,0.15); color: var(--holo-amber); border: 1px solid rgba(255,200,80,0.3); display: flex; align-items: center; justify-content: center; font-size: var(--fs-xs); font-weight: 600; flex-shrink: 0; }
.step-text { font-size: var(--fs-sm); color: var(--text-secondary); }
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
