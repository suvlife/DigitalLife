import { createRouter, createWebHistory } from 'vue-router';
import HomePage from './pages/HomePage.vue';
import TeamCourtyardPage from './pages/TeamCourtyardPage.vue';
import RunPage from './pages/RunPage.vue';
import RoomPage from './pages/RoomPage.vue';
import ArchivePage from './pages/ArchivePage.vue';
import SettingsPage from './pages/SettingsPage.vue';
export default createRouter({
  history: createWebHistory('/'),
  routes: [
    { path: '/', name: 'home', component: HomePage },
    { path: '/teams/:teamId', name: 'team', component: TeamCourtyardPage },
    { path: '/teams/:teamId/runs/:runId', name: 'run', component: RunPage },
    { path: '/teams/:teamId/rooms/:roomId', name: 'room', component: RoomPage },
    { path: '/teams/:teamId/archive', name: 'team-archive', component: ArchivePage },
    { path: '/archive', name: 'archive', component: ArchivePage },
    { path: '/settings/:section?', name: 'settings', component: SettingsPage },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
});
