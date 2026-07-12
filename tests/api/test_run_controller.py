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


class TestRunControllerTenantIsolation(ServiceTestCase):
    requires_backend = True
    use_custom_config = True

    async def _register_and_login(self, username: str, password: str, *, admin_cookie: str | None = None):
        from yarl import URL
        headers = {"Cookie": f"dl_session={admin_cookie}"} if admin_cookie else {}
        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as client:
            async with client.post(
                f"{self.backend_base_url}/auth/register.json",
                json={"username": username, "password": password}, headers=headers,
            ) as resp:
                assert resp.status == 200, await resp.text()
                user = (await resp.json())["user"]
            async with client.post(
                f"{self.backend_base_url}/auth/login.json",
                json={"username": username, "password": password},
            ) as resp:
                assert resp.status == 200, await resp.text()
            cookie = client.cookie_jar.filter_cookies(URL(self.backend_base_url))["dl_session"].value
            return user, cookie

    def _insert_public_run(self, owner_user_id: int) -> int:
        import sqlite3
        from datetime import datetime

        now = datetime.now().isoformat(sep=" ")
        with sqlite3.connect(self.test_db_path) as db:
            team_id = db.execute(
                "INSERT INTO teams(name, uuid, config, i18n, enabled, deleted, owner_user_id, created_at, updated_at) "
                "VALUES (?, NULL, '{}', '{}', 1, 0, NULL, ?, ?)",
                (f"public-run-{owner_user_id}", now, now),
            ).lastrowid
            run_id = db.execute(
                "INSERT INTO task_runs(team_id, root_room_id, owner_user_id, title, query, status, progress_percent, "
                "total_rooms, active_rooms, completed_rooms, failed_rooms, total_agents, active_agents, final_answer, "
                "blog_publish_status, error_message, metadata, created_at, updated_at) "
                "VALUES (?, 1, ?, 'private run', 'secret query', 'QUEUED', 0, 0, 0, 0, 0, 0, 0, "
                "'secret answer', 'NOT_STARTED', NULL, '{}', ?, ?)",
                (team_id, owner_user_id, now, now),
            ).lastrowid
            db.commit()
        return int(run_id)

    async def test_public_team_run_rest_endpoints_reject_another_user(self):
        from yarl import URL

        admin, admin_cookie = await self._register_and_login("run-admin", "secret1")
        owner, owner_cookie = await self._register_and_login("run-owner", "secret2", admin_cookie=admin_cookie)
        _, other_cookie = await self._register_and_login("run-other", "secret3", admin_cookie=admin_cookie)
        run_id = self._insert_public_run(owner["id"])

        def session(cookie: str) -> aiohttp.ClientSession:
            jar = aiohttp.CookieJar(unsafe=True)
            jar.update_cookies({"dl_session": cookie}, response_url=URL(self.backend_base_url))
            return aiohttp.ClientSession(cookie_jar=jar)

        paths = (
            f"/runs/{run_id}.json",
            f"/runs/{run_id}/rooms.json",
            f"/runs/{run_id}/timeline.json",
            f"/runs/{run_id}/final_answer.json",
        )
        async with session(other_cookie) as other_client:
            for path in paths:
                async with other_client.get(self.backend_base_url + path) as resp:
                    assert resp.status == 403, (path, await resp.text())

        async with session(owner_cookie) as owner_client, session(admin_cookie) as admin_client:
            for client in (owner_client, admin_client):
                for path in paths:
                    async with client.get(self.backend_base_url + path) as resp:
                        assert resp.status == 200, (path, await resp.text())
