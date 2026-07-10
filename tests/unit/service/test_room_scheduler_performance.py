from constants import RoomType
from model.dbModel.gtRoom import GtRoom
from service.roomService.roomScheduler import RoomScheduler


def _scheduler(*, max_rounds=10, tags=None):
    room = GtRoom(
        id=1,
        team_id=1,
        name="room",
        type=RoomType.GROUP,
        initial_topic="",
        max_rounds=max_rounds,
        agent_ids=[1, 2, 3],
        agent_read_index={},
        tags=tags or [],
        i18n={},
    )
    return RoomScheduler(room_key="room", gt_room=room, get_read_index=lambda: {})


def test_round_robin_keeps_configured_rounds():
    scheduler = _scheduler(max_rounds=4, tags=["STRATEGY:ROUND_ROBIN"])
    assert scheduler.discussion_strategy() == "ROUND_ROBIN"
    assert scheduler._effective_max_rounds() == 4


def test_fast_consensus_safely_caps_to_one_round():
    scheduler = _scheduler(max_rounds=30, tags=["STRATEGY:FAST_CONSENSUS"])
    assert scheduler.discussion_strategy() == "FAST_CONSENSUS"
    assert scheduler._effective_max_rounds() == 1


def test_parallel_opinions_safely_caps_to_one_round():
    scheduler = _scheduler(max_rounds=3, tags=["STRATEGY:PARALLEL_OPINIONS"])
    assert scheduler.discussion_strategy() == "PARALLEL_OPINIONS"
    assert scheduler._effective_max_rounds() == 1


def test_unknown_strategy_falls_back_without_changing_rounds():
    scheduler = _scheduler(max_rounds=3, tags=["STRATEGY:UNKNOWN"])
    assert scheduler.discussion_strategy() == "ROUND_ROBIN"
    assert scheduler._effective_max_rounds() == 3
