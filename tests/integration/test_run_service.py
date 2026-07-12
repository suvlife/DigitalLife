from __future__ import annotations

import os
from datetime import datetime, timezone

from constants import MessageBusTopic, RoomRunStatus, RoomState, RoomType, TaskPriority, TaskRunStatus, TaskStatus
from model.dbModel.gtAgentTask import GtAgentTask
from model.dbModel.gtRoom import GtRoom
from model.dbModel.gtRoomMessage import GtRoomMessage
from model.dbModel.gtRoomRun import GtRoomRun
from model.dbModel.gtTaskRun import GtTaskRun
from dal.db import gtRoomRunManager
from service import messageBus, ormService, runService
from tests.base import ServiceTestCase


class TestRunService(ServiceTestCase):
    @classmethod
    async def async_setup_class(cls):
        db_path = cls._get_test_db_path()
        try:
            os.remove(db_path)
        except FileNotFoundError:
            pass
        await messageBus.startup()
        await ormService.startup(db_path)
        await runService.startup()

    @classmethod
    async def async_teardown_class(cls):
        runService.shutdown()
        await ormService.shutdown()
        await messageBus.shutdown()

    async def _reset(self):
        await GtRoomRun.delete().aio_execute()
        await GtTaskRun.delete().aio_execute()
        await GtRoomMessage.delete().aio_execute()
        await GtRoom.delete().aio_execute()

    async def test_create_snapshot_progress_and_final_answer(self):
        await self._reset()
        room = GtRoom(team_id=11, name="main", type=RoomType.GROUP, agent_ids=[1, 2], tags=[])
        await room.aio_save()
        message = GtRoomMessage(
            room_id=room.id,
            sender_id=-1,
            content="请给出完整研究结论",
            send_time=datetime.now(timezone.utc),
            insert_immediately=False,
            seq=0,
        )
        await message.aio_save()

        run = await runService.create_run_for_user_message(
            team_id=11,
            root_room_id=room.id,
            user_message_id=message.id,
            query=message.content,
            owner_user_id=3,
        )
        duplicate = await runService.create_run_for_user_message(
            team_id=11,
            root_room_id=room.id,
            user_message_id=message.id,
            query=message.content,
            owner_user_id=3,
        )
        assert duplicate.id == run.id

        room_run = (await runService.list_room_runs(run.id))[0]
        assert room_run.status == RoomRunStatus.QUEUED
        assert room_run.expected_contributors == 2

        await runService.set_run_status(run.id, TaskRunStatus.DISCUSSING)
        await runService.update_room_status(
            run_id=run.id,
            room=room,
            status=RoomRunStatus.DISCUSSING,
            current_agent_id=1,
            current_activity="THINKING",
        )
        snapshot = await runService.get_run_snapshot(run.id)
        assert snapshot is not None
        assert snapshot["run"]["status"] == TaskRunStatus.DISCUSSING
        assert snapshot["run"]["active_rooms"] == 1
        assert snapshot["rooms"][0]["current_agent_id"] == 1
        assert snapshot["rooms"][0]["current_activity"] == "THINKING"

        final = await runService.complete_final_answer(
            run_id=run.id,
            final_answer="# 最终结论\n完整内容",
            final_message_id=99,
        )
        assert final.status == TaskRunStatus.COMPLETED
        assert final.progress_percent == 100
        assert final.final_answer.startswith("# 最终结论")

        current = await runService.get_current_run(11, owner_user_id=3)
        assert current is not None
        assert current.id == run.id

    async def test_blog_publish_bridge_persists_status(self):
        await self._reset()
        room = GtRoom(team_id=12, name="main2", type=RoomType.GROUP, agent_ids=[1], tags=[])
        await room.aio_save()
        message = GtRoomMessage(
            room_id=room.id, sender_id=-1, content="问题", send_time=datetime.now(timezone.utc),
            insert_immediately=False, seq=0,
        )
        await message.aio_save()
        run = await runService.create_run_for_user_message(
            team_id=12, root_room_id=room.id, user_message_id=message.id, query="问题",
        )
        updated = await runService.update_blog_publish_status(
            run_id=run.id, status="PUBLISHED", post_id="ghost-1", post_url="https://example.test/post",
        )
        assert updated.blog_publish_status == "PUBLISHED"
        assert updated.blog_post_id == "ghost-1"
        assert updated.blog_post_url == "https://example.test/post"

    async def test_collaboration_task_updates_room_progress_from_real_status(self):
        await self._reset()
        await GtAgentTask.delete().aio_execute()
        room = GtRoom(team_id=13, name="research", type=RoomType.GROUP, agent_ids=[1, 2], tags=[])
        await room.aio_save()
        message = GtRoomMessage(
            room_id=room.id, sender_id=-1, content="研究任务", send_time=datetime.now(timezone.utc),
            insert_immediately=False, seq=0,
        )
        await message.aio_save()
        run = await runService.create_run_for_user_message(
            team_id=13, root_room_id=room.id, user_message_id=message.id, query=message.content,
        )
        task = GtAgentTask(
            team_id=13, title="子任务", description="", assignee_id=1, creator_id=2,
            status=TaskStatus.DONE, priority=TaskPriority.NORMAL, room_id=room.id,
        )
        await task.aio_save()
        await runService._on_collaboration_task_changed(
            messageBus.EventBusMessage(topic=MessageBusTopic.TASK_CHANGED, payload={"task": task})
        )
        room_run = (await runService.list_room_runs(run.id))[0]
        assert room_run.progress_percent == 85
        assert room_run.metadata["task_total"] == 1
        assert room_run.metadata["task_completed"] == 1

    async def test_concurrent_runs_use_explicit_room_association_without_cross_talk(self):
        await self._reset()
        team_id = 14
        root_a = GtRoom(team_id=team_id, name="root-a", type=RoomType.GROUP, agent_ids=[1], tags=[])
        root_b = GtRoom(team_id=team_id, name="root-b", type=RoomType.GROUP, agent_ids=[2], tags=[])
        shared = GtRoom(team_id=team_id, name="shared", type=RoomType.GROUP, agent_ids=[3], tags=[])
        for room in (root_a, root_b, shared):
            await room.aio_save()

        message_a = GtRoomMessage(
            room_id=root_a.id, sender_id=-1, content="任务 A", send_time=datetime.now(timezone.utc),
            insert_immediately=False, seq=0,
        )
        message_b = GtRoomMessage(
            room_id=root_b.id, sender_id=-1, content="任务 B", send_time=datetime.now(timezone.utc),
            insert_immediately=False, seq=0,
        )
        await message_a.aio_save()
        await message_b.aio_save()
        run_a = await runService.create_run_for_user_message(
            team_id=team_id, root_room_id=root_a.id, user_message_id=message_a.id,
            query=message_a.content, owner_user_id=101,
        )
        run_b = await runService.create_run_for_user_message(
            team_id=team_id, root_room_id=root_b.id, user_message_id=message_b.id,
            query=message_b.content, owner_user_id=202,
        )

        # 初始快照只绑定各自真实根房间，不再让两个并发 Run 共享团队全部房间。
        assert {item.room_id for item in await runService.list_room_runs(run_a.id)} == {root_a.id}
        assert {item.room_id for item in await runService.list_room_runs(run_b.id)} == {root_b.id}

        await runService._on_room_status_changed(messageBus.EventBusMessage(
            topic=MessageBusTopic.ROOM_STATUS_CHANGED,
            payload={
                "gt_room": shared, "state": RoomState.SCHEDULING,
                "current_turn_agent_id": 3, "run_id": run_a.id,
            },
        ))
        room_run_a = await gtRoomRunManager.get_room_run(run_a.id, shared.id)
        assert room_run_a is not None
        assert room_run_a.status == RoomRunStatus.DISCUSSING
        assert await gtRoomRunManager.get_room_run(run_b.id, shared.id) is None

        await runService._on_room_status_changed(messageBus.EventBusMessage(
            topic=MessageBusTopic.ROOM_STATUS_CHANGED,
            payload={
                "gt_room": shared, "state": RoomState.SCHEDULING,
                "current_turn_agent_id": 3, "run_id": run_b.id,
            },
        ))
        room_run_b = await gtRoomRunManager.get_room_run(run_b.id, shared.id)
        assert room_run_b is not None
        assert room_run_b.status == RoomRunStatus.DISCUSSING

        # 同一房间现已明确关联两个活动 Run；缺少 run_id 的旧事件必须丢弃，
        # 不能再按团队最新 Run 猜测并串线。
        await runService._on_room_status_changed(messageBus.EventBusMessage(
            topic=MessageBusTopic.ROOM_STATUS_CHANGED,
            payload={"gt_room": shared, "state": RoomState.IDLE, "current_turn_agent_id": None},
        ))
        assert (await gtRoomRunManager.get_room_run(run_a.id, shared.id)).status == RoomRunStatus.DISCUSSING
        assert (await gtRoomRunManager.get_room_run(run_b.id, shared.id)).status == RoomRunStatus.DISCUSSING

    async def test_complete_final_answer_lock_retry_commits_consistent_terminal_state(self, monkeypatch):
        await self._reset()
        room_a = GtRoom(team_id=31, name="root", type=RoomType.GROUP, agent_ids=[1], tags=[])
        room_b = GtRoom(team_id=31, name="research", type=RoomType.GROUP, agent_ids=[2], tags=[])
        await room_a.aio_save()
        await room_b.aio_save()
        message = GtRoomMessage(
            room_id=room_a.id, sender_id=-1, content="可靠完成", send_time=datetime.now(timezone.utc),
            insert_immediately=False, seq=0,
        )
        await message.aio_save()
        run = await runService.create_run_for_user_message(
            team_id=31, root_room_id=room_a.id, user_message_id=message.id, query=message.content,
        )
        await runService.update_room_status(run_id=run.id, room=room_a, status=RoomRunStatus.DISCUSSING)
        await runService.update_room_status(run_id=run.id, room=room_b, status=RoomRunStatus.DISCUSSING)

        original_update = gtRoomRunManager.update_room_run
        locked_once = False

        async def update_with_one_lock(room_run_id, **fields):
            nonlocal locked_once
            if not locked_once and fields.get("status") == RoomRunStatus.COMPLETED:
                locked_once = True
                import peewee
                raise peewee.OperationalError("database is locked")
            return await original_update(room_run_id, **fields)

        monkeypatch.setattr(gtRoomRunManager, "update_room_run", update_with_one_lock)
        monkeypatch.setattr(runService.ormService, "_SQLITE_LOCK_RETRY_DELAYS", (0.001,))
        result = await runService.complete_final_answer(run_id=run.id, final_answer="# 稳定结论")

        assert locked_once is True
        assert result.status == TaskRunStatus.COMPLETED
        persisted = await runService.get_run(run.id)
        assert persisted is not None
        assert persisted.final_answer == "# 稳定结论"
        assert persisted.progress_percent == 100
        room_runs = await runService.list_room_runs(run.id)
        assert len(room_runs) == 2
        assert all(item.status == RoomRunStatus.COMPLETED for item in room_runs)
        assert all(item.progress_percent == 100 for item in room_runs)

    async def test_complete_final_answer_generic_failure_rolls_back_then_reentry_converges(self, monkeypatch):
        await self._reset()
        room_a = GtRoom(team_id=32, name="root", type=RoomType.GROUP, agent_ids=[1], tags=[])
        room_b = GtRoom(team_id=32, name="research", type=RoomType.GROUP, agent_ids=[2], tags=[])
        await room_a.aio_save()
        await room_b.aio_save()
        message = GtRoomMessage(
            room_id=room_a.id, sender_id=-1, content="故障恢复", send_time=datetime.now(timezone.utc),
            insert_immediately=False, seq=0,
        )
        await message.aio_save()
        run = await runService.create_run_for_user_message(
            team_id=32, root_room_id=room_a.id, user_message_id=message.id, query=message.content,
        )
        await runService.update_room_status(run_id=run.id, room=room_a, status=RoomRunStatus.DISCUSSING)
        await runService.update_room_status(run_id=run.id, room=room_b, status=RoomRunStatus.DISCUSSING)

        original_update = gtRoomRunManager.update_room_run
        calls = 0

        async def fail_second_room_update(room_run_id, **fields):
            nonlocal calls
            if fields.get("status") == RoomRunStatus.COMPLETED:
                calls += 1
                if calls == 2:
                    raise RuntimeError("injected terminal transition failure")
            return await original_update(room_run_id, **fields)

        monkeypatch.setattr(gtRoomRunManager, "update_room_run", fail_second_room_update)
        import pytest
        with pytest.raises(RuntimeError, match="injected terminal transition failure"):
            await runService.complete_final_answer(run_id=run.id, final_answer="# 可恢复结论")

        rolled_back = await runService.get_run(run.id)
        assert rolled_back is not None
        assert rolled_back.final_answer == ""
        assert rolled_back.status != TaskRunStatus.COMPLETED
        assert all(
            item.status == RoomRunStatus.DISCUSSING
            for item in await runService.list_room_runs(run.id)
        )

        monkeypatch.setattr(gtRoomRunManager, "update_room_run", original_update)
        completed = await runService.complete_final_answer(run_id=run.id, final_answer="# 可恢复结论")
        assert completed.status == TaskRunStatus.COMPLETED
        assert all(
            item.status == RoomRunStatus.COMPLETED
            for item in await runService.list_room_runs(run.id)
        )
