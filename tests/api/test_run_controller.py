from __future__ import annotations

import asyncio
import json

import aiohttp
import async_timeout

from ..base import ServiceTestCase


class TestRunController(ServiceTestCase):
    requires_backend = True
    requires_mock_llm = True

    async def _team_and_room(self, session: aiohttp.ClientSession) -> tuple[int, int]:
        async with session.get(f"{self.backend_base_url}/teams/list.json") as resp:
            teams = (await resp.json())["teams"]
        team_id = next(team["id"] for team in teams if team["name"] == "e2e")
        async with session.get(f"{self.backend_base_url}/rooms/list.json?team_id={team_id}") as resp:
            rooms = (await resp.json())["rooms"]
        room_id = next(room["gt_room"]["id"] for room in rooms if room["gt_room"]["name"] == "general")
        return team_id, room_id

    async def test_submit_creates_restorable_run_and_ws_events(self):
        finish = {"tool_calls": [{"name": "finish_action", "arguments": {"confirm_no_need_talk": True}}]}
        for _ in range(8):
            self.set_mock_response(finish)

        async with aiohttp.ClientSession() as session:
            team_id, room_id = await self._team_and_room(session)
            async with session.ws_connect(f"ws://127.0.0.1:{self.backend_port}/ws/events.json") as ws:
                async with session.post(
                    f"{self.backend_base_url}/rooms/{room_id}/messages/send.json",
                    json={"content": "测试 Run 进度恢复"},
                ) as resp:
                    assert resp.status == 200

                seen = set()
                run_id = None
                async with async_timeout.timeout(8):
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            continue
                        payload = json.loads(msg.data)
                        event = payload.get("event")
                        if event in {"run_created", "run_progress_changed", "room_run_changed"}:
                            seen.add(event)
                            assert isinstance(payload.get("event_id"), int)
                        if event == "run_created":
                            run_id = payload["run"]["id"]
                        if run_id is not None and {"run_created", "room_run_changed"} <= seen:
                            break

                assert run_id is not None
                assert "run_created" in seen
                assert "room_run_changed" in seen

            async with session.get(f"{self.backend_base_url}/runs/current.json?team_id={team_id}") as resp:
                assert resp.status == 200
                current = await resp.json()
            assert current["run"]["id"] == run_id
            assert current["run"]["query"] == "测试 Run 进度恢复"
            assert current["rooms"]

            for path in (
                f"/runs/{run_id}.json",
                f"/runs/{run_id}/rooms.json",
                f"/runs/{run_id}/timeline.json",
                f"/runs/{run_id}/final_answer.json",
            ):
                async with session.get(self.backend_base_url + path) as resp:
                    assert resp.status == 200, path
