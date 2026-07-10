"""基于持久化 RoomRun/真实 Agent 活动计算 Run 进度。"""
from __future__ import annotations

from constants import RoomRunStatus, TaskRunStatus
from model.dbModel.gtRoomRun import GtRoomRun
from model.dbModel.gtTaskRun import GtTaskRun


_ACTIVE_ROOM_STATUSES = {RoomRunStatus.QUEUED, RoomRunStatus.DISCUSSING, RoomRunStatus.SYNTHESIZING}
_FINISHED_ROOM_STATUSES = {RoomRunStatus.COMPLETED, RoomRunStatus.FAILED, RoomRunStatus.SKIPPED}

# 阶段基础权重。房间部分只由 RoomRun 的真实百分比贡献，不随时间增长。
_PHASE_BASE = {
    TaskRunStatus.QUEUED: 0,
    TaskRunStatus.PLANNING: 5,
    TaskRunStatus.DISPATCHING: 10,
    TaskRunStatus.DISCUSSING: 15,
    TaskRunStatus.SYNTHESIZING: 70,
    TaskRunStatus.PUBLISHING: 90,
    TaskRunStatus.COMPLETED: 100,
    TaskRunStatus.PARTIAL_FAILED: 100,
    TaskRunStatus.FAILED: 100,
    TaskRunStatus.CANCELLED: 100,
}


def room_progress_for_status(status: RoomRunStatus, *, completed_contributors: int = 0, expected_contributors: int = 0) -> int:
    if status == RoomRunStatus.WAITING:
        return 0
    if status == RoomRunStatus.QUEUED:
        return 10
    if status == RoomRunStatus.DISCUSSING:
        if expected_contributors > 0:
            ratio = min(1.0, completed_contributors / expected_contributors)
            return min(80, 20 + round(ratio * 60))
        return 20
    if status == RoomRunStatus.SYNTHESIZING:
        return 90
    if status in _FINISHED_ROOM_STATUSES:
        return 100
    return 0


def calculate_run_snapshot(run: GtTaskRun, room_runs: list[GtRoomRun]) -> dict:
    total_rooms = len(room_runs)
    active_rooms = sum(1 for room in room_runs if room.status in _ACTIVE_ROOM_STATUSES)
    completed_rooms = sum(1 for room in room_runs if room.status in (RoomRunStatus.COMPLETED, RoomRunStatus.SKIPPED))
    failed_rooms = sum(1 for room in room_runs if room.status == RoomRunStatus.FAILED)
    active_agents = len({room.current_agent_id for room in room_runs if room.current_agent_id is not None and room.status in _ACTIVE_ROOM_STATUSES})
    total_agents = sum(max(0, room.expected_contributors) for room in room_runs)

    status = run.status
    if status in (TaskRunStatus.COMPLETED, TaskRunStatus.PARTIAL_FAILED, TaskRunStatus.FAILED, TaskRunStatus.CANCELLED):
        progress = 100
    elif status == TaskRunStatus.DISCUSSING:
        real_room_progress = (
            sum(room.progress_percent for room in room_runs) / total_rooms
            if total_rooms else 0
        )
        progress = round(15 + real_room_progress * 0.55)
    else:
        progress = _PHASE_BASE.get(status, 0)

    return {
        "progress_percent": max(run.progress_percent, min(100, progress)),
        "total_rooms": total_rooms,
        "active_rooms": active_rooms,
        "completed_rooms": completed_rooms,
        "failed_rooms": failed_rooms,
        "total_agents": total_agents,
        "active_agents": active_agents,
    }
