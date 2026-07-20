<script setup lang="ts">
import { computed, onMounted } from 'vue';
import { world } from './store/world';
import { useViewMode } from './composables/useViewMode';
import TopBar from './layout/TopBar.vue';
import BottomBar from './layout/BottomBar.vue';
import SideRail from './layout/SideRail.vue';
import DetailDock from './layout/DetailDock.vue';
import DashboardView from './views/DashboardView.vue';
import TeamView from './views/TeamView.vue';
import RoomView from './views/RoomView.vue';
import SettingsView from './views/SettingsView.vue';
import ArchiveView from './views/ArchiveView.vue';

const { mode } = useViewMode();
onMounted(() => { world.loadTeams(); });
const currentView = computed(() => ({
  dashboard: DashboardView, team: TeamView, room: RoomView,
  settings: SettingsView, archive: ArchiveView,
}[mode.value] || DashboardView));
</script>
<template>
  <div class="app-shell">
    <TopBar />
    <div class="app-body">
      <SideRail />
      <main class="app-main">
        <component :is="currentView" />
      </main>
      <DetailDock />
    </div>
    <BottomBar />
  </div>
</template>
<style scoped>
.app-shell { display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
.app-body { display: flex; flex: 1; overflow: hidden; gap: 1px; }
.app-main { flex: 1; overflow-y: auto; overflow-x: hidden; padding: 0; }
</style>
