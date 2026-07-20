import { ref, readonly } from 'vue';

export type ViewMode = 'dashboard' | 'team' | 'room' | 'settings' | 'archive';
export type NavTarget = { mode: ViewMode; teamId?: number; roomId?: number };

const current = ref<ViewMode>('dashboard');
const activeTeamId = ref<number | null>(null);
const activeRoomId = ref<number | null>(null);

function navigate(target: NavTarget) {
  current.value = target.mode;
  if (target.teamId !== undefined) activeTeamId.value = target.teamId;
  if (target.roomId !== undefined) activeRoomId.value = target.roomId;
}

export function useViewMode() {
  return {
    mode: readonly(current),
    teamId: readonly(activeTeamId),
    roomId: readonly(activeRoomId),
    navigate,
  };
}
