from __future__ import annotations

from tornado.web import Finish

from controller.baseController import BaseHandler
from service import runService
from model.dbModel.gtTaskRun import GtTaskRun


class _RunOwnedHandler(BaseHandler):
    async def _load_owned_run(self, run_id: int) -> GtTaskRun:
        run = await runService.get_run(run_id)
        if run is None:
            self.set_status(404)
            self.return_json({"error_code": "run_not_found", "error_desc": "运行实例不存在"})
            raise Finish()
        await self._assert_team_owned(run.team_id)
        return run


class CurrentRunHandler(BaseHandler):
    """GET /runs/current.json?team_id=..."""

    async def get(self) -> None:
        team_id = self.get_int_argument("team_id", min_val=1)
        if team_id is None:
            self.set_status(400)
            self.return_json({"error_code": "invalid_argument", "error_desc": "team_id 必填"})
            return
        await self._assert_team_owned(team_id)
        run = await runService.get_current_run(team_id, owner_user_id=self._current_user_id())
        if run is None:
            self.return_json({"run": None, "rooms": []})
            return
        snapshot = await runService.get_run_snapshot(run.id)
        self.return_json(snapshot)


class RunListHandler(BaseHandler):
    """GET /runs/list.json?team_id=...&limit=50"""

    async def get(self) -> None:
        team_id = self.get_int_argument("team_id", min_val=1)
        if team_id is None:
            self.set_status(400)
            self.return_json({"error_code": "invalid_argument", "error_desc": "team_id 必填"})
            return
        await self._assert_team_owned(team_id)
        limit = self.get_int_argument("limit", default=50, min_val=1, max_val=200) or 50
        runs = await runService.list_runs(team_id, limit=limit, owner_user_id=self._current_user_id())
        self.return_json({"runs": runs})


class RunDetailHandler(_RunOwnedHandler):
    """GET /runs/{id}.json"""

    async def get(self, run_id_str: str) -> None:
        run_id = int(run_id_str)
        await self._load_owned_run(run_id)
        snapshot = await runService.get_run_snapshot(run_id)
        self.return_json(snapshot)


class RunRoomsHandler(_RunOwnedHandler):
    """GET /runs/{id}/rooms.json"""

    async def get(self, run_id_str: str) -> None:
        run_id = int(run_id_str)
        await self._load_owned_run(run_id)
        rooms = await runService.list_room_runs(run_id)
        self.return_json({"run_id": run_id, "rooms": rooms})


class RunTimelineHandler(_RunOwnedHandler):
    """GET /runs/{id}/timeline.json"""

    async def get(self, run_id_str: str) -> None:
        run_id = int(run_id_str)
        await self._load_owned_run(run_id)
        limit = self.get_int_argument("limit", default=200, min_val=1, max_val=500) or 200
        timeline = await runService.get_timeline(run_id, limit=limit)
        self.return_json({"run_id": run_id, "timeline": timeline})


class RunFinalAnswerHandler(_RunOwnedHandler):
    """GET /runs/{id}/final_answer.json"""

    async def get(self, run_id_str: str) -> None:
        run_id = int(run_id_str)
        run = await self._load_owned_run(run_id)
        self.return_json({
            "run_id": run_id,
            "status": run.status,
            "final_message_id": run.final_message_id,
            "final_answer": run.final_answer,
            "blog_publish_status": run.blog_publish_status,
            "blog_post_url": run.blog_post_url,
        })
