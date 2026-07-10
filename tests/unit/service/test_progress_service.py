from __future__ import annotations

from types import SimpleNamespace

from constants import RoomRunStatus, TaskRunStatus
from service import progressService


def _room(status, progress, agent=None, expected=2, completed=0):
    return SimpleNamespace(
        status=status,
        progress_percent=progress,
        current_agent_id=agent,
        expected_contributors=expected,
        completed_contributors=completed,
    )


def test_room_progress_uses_real_contributor_ratio() -> None:
    assert progressService.room_progress_for_status(RoomRunStatus.WAITING) == 0
    assert progressService.room_progress_for_status(RoomRunStatus.QUEUED) == 10
    assert progressService.room_progress_for_status(
        RoomRunStatus.DISCUSSING, completed_contributors=1, expected_contributors=2,
    ) == 50
    assert progressService.room_progress_for_status(RoomRunStatus.SYNTHESIZING) == 90
    assert progressService.room_progress_for_status(RoomRunStatus.COMPLETED) == 100


def test_run_snapshot_is_derived_from_room_state_not_time() -> None:
    run = SimpleNamespace(status=TaskRunStatus.DISCUSSING, progress_percent=15)
    rooms = [
        _room(RoomRunStatus.COMPLETED, 100),
        _room(RoomRunStatus.DISCUSSING, 50, agent=7),
        _room(RoomRunStatus.FAILED, 100),
    ]
    snapshot = progressService.calculate_run_snapshot(run, rooms)
    assert snapshot["total_rooms"] == 3
    assert snapshot["active_rooms"] == 1
    assert snapshot["completed_rooms"] == 1
    assert snapshot["failed_rooms"] == 1
    assert snapshot["active_agents"] == 1
    assert snapshot["progress_percent"] == 61


def test_terminal_run_is_always_100_percent() -> None:
    run = SimpleNamespace(status=TaskRunStatus.PARTIAL_FAILED, progress_percent=80)
    snapshot = progressService.calculate_run_snapshot(run, [])
    assert snapshot["progress_percent"] == 100
