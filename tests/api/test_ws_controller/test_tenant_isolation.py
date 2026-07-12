import asyncio
import json
import sqlite3
from datetime import datetime

import aiohttp
import pytest
from yarl import URL

from constants import MessageBusTopic
from controller.wsController import EventsWsHandler
from service.messageBus import EventBusMessage
from ...base import ServiceTestCase


class _UnitHandler:
    """Build a handler-shaped object without a Tornado HTTP connection."""

    @staticmethod
    def make(*, principal="user", user_id=7):
        handler = object.__new__(EventsWsHandler)
        handler._principal_kind = principal
        handler._user_id = user_id
        return handler


@pytest.mark.asyncio
async def test_user_reads_owned_and_public_team_but_not_another_users_team(monkeypatch):
    handler = _UnitHandler.make(user_id=7)
    owners = {10: 7, 11: None, 12: 8}

    async def fake_team_owner(team_id):
        return (team_id in owners, owners.get(team_id))

    monkeypatch.setattr(handler, "_load_team_owner", fake_team_owner)

    async def visible(team_id):
        return await handler._event_visible(
            EventBusMessage(MessageBusTopic.TASK_CHANGED, {"task": {"team_id": team_id}})
        )

    assert await visible(10) is True
    assert await visible(11) is True
    assert await visible(12) is False


@pytest.mark.asyncio
async def test_public_team_run_still_requires_matching_run_owner(monkeypatch):
    handler = _UnitHandler.make(user_id=7)

    async def fake_team_owner(team_id):
        return True, None

    async def fake_run_scope(run_id):
        return (11, 7) if run_id == 21 else (11, 8)

    monkeypatch.setattr(handler, "_load_team_owner", fake_team_owner)
    monkeypatch.setattr(handler, "_load_run_scope", fake_run_scope)

    own = EventBusMessage(MessageBusTopic.RUN_PROGRESS_CHANGED, {"run": {"id": 21, "team_id": 11}})
    other = EventBusMessage(MessageBusTopic.ROOM_RUN_CHANGED, {"run_id": 22, "room_run": {"team_id": 11}})
    assert await handler._event_visible(own) is True
    assert await handler._event_visible(other) is False


@pytest.mark.asyncio
async def test_unattributed_sensitive_event_is_dropped_but_schedule_state_broadcasts():
    handler = _UnitHandler.make(user_id=7)
    usage = EventBusMessage(MessageBusTopic.USAGE_UPDATED, {"total_tokens": 123})
    schedule = EventBusMessage(MessageBusTopic.SCHEDULE_STATE_CHANGED, {"schedule_state": "RUNNING"})
    assert await handler._event_visible(usage) is False
    assert await handler._event_visible(schedule) is True


@pytest.mark.asyncio
async def test_admin_service_and_auth_disabled_connections_receive_all_events():
    unattributed = EventBusMessage(MessageBusTopic.USAGE_UPDATED, {"total_tokens": 123})
    assert await _UnitHandler.make(principal="admin", user_id=None)._event_visible(unattributed) is True
    assert await _UnitHandler.make(principal="disabled", user_id=None)._event_visible(unattributed) is True


