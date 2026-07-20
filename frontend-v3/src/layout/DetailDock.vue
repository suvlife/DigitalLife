<script setup lang="ts">
import { world } from '../store/world';
import { useViewMode } from '../composables/useViewMode';
import GlassPanel from '../components/GlassPanel.vue';
import AgentOrb from '../components/AgentOrb.vue';
import StatusDot from '../components/StatusDot.vue';
const { mode, teamId, roomId, navigate } = useViewMode();
const team = computed(() => world.state.teams.find(t => t.id === teamId.value));
const room = computed(() => world.state.rooms.find(r => r.id === roomId.value));
import { computed } from 'vue';
</script>
<template>
  <aside class="detail-dock">
    <GlassPanel padding="md" class="dock-inner">
      <!-- 团队模式：显示团队详情 -->
      <template v-if="mode === 'team' && team">
        <div class="dock-section">
          <h4 class="dock-title">团队信息</h4>
          <p class="dock-desc">{{ team.name }}</p>
          <div class="dock-stats">
            <div class="dock-stat"><span class="stat-val">{{ world.state.agents.length }}</span><span class="stat-label">成员</span></div>
            <div class="dock-stat"><span class="stat-val">{{ world.state.rooms.length }}</span><span class="stat-label">房间</span></div>
          </div>
        </div>
        <div class="dock-section" v-if="world.state.agents.length">
          <h4 class="dock-title">团队成员</h4>
          <div class="dock-agents">
            <AgentOrb v-for="agent in world.state.agents" :key="agent.id" :name="agent.name" :status="agent.status as any" :size="'sm'" :active="agent.status === 'active'" />
          </div>
        </div>
      </template>
      <!-- 房间模式：显示房间成员和活动 -->
      <template v-else-if="mode === 'room' && room">
        <div class="dock-section">
          <h4 class="dock-title">{{ room.name }}</h4>
          <StatusDot :status="room.state === 'scheduling' ? 'active' : 'waiting'" :label="room.state === 'scheduling' ? '讨论进行中' : '等待中'" />
        </div>
        <div class="dock-section" v-if="world.state.agents.length">
          <h4 class="dock-title">本室成员</h4>
          <div class="dock-agents">
            <AgentOrb v-for="agent in world.state.agents.filter(a => room?.agentIds?.includes(a.id))" :key="agent.id" :name="agent.name" :status="agent.status as any" :size="'sm'" :active="agent.status === 'active'" />
          </div>
        </div>
      </template>
      <!-- 默认 -->
      <template v-else>
        <div class="dock-section">
          <h4 class="dock-title">系统面板</h4>
          <p class="dock-desc">选择左侧团队进入协作空间，或在顶部导航至设置和卷宗。</p>
        </div>
      </template>
    </GlassPanel>
  </aside>
</template>
<style scoped>
.detail-dock { width: 340px; flex-shrink: 0; padding: var(--space-3); overflow-y: auto; }
.dock-inner { min-height: 100%; }
.dock-section { display: flex; flex-direction: column; gap: var(--space-2); margin-bottom: var(--space-5); }
.dock-section:last-child { margin-bottom: 0; }
.dock-title { font-size: var(--fs-sm); font-weight: 600; color: var(--text-secondary); margin: 0; }
.dock-desc { font-size: var(--fs-sm); color: var(--text-muted); line-height: var(--lh-normal); }
.dock-stats { display: flex; gap: var(--space-4); margin-top: var(--space-2); }
.dock-stat { display: flex; flex-direction: column; align-items: center; }
.stat-val { font-size: var(--fs-lg); font-weight: 600; color: var(--holo-cyan); font-family: var(--font-mono); }
.stat-label { font-size: var(--fs-xs); color: var(--text-muted); }
.dock-agents { display: flex; flex-wrap: wrap; gap: var(--space-3); }
</style>
