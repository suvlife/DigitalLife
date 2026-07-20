<script setup lang="ts">
import { world } from '../store/world';
import { useViewMode } from '../composables/useViewMode';
import HoloCard from '../components/HoloCard.vue';
import StatusDot from '../components/StatusDot.vue';
const { mode, teamId, navigate } = useViewMode();
function selectTeam(id: number) { navigate({ mode: 'team', teamId: id }); }
</script>
<template>
  <aside class="side-rail">
    <div class="rail-header">
      <span class="rail-title">协作空间</span>
      <span class="rail-count">{{ world.state.teams.length }}</span>
    </div>
    <div class="rail-list">
      <HoloCard v-for="team in world.state.teams" :key="team.id" :status="team.enabled ? 'discussing' : 'idle'" :clickable="true" :hover="true"
        :class="{ 'rail-active': teamId === team.id && mode === 'team' }" @click="selectTeam(team.id)">
        <template #header>
          <div class="rail-card-header">
            <StatusDot :status="team.enabled ? 'online' : 'waiting'" />
            <span class="rail-team-name">{{ team.name }}</span>
          </div>
        </template>
        <div class="rail-card-body">{{ team.enabled ? '已启用' : '未启用' }}</div>
      </HoloCard>
    </div>
  </aside>
</template>
<style scoped>
.side-rail { width: 220px; flex-shrink: 0; display: flex; flex-direction: column; background: rgba(5, 8, 16, 0.5); backdrop-filter: blur(12px); border-right: 1px solid var(--glass-border); overflow: hidden; }
.rail-header { padding: var(--space-4) var(--space-4) var(--space-2); display: flex; align-items: center; justify-content: space-between; }
.rail-title { font-size: var(--fs-xs); color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.15em; }
.rail-count { font-size: var(--fs-xs); color: var(--holo-cyan); font-family: var(--font-mono); }
.rail-list { flex: 1; overflow-y: auto; padding: var(--space-2); display: flex; flex-direction: column; gap: var(--space-2); }
.rail-list :deep(.holo-card-inner) { padding: var(--space-3); gap: var(--space-1); }
.rail-active { border-color: var(--glass-border-active) !important; background: var(--glass-bg-active) !important; }
.rail-card-header { display: flex; align-items: center; gap: 6px; }
.rail-team-name { font-size: var(--fs-sm); font-weight: 500; color: var(--text-primary); }
.rail-card-body { font-size: var(--fs-xs); color: var(--text-muted); }
</style>