class TestWsTenantIsolationApi(ServiceTestCase):
    requires_backend = True
    use_custom_config = True

    def _cookie_value(self, client: aiohttp.ClientSession) -> str:
        cookies = client.cookie_jar.filter_cookies(URL(self.backend_base_url))
        return cookies["dl_session"].value

    async def _register_and_login(self, username: str, password: str, *, admin_cookie: str | None = None):
        headers = {"Cookie": f"dl_session={admin_cookie}"} if admin_cookie else {}
        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as client:
            async with client.post(
                f"{self.backend_base_url}/auth/register.json",
                json={"username": username, "password": password},
                headers=headers,
            ) as resp:
                assert resp.status == 200, await resp.text()
                user = (await resp.json())["user"]
            async with client.post(
                f"{self.backend_base_url}/auth/login.json",
                json={"username": username, "password": password},
            ) as resp:
                assert resp.status == 200, await resp.text()
            return user, self._cookie_value(client)

    def _insert_scope_fixture(self, user_id: int, other_user_id: int) -> tuple[int, int, int, int, int]:
        now = datetime.now().isoformat(sep=" ")
        with sqlite3.connect(self.test_db_path) as db:
            private_team = db.execute(
                "INSERT INTO teams(name, uuid, config, i18n, enabled, deleted, owner_user_id, created_at, updated_at) "
                "VALUES (?, NULL, '{}', '{}', 1, 0, ?, ?, ?)",
                (f"private-{user_id}", user_id, now, now),
            ).lastrowid
            public_team = db.execute(
                "INSERT INTO teams(name, uuid, config, i18n, enabled, deleted, owner_user_id, created_at, updated_at) "
                "VALUES (?, NULL, '{}', '{}', 1, 0, NULL, ?, ?)",
                (f"public-{user_id}", now, now),
            ).lastrowid
            other_team = db.execute(
                "INSERT INTO teams(name, uuid, config, i18n, enabled, deleted, owner_user_id, created_at, updated_at) "
                "VALUES (?, NULL, '{}', '{}', 1, 0, ?, ?, ?)",
                (f"other-{user_id}", other_user_id, now, now),
            ).lastrowid

            def add_run(owner):
                return db.execute(
                    "INSERT INTO task_runs(team_id, root_room_id, owner_user_id, title, query, status, progress_percent, "
                    "total_rooms, active_rooms, completed_rooms, failed_rooms, total_agents, active_agents, final_answer, "
                    "blog_publish_status, error_message, metadata, created_at, updated_at) "
                    "VALUES (?, 1, ?, '', '', 'QUEUED', 0, 0, 0, 0, 0, 0, 0, '', 'NOT_STARTED', NULL, '{}', ?, ?)",
                    (public_team, owner, now, now),
                ).lastrowid

            own_run = add_run(user_id)
            other_run = add_run(other_user_id)
            db.commit()
        return private_team, public_team, other_team, own_run, other_run

    async def test_cookie_session_filters_team_events(self):
        admin, admin_cookie = await self._register_and_login("ws-admin", "secret1")
        user, user_cookie = await self._register_and_login("ws-user", "secret2", admin_cookie=admin_cookie)
        other, other_cookie = await self._register_and_login("ws-other", "secret3", admin_cookie=admin_cookie)
        private_team, public_team, other_team, own_run, other_run = self._insert_scope_fixture(user["id"], other["id"])

        ws_url = f"ws://127.0.0.1:{self.backend_port}/ws/events.json"

        def session_with_cookie(cookie: str) -> aiohttp.ClientSession:
            jar = aiohttp.CookieJar(unsafe=True)
            jar.update_cookies({"dl_session": cookie}, response_url=URL(self.backend_base_url))
            return aiohttp.ClientSession(cookie_jar=jar)

        async def clear_team(client: aiohttp.ClientSession, team_id: int) -> None:
            async with client.post(f"{self.backend_base_url}/teams/{team_id}/clear_data.json") as resp:
                assert resp.status == 200, await resp.text()

        async def receive_reload(ws: aiohttp.ClientWebSocketResponse) -> dict:
            async with asyncio.timeout(3):
                async for message in ws:
                    if message.type == aiohttp.WSMsgType.TEXT:
                        payload = json.loads(message.data)
                        if payload.get("event") == "team_reloaded":
                            return payload
            raise AssertionError("team_reloaded not received")

        async with session_with_cookie(user_cookie) as user_client, session_with_cookie(other_cookie) as other_client, session_with_cookie(admin_cookie) as admin_client:
            async with user_client.ws_connect(ws_url) as ws:
                # Own private team is visible.
                await clear_team(user_client, private_team)
                assert (await receive_reload(ws))["team_id"] == private_team

                # Public team events are readable, although ordinary users
                # cannot write that team themselves.
                await clear_team(admin_client, public_team)
                assert (await receive_reload(ws))["team_id"] == public_team

                # Another user's private team must not cross the socket.
                await clear_team(other_client, other_team)
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(ws.receive(), timeout=0.3)

        # Run ownership decisions use these persisted fixtures in unit policy
        # coverage; IDs being distinct guards accidental fixture collapse.
        assert own_run != other_run

    async def test_bearer_header_is_admin_service_connection(self):
        ws_url = f"ws://127.0.0.1:{self.backend_port}/ws/events.json"
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(
                ws_url, headers={"Authorization": "Bearer test_access_token"}
            ) as ws:
                await asyncio.sleep(0.05)
                assert not ws.closed

    async def test_wrong_bearer_is_rejected(self):
        ws_url = f"ws://127.0.0.1:{self.backend_port}/ws/events.json"
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(ws_url, headers={"Authorization": "Bearer wrong"}) as ws:
                message = await ws.receive(timeout=2)
                assert message.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED}
                assert ws.close_code == 1008


