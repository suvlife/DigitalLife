<script setup lang="ts">
import { onMounted } from 'vue';
import { world } from './store/world';
import TopBar from './layout/TopBar.vue';
import BottomBar from './layout/BottomBar.vue';
import SideRail from './layout/SideRail.vue';
import DetailDock from './layout/DetailDock.vue';

onMounted(() => { world.loadTeams(); });
</script>
<template>
  <div class="app-shell">
    <TopBar />
    <div class="app-body">
      <SideRail />
      <main class="app-main">
        <router-view />
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
