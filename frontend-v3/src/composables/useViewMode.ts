import { computed } from 'vue';
import { router } from '../router';

export type ViewMode = 'dashboard' | 'team' | 'room' | 'settings' | 'archive';
export type NavTarget = { mode: ViewMode; teamId?: number; roomId?: number };

// 路由名 -> ViewMode 映射
const routeMode: Record<string, ViewMode> = {
  dashboard: 'dashboard', team: 'team', room: 'room', settings: 'settings', archive: 'archive',
};

function navigate(target: NavTarget) {
  const currentTeamId = Number(router.currentRoute.value.params.teamId) || null;
  const teamId = target.teamId ?? (target.mode === 'room' ? currentTeamId : undefined);
  switch (target.mode) {
    case 'dashboard':
      router.push({ name: 'dashboard' });
      break;
    case 'team':
      if (teamId) router.push({ name: 'team', params: { teamId: String(teamId) } });
      break;
    case 'room': {
      // 进入房间需要 teamId；未显式传入时沿用当前路由的 teamId（与旧 activeTeamId 粘滞行为一致）
      const roomId = target.roomId;
      if (teamId && roomId) router.push({ name: 'room', params: { teamId: String(teamId), roomId: String(roomId) } });
      break;
    }
    case 'settings':
      router.push({ name: 'settings' });
      break;
    case 'archive':
      router.push({ name: 'archive' });
      break;
  }
}

export function useViewMode() {
  const mode = computed<ViewMode>(() => routeMode[router.currentRoute.value.name as string] ?? 'dashboard');
  const teamId = computed<number | null>(() => {
    const v = router.currentRoute.value.params.teamId;
    return v ? Number(v) : null;
  });
  const roomId = computed<number | null>(() => {
    const v = router.currentRoute.value.params.roomId;
    return v ? Number(v) : null;
  });
  return { mode, teamId, roomId, navigate };
}
