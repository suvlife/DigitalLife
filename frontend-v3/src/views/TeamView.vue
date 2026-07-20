<script setup lang="ts">
import { onMounted, watch, computed } from 'vue';
import { world } from '../store/world';
import { useViewMode } from '../composables/useViewMode';
import GlassPanel from '../components/GlassPanel.vue';
import HoloCard from '../components/HoloCard.vue';
import AgentOrb from '../components/AgentOrb.vue';
import GlowButton from '../components/GlowButton.vue';
import StatusDot from '../components/StatusDot.vue';
const { teamId, navigate } = useViewMode();
const team = computed(() => world.state.team);
const groupRooms = computed(() => world.state.rooms.filter(r => r.type === 'group'));
function enterRoom(roomId: number) { navigate({ mode: 'room', roomId }); }
function startNew() { if (team.value) { world.loadTeam(team.value.id).then(() => { const r = groupRooms.value.find(r => r.tags?.includes('STRATEGY:FAST_CONSENSUS') || r.tags?.includes('STRATEGY:ROUND_ROBIN')); if (r) enterRoom(r.id); }); } }
onMounted(() => { if (teamId.value) world.loadTeam(teamId.value); });
watch(teamId, (id) => { if (id) world.loadTeam(id); });
</script>
<template>
  <div class="team-view" v-if="team">
    <GlassPanel padding="lg" glow="cyan" class="team-hero">
      <h1 class="team-name">{{ team.name }}</h1>
      <p class="team-desc">{{ team.enabled ? '该协作空间已启用，所有大师已就位，可以发起新的讨论任务。' : '该协作空间当前未启用，请在系统配置中开启。' }}</p>
      <div class="team-actions">
        <GlowButton variant="primary" size="md" @click="startNew">发起新讨论</GlowButton>
        <GlowButton variant="secondary" size="md" @click="navigate({ mode: 'settings' })">配置本院</GlowButton>
      </div>
    </GlassPanel>
    <div class="team-section">
      <h2 class="section-title">研究室</h2>
      <div class="room-grid">
        <HoloCard v-for="room in groupRooms" :key="room.id" :status="room.state === 'scheduling' ? 'discussing' : 'idle'" :clickable="true" :hover="true" @click="enterRoom(room.id)">
          <template #header>
            <div class="room-card-header">
              <StatusDot :status="room.state === 'scheduling' ? 'active' : 'waiting'" />
              <span class="room-card-name">{{ room.name }}</span>
            </div>
          </template>
          <p class="room-card-info">{{ room.agentIds.length }} 位大师 · {{ room.state === 'scheduling' ? '讨论中' : '待命' }}</p>
          <template #footer>
            <span class="room-tags" v-if="room.tags?.length">{{ room.tags.join(' · ') }}</span>
          </template>
        </HoloCard>
      </div>
    </div>
    <div class="team-section" v-if="world.state.agents.length">
      <h2 class="section-title">团队成员</h2>
      <GlassPanel padding="md">
        <div class="agent-grid">
          <div v-for="agent in world.state.agents" :key="agent.id" class="agent-cell">
            <AgentOrb :name="agent.name" :status="agent.status as any" :size="'md'" :active="agent.status === 'active'" />
          </div>
        </div>
      </GlassPanel>
    </div>
  </div>
  <div v-else class="loading-state">
    <GlassPanel padding="lg"><p class="loading-text">正在加载团队信息...</p></GlassPanel>
  </div>
</template>
<style scoped>
.team-view { padding: var(--space-6); display: flex; flex-direction: column; gap: var(--space-6); }
.team-hero { animation: fade-in-up var(--dur-normal) var(--ease-out); }
.team-name { font-family: var(--font-display); font-size: var(--fs-xl); font-weight: 600; color: var(--text-primary); margin: 0 0 var(--space-2); }
.team-desc { font-size: var(--fs-base); color: var(--text-secondary); line-height: var(--lh-normal); margin-bottom: var(--space-4); }
.team-actions { display: flex; gap: var(--space-3); }
.team-section { display: flex; flex-direction: column; gap: var(--space-3); }
.section-title { font-size: var(--fs-sm); font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.15em; }
.room-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: var(--space-4); }
.room-card-header { display: flex; align-items: center; gap: 6px; }
.room-card-name { font-size: var(--fs-base); font-weight: 500; color: var(--text-primary); }
.room-card-info { font-size: var(--fs-sm); color: var(--text-secondary); }
.room-tags { font-size: var(--fs-xs); color: var(--text-muted); font-family: var(--font-mono); }
.agent-grid { display: flex; flex-wrap: wrap; gap: var(--space-5); }
.agent-cell { display: flex; flex-direction: column; align-items: center; }
.loading-state { padding: var(--space-12); display: flex; justify-content: center; }
.loading-text { color: var(--text-muted); text-align: center; }
</style>