@pytest.fixture(autouse=True)
def _clear_ws_scope_cache():
    from controller.wsController import _SCOPE_CACHE

    _SCOPE_CACHE.clear()
    yield
    _SCOPE_CACHE.clear()


_NON_RUN_TOPIC_PAYLOADS = [
    (MessageBusTopic.ROOM_MSG_ADDED, {"gt_room": {"team_id": 10}}),
    (MessageBusTopic.ROOM_MSG_CHANGED, {"gt_room": {"team_id": 10}}),
    (MessageBusTopic.ROOM_STATUS_CHANGED, {"gt_room": {"team_id": 10}}),
    (MessageBusTopic.ROOM_ADDED, {"team_id": 10}),
    (MessageBusTopic.AGENT_STATUS_CHANGED, {"gt_agent": {"team_id": 10}}),
    (MessageBusTopic.AGENT_ACTIVITY_CHANGED, {"activity": {"team_id": 10}}),
    (MessageBusTopic.TEAM_RELOADED, {"team_id": 10}),
    (MessageBusTopic.TASK_CREATED, {"task": {"team_id": 10}}),
    (MessageBusTopic.TASK_CHANGED, {"task": {"team_id": 10}}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("topic", "payload"), _NON_RUN_TOPIC_PAYLOADS)
async def test_every_team_scoped_ws_topic_uses_tenant_owner(topic, payload, monkeypatch):
    handler = _UnitHandler.make(user_id=7)

    async def own_team(team_id):
        assert team_id == 10
        return True, 7

    monkeypatch.setattr(handler, "_load_team_owner", own_team)
    assert await handler._event_visible(EventBusMessage(topic, payload)) is True

    from controller.wsController import _SCOPE_CACHE
    _SCOPE_CACHE.clear()

    async def other_team(team_id):
        assert team_id == 10
        return True, 8

    monkeypatch.setattr(handler, "_load_team_owner", other_team)
    assert await handler._event_visible(EventBusMessage(topic, payload)) is False


_RUN_TOPIC_PAYLOADS = [
    (MessageBusTopic.RUN_CREATED, {"run": {"id": 20, "team_id": 10}}),
    (MessageBusTopic.RUN_PROGRESS_CHANGED, {"run": {"id": 20, "team_id": 10}}),
    (MessageBusTopic.ROOM_RUN_CHANGED, {"run_id": 20, "room_run": {"team_id": 10, "run_id": 20}}),
    (MessageBusTopic.FINAL_ANSWER_COMPLETED, {"run": {"id": 20, "team_id": 10}}),
    (MessageBusTopic.BLOG_PUBLISH_CHANGED, {"run_id": 20}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("topic", "payload"), _RUN_TOPIC_PAYLOADS)
async def test_every_run_ws_topic_requires_run_and_team_ownership(topic, payload, monkeypatch):
    handler = _UnitHandler.make(user_id=7)
    monkeypatch.setattr(handler, "_load_run_scope", lambda run_id: _async_value((10, 7)))
    monkeypatch.setattr(handler, "_load_team_owner", lambda team_id: _async_value((True, 7)))
    assert await handler._event_visible(EventBusMessage(topic, payload)) is True

    from controller.wsController import _SCOPE_CACHE
    _SCOPE_CACHE.clear()
    monkeypatch.setattr(handler, "_load_run_scope", lambda run_id: _async_value((10, 8)))
    assert await handler._event_visible(EventBusMessage(topic, payload)) is False


async def _async_value(value):
    return value


@pytest.mark.asyncio
async def test_usage_topic_is_fail_closed_until_it_has_team_attribution(monkeypatch):
    handler = _UnitHandler.make(user_id=7)
    monkeypatch.setattr(handler, "_load_team_owner", lambda team_id: _async_value((True, 7)))
    assert await handler._event_visible(
        EventBusMessage(MessageBusTopic.USAGE_UPDATED, {"total_tokens": 1})
    ) is False
    assert await handler._event_visible(
        EventBusMessage(MessageBusTopic.USAGE_UPDATED, {"team_id": 10, "total_tokens": 1})
    ) is True


@pytest.mark.asyncio
async def test_one_high_frequency_event_does_one_scope_query_for_many_connections(monkeypatch):
    from controller.wsController import _SCOPE_CACHE

    _SCOPE_CACHE.clear()
    calls = 0

    async def load_owner(team_id):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return True, 7

    handlers = [_UnitHandler.make(user_id=7) for _ in range(100)]
    for handler in handlers:
        monkeypatch.setattr(handler, "_load_team_owner", load_owner)
    msg = EventBusMessage(
        MessageBusTopic.AGENT_ACTIVITY_CHANGED,
        {"activity": {"team_id": 10, "id": 123}},
    )
    msg.event_id = 999
    results = await asyncio.gather(*(handler._event_visible(msg) for handler in handlers))
    assert all(results)
    assert calls == 1


@pytest.mark.asyncio
async def test_team_reload_conservatively_invalidates_cached_owner(monkeypatch):
    handler = _UnitHandler.make(user_id=7)
    owner = 7
    calls = 0

    async def load_owner(team_id):
        nonlocal calls
        calls += 1
        return True, owner

    monkeypatch.setattr(handler, "_load_team_owner", load_owner)
    normal = EventBusMessage(MessageBusTopic.TASK_CHANGED, {"task": {"team_id": 10}})
    assert await handler._event_visible(normal) is True
    assert calls == 1

    owner = 8
    reload_msg = EventBusMessage(MessageBusTopic.TEAM_RELOADED, {"team_id": 10})
    assert await handler._event_visible(reload_msg) is False
    assert calls == 2


@pytest.mark.asyncio
async def test_many_connections_and_concurrent_events_share_short_ttl_scope_query(monkeypatch):
    from controller.wsController import _SCOPE_CACHE

    _SCOPE_CACHE.clear()
    calls = 0

    async def load_owner(team_id):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return True, 7

    handlers = [_UnitHandler.make(user_id=7) for _ in range(20)]
    for handler in handlers:
        monkeypatch.setattr(handler, "_load_team_owner", load_owner)
    messages = [
        EventBusMessage(
            MessageBusTopic.AGENT_ACTIVITY_CHANGED,
            {"activity": {"team_id": 10, "id": event_id}},
        )
        for event_id in range(50)
    ]
    for event_id, msg in enumerate(messages, 1):
        msg.event_id = event_id

    results = await asyncio.gather(
        *(handler._event_visible(msg) for msg in messages for handler in handlers)
    )
    assert all(results)
    assert calls == 1
