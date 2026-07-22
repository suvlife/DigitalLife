import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router';
import DashboardView from '../views/DashboardView.vue';
import TeamView from '../views/TeamView.vue';
import RoomView from '../views/RoomView.vue';
import SettingsView from '../views/SettingsView.vue';
import ArchiveView from '../views/ArchiveView.vue';

// V3 生产路径为 /v3/，路由 history base 对齐，保证深链刷新可正确回退到 index.html。
const routes: RouteRecordRaw[] = [
  { path: '/', name: 'dashboard', component: DashboardView },
  { path: '/team/:teamId', name: 'team', component: TeamView, props: true },
  { path: '/team/:teamId/room/:roomId', name: 'room', component: RoomView, props: true },
  { path: '/settings', name: 'settings', component: SettingsView },
  { path: '/archive', name: 'archive', component: ArchiveView },
  // 兜底：未知路径回到总览
  { path: '/:pathMatch(.*)*', redirect: '/' },
];

export const router = createRouter({
  history: createWebHistory('/v3/'),
  routes,
});
