from __future__ import annotations

import os
from datetime import datetime, timezone

from constants import MessageBusTopic, RoomRunStatus, RoomType, TaskPriority, TaskRunStatus, TaskStatus
from model.dbModel.gtAgentTask import GtAgentTask
from model.dbModel.gtRoom import GtRoom
from model.dbModel.gtRoomMessage import GtRoomMessage
from model.dbModel.gtRoomRun import GtRoomRun
from model.dbModel.gtTaskRun import GtTaskRun
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
