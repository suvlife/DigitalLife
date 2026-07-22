<script setup lang="ts">
import { onMounted, watch, computed, ref } from 'vue';
import { world } from '../store/world';
import * as api from '../api/client';
import { useViewMode } from '../composables/useViewMode';
import GlassPanel from '../components/GlassPanel.vue';
import HoloCard from '../components/HoloCard.vue';
import AgentOrb from '../components/AgentOrb.vue';
import GlowButton from '../components/GlowButton.vue';
import StatusDot from '../components/StatusDot.vue';
import DeptTree from '../components/DeptTree.vue';

const { teamId, navigate } = useViewMode();
const team = computed(() => world.state.team);
const groupRooms = computed(() => world.state.rooms.filter(r => r.type === 'group'));
const deptTree = ref<api.DeptTreeNode | null>(null);

const questionRoom = computed(() => {
  if (team.value?.questionRoomId) return groupRooms.value.find(r => r.id === team.value!.questionRoomId) || null;
  // 兜底：含 task/root 标签的房间，否则成员最多的房间
  const tagged = groupRooms.value.find(r => r.tags?.includes('task') || r.tags?.includes('root'));
  if (tagged) return tagged;
  return [...groupRooms.value].sort((a, b) => b.agentIds.length - a.agentIds.length)[0] || null;
});

function enterRoom(roomId: number) { navigate({ mode: 'room', roomId }); }
function startNew() { if (questionRoom.value) enterRoom(questionRoom.value.id); }

async function loadDept(id: number) { try { deptTree.value = await api.getDeptTree(id); } catch { deptTree.value = null; } }

onMounted(() => { if (teamId.value) { world.loadTeam(teamId.value); loadDept(teamId.value); } });
watch(teamId, (id) => { if (id) { world.loadTeam(id); loadDept(id); } });
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

    <!-- 主问策房间直达 -->
    <div class="team-section" v-if="questionRoom">
      <h2 class="section-title">主问策房间</h2>
      <HoloCard :status="questionRoom.state === 'scheduling' ? 'discussing' : 'idle'" :clickable="true" :hover="true" glow-card @click="enterRoom(questionRoom.id)">
        <template #header>
          <div class="room-card-header">
            <StatusDot :status="questionRoom.state === 'scheduling' ? 'active' : 'waiting'" />
            <span class="room-card-name">{{ questionRoom.name }}</span>
            <span class="root-badge">主</span>
          </div>
        </template>
        <p class="room-card-info">{{ questionRoom.agentIds.length }} 位大师 · {{ questionRoom.state === 'scheduling' ? '讨论中' : '待命' }}</p>
        <p v-if="questionRoom.initialTopic" class="room-topic">{{ questionRoom.initialTopic }}</p>
      </HoloCard>
    </div>

    <div class="team-section">
      <h2 class="section-title">研究室（{{ groupRooms.length }}）</h2>
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

    <div class="team-columns">
      <!-- 团队成员 -->
      <div class="team-section" v-if="world.state.agents.length">
        <h2 class="section-title">团队成员（{{ world.state.agents.length }}）</h2>
        <GlassPanel padding="md">
          <div class="agent-grid">
            <div v-for="agent in world.state.agents" :key="agent.id" class="agent-cell">
              <AgentOrb :name="agent.name" :status="agent.status as any" :size="'md'" :active="agent.status === 'active'" />
              <span v-if="agent.model" class="agent-model">{{ agent.model }}</span>
            </div>
          </div>
        </GlassPanel>
      </div>

      <!-- 部门结构 -->
      <div class="team-section" v-if="deptTree">
        <h2 class="section-title">部门结构</h2>
        <GlassPanel padding="md">
          <DeptTree :node="deptTree" />
        </GlassPanel>
      </div>
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
.root-badge { font-size: 10px; padding: 0 5px; border-radius: 4px; background: rgba(0,217,255,0.12); color: var(--holo-cyan); border: 1px solid var(--glass-border); }
.room-card-info { font-size: var(--fs-sm); color: var(--text-secondary); }
.room-topic { font-size: var(--fs-xs); color: var(--text-muted); font-style: italic; }
.room-tags { font-size: var(--fs-xs); color: var(--text-muted); font-family: var(--font-mono); }
.team-columns { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-5); align-items: start; }
@media (max-width: 900px) { .team-columns { grid-template-columns: 1fr; } }
.agent-grid { display: flex; flex-wrap: wrap; gap: var(--space-5); }
.agent-cell { display: flex; flex-direction: column; align-items: center; gap: 4px; }
.agent-model { font-size: 10px; color: var(--text-faint); font-family: var(--font-mono); }
.loading-state { padding: var(--space-12); display: flex; justify-content: center; }
.loading-text { color: var(--text-muted); text-align: center; }
</style>
