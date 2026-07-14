import asyncio
import hmac
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable

import tornado.websocket

import service.messageBus as messageBus
from constants import MessageBusTopic
from util import jsonUtil, configUtil

logger = logging.getLogger(__name__)

_WS_TOPICS = [
    MessageBusTopic.ROOM_MSG_ADDED,
    MessageBusTopic.ROOM_MSG_CHANGED,
    MessageBusTopic.ROOM_STATUS_CHANGED,
    MessageBusTopic.ROOM_ADDED,
    MessageBusTopic.AGENT_STATUS_CHANGED,
    MessageBusTopic.AGENT_ACTIVITY_CHANGED,
    MessageBusTopic.SCHEDULE_STATE_CHANGED,
    MessageBusTopic.TEAM_RELOADED,
    MessageBusTopic.TASK_CREATED,
    MessageBusTopic.TASK_CHANGED,
    MessageBusTopic.USAGE_UPDATED,
    MessageBusTopic.RUN_CREATED,
    MessageBusTopic.RUN_PROGRESS_CHANGED,
    MessageBusTopic.ROOM_RUN_CHANGED,
    MessageBusTopic.FINAL_ANSWER_COMPLETED,
    MessageBusTopic.BLOG_PUBLISH_CHANGED,
]

_RUN_TOPICS = {
    MessageBusTopic.RUN_CREATED,
    MessageBusTopic.RUN_PROGRESS_CHANGED,
    MessageBusTopic.ROOM_RUN_CHANGED,
    MessageBusTopic.FINAL_ANSWER_COMPLETED,
    MessageBusTopic.BLOG_PUBLISH_CHANGED,
}

_EVENT_NAMES = {
    MessageBusTopic.ROOM_MSG_ADDED: "message",
    MessageBusTopic.ROOM_MSG_CHANGED: "message_changed",
    MessageBusTopic.ROOM_STATUS_CHANGED: "room_status",
    MessageBusTopic.ROOM_ADDED: "room_added",
    MessageBusTopic.AGENT_STATUS_CHANGED: "agent_status",
    MessageBusTopic.AGENT_ACTIVITY_CHANGED: "agent_activity",
    MessageBusTopic.SCHEDULE_STATE_CHANGED: "schedule_state",
    MessageBusTopic.TEAM_RELOADED: "team_reloaded",
    MessageBusTopic.TASK_CREATED: "task_created",
    MessageBusTopic.TASK_CHANGED: "task_changed",
    MessageBusTopic.USAGE_UPDATED: "usage_updated",
    MessageBusTopic.RUN_CREATED: "run_created",
    MessageBusTopic.RUN_PROGRESS_CHANGED: "run_progress_changed",
    MessageBusTopic.ROOM_RUN_CHANGED: "room_run_changed",
    MessageBusTopic.FINAL_ANSWER_COMPLETED: "final_answer_completed",
    MessageBusTopic.BLOG_PUBLISH_CHANGED: "blog_publish_changed",
}


@dataclass(frozen=True)
class _EventScope:
    team_id: int | None
    team_found: bool = False
    team_owner_id: int | None = None
    run_id: int | None = None
    run_owner_id: int | None = None
    valid: bool = True


class _ScopeCache:
    """Shared, fail-closed WebSocket tenant-scope cache."""

    ENTITY_TTL_SECONDS = 1.0
    EVENT_TTL_SECONDS = 2.0

    def __init__(self) -> None:
        self._teams: dict[int, tuple[float, tuple[bool, int | None]]] = {}
        self._runs: dict[int, tuple[float, tuple[int, int | None]]] = {}
        self._team_inflight: dict[int, asyncio.Task[tuple[bool, int | None]]] = {}
        self._run_inflight: dict[int, asyncio.Task[tuple[int, int | None] | None]] = {}
        self._events: dict[tuple[int, int], tuple[float, messageBus.EventBusMessage, asyncio.Task[_EventScope]]] = {}

    def clear(self) -> None:
        self._teams.clear()
        self._runs.clear()
        for team_task in self._team_inflight.values():
            if not team_task.done():
                team_task.cancel()
        for run_task in self._run_inflight.values():
            if not run_task.done():
                run_task.cancel()
        self._team_inflight.clear()
        self._run_inflight.clear()
        for _, _, event_task in self._events.values():
            if not event_task.done():
                event_task.cancel()
        self._events.clear()

    def invalidate_team(self, team_id: int) -> None:
        self._teams.pop(team_id, None)
        team_task = self._team_inflight.pop(team_id, None)
        if team_task is not None and not team_task.done():
            team_task.cancel()
        # Ownership/config reloads are rare. Conservatively invalidate runs.
        self._runs.clear()
        for run_task in self._run_inflight.values():
            if not run_task.done():
                run_task.cancel()
        self._run_inflight.clear()

    def invalidate_run(self, run_id: int) -> None:
        self._runs.pop(run_id, None)
        run_task = self._run_inflight.pop(run_id, None)
        if run_task is not None and not run_task.done():
            run_task.cancel()

    async def team(
        self, team_id: int, loader: Callable[[int], Awaitable[tuple[bool, int | None]]]
    ) -> tuple[bool, int | None]:
        now = time.monotonic()
        cached = self._teams.get(team_id)
        if cached is not None and cached[0] > now:
            return cached[1]
        team_task = self._team_inflight.get(team_id)
        if team_task is None:
            team_task = asyncio.ensure_future(loader(team_id))
            self._team_inflight[team_id] = team_task
        try:
            value = await asyncio.shield(team_task)
        finally:
            if team_task.done():
                self._team_inflight.pop(team_id, None)
        # Never cache negative/error results: deny now and retry next event.
        if value[0]:
            self._teams[team_id] = (time.monotonic() + self.ENTITY_TTL_SECONDS, value)
        return value

    async def run(
        self, run_id: int, loader: Callable[[int], Awaitable[tuple[int, int | None] | None]]
    ) -> tuple[int, int | None] | None:
        now = time.monotonic()
        cached = self._runs.get(run_id)
        if cached is not None and cached[0] > now:
            return cached[1]
        run_task = self._run_inflight.get(run_id)
        if run_task is None:
            run_task = asyncio.ensure_future(loader(run_id))
            self._run_inflight[run_id] = run_task
        try:
            value = await asyncio.shield(run_task)
        finally:
            if run_task.done():
                self._run_inflight.pop(run_id, None)
        if value is not None:
            self._runs[run_id] = (time.monotonic() + self.ENTITY_TTL_SECONDS, value)
        return value

    async def event(
        self, msg: messageBus.EventBusMessage, factory: Callable[[], Awaitable[_EventScope]]
    ) -> _EventScope:
        now = time.monotonic()
        key = (msg.event_id if msg.event_id is not None else -1, id(msg))
        cached = self._events.get(key)
        if cached is not None and cached[0] > now and cached[1] is msg:
            return await asyncio.shield(cached[2])
        event_task: asyncio.Task[_EventScope] = asyncio.ensure_future(factory())
        # Retain msg while cached so CPython cannot reuse its id for another event.
        self._events[key] = (now + self.EVENT_TTL_SECONDS, msg, event_task)
        try:
            result = await asyncio.shield(event_task)
        except Exception:
            self._events.pop(key, None)
            raise
        if len(self._events) > 1024:
            self._events = {k: v for k, v in self._events.items() if v[0] > now}
        return result


_SCOPE_CACHE = _ScopeCache()


def _field(value: Any, name: str) -> Any:
    """Read a field from either an ORM object or an already serialized payload."""
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


class EventsWsHandler(tornado.websocket.WebSocketHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._subscribed = False
        self._send_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=512)
        self._sender_task: asyncio.Task | None = None
        self._dropped_events = 0
        # disabled/admin connections are trusted service connections.  A user
        # connection is always scoped to exactly one Cookie session user.
        self._principal_kind: str | None = None
        self._user_id: int | None = None

    def check_origin(self, origin: str) -> bool:
        """WebSocket Origin 校验：仅允许同源连接（公网部署安全防护）。

        审计 H3：默认策略对 loopback Host 放行（本地开发便捷，未鉴权模式下存在
        CSWSH 风险）。当 setting.security.ws_strict_origin=True 时进入严格模式：
        无论 Host 是否为 loopback，都要求 Origin 与 Host 严格同源，缺失 Origin 直接拒绝。
        """
        host = self.request.headers.get("Host", "")
        strict = configUtil.get_app_config().setting.security.ws_strict_origin
        # 非严格模式：开发便捷，loopback 或无 Host 放行
        if not strict:
            if not host or "localhost" in host or "127.0.0.1" in host:
                return True
        elif not host:
            return False
        # 严格模式或生产 Host：校验 Origin 与 Host 一致
        from urllib.parse import urlparse
        try:
            parsed = urlparse(origin)
            origin_host = parsed.netloc or parsed.path
            return bool(origin_host) and origin_host == host
        except Exception:
            return False

    async def open(self):
        auth_config = configUtil.get_app_config().setting.auth
        if not auth_config.enabled:
            self._principal_kind = "disabled"
            logger.info("[ws] WebSocket opened, auth disabled, subscribing events")
            self._subscribe_events()
            return

        # Browser WebSockets naturally carry the login Cookie.  Resolve it
        # before considering the global token so a normal user can never be
        # accidentally upgraded to a service/admin connection.
        user = await self._get_session_user()
        if user is not None:
            from model.dbModel.gtUser import UserRole

            self._user_id = user.id
            self._principal_kind = "admin" if user.role == UserRole.ADMIN else "user"
            logger.info("[ws] Cookie session authenticated: user_id=%s role=%s", user.id, user.role.name)
            self._subscribe_events()
            return

        auth_header = self.request.headers.get("Authorization", "")
        if auth_header:
            if not auth_header.startswith("Bearer ") or not hmac.compare_digest(auth_header[7:], auth_config.token):
                logger.warning("[ws] Bearer auth failed")
                self.close(code=1008, reason="Invalid token")
                return
            # The configured global Bearer token is deliberately not a user
            # identity.  It represents a trusted administrator/service feed.
            self._principal_kind = "admin"
            logger.info("[ws] Bearer service connection authenticated")
            self._subscribe_events()
            return

        # Keep the legacy first-frame auth protocol for service clients that
        # cannot attach an Authorization header.  It has the same admin/service
        # semantics as a Bearer header, never ordinary-user semantics.
        logger.info("[ws] WebSocket opened, waiting for Cookie or service token auth")

    def on_close(self):
        logger.info("[ws] WebSocket closed: code=%s reason=%s queued=%s dropped=%s", self.close_code, self.close_reason, self._send_queue.qsize(), self._dropped_events)
        if self._subscribed:
            messageBus.unsubscribe_many(_WS_TOPICS, self._on_event)
            self._subscribed = False
        if self._sender_task is not None:
            self._sender_task.cancel()
            self._sender_task = None

    def on_message(self, message):
        """处理旧式服务连接的首帧认证消息。"""
        auth_config = configUtil.get_app_config().setting.auth

        # 鉴权未启用或已认证：忽略后续消息，避免重复订阅/身份切换。
        if not auth_config.enabled or self._subscribed:
            return

        try:
            data = json.loads(message)
        except (json.JSONDecodeError, TypeError):
            logger.warning("[ws] Invalid message format")
            self.close(code=1008, reason="Invalid message")
            return

        if data.get("type") != "auth":
            logger.warning("[ws] Expected auth message first")
            self.close(code=1008, reason="Auth required")
            return

        token = data.get("token", "")
        if not isinstance(token, str) or not hmac.compare_digest(token, auth_config.token):
            logger.warning("[ws] Auth failed: wrong token")
            self.close(code=1008, reason="Invalid token")
            return

        self._principal_kind = "admin"
        logger.info("[ws] Service token auth succeeded, subscribing events")
        self._subscribe_events()

    async def _get_session_user(self):
        token = self.get_cookie("dl_session")
        if not token:
            return None
        try:
            from model.dbModel.gtUser import GtSession, GtUser

            session = await GtSession.aio_get_or_none(GtSession.token == token)
            if session is None or session.expires_at < datetime.now():
                return None
            user = await GtUser.aio_get_or_none(GtUser.id == session.user_id)
            if user is None or not user.enabled:
                return None
            return user
        except Exception:
            logger.exception("[ws] Failed to resolve Cookie session")
            return None

    def _subscribe_events(self):
        """订阅消息总线事件（幂等，仅订阅一次）。"""
        if self._subscribed:
            return
        messageBus.subscribe_many(_WS_TOPICS, self._on_event)
        self._subscribed = True
        self._sender_task = asyncio.get_running_loop().create_task(self._sender_loop())

    async def _load_team_owner(self, team_id: int) -> tuple[bool, int | None]:
        try:
            from model.dbModel.gtTeam import GtTeam

            team = await GtTeam.aio_get_or_none(GtTeam.id == team_id, GtTeam.deleted == 0)
        except Exception:
            logger.exception("[ws] Failed to resolve team scope: team_id=%s", team_id)
            return False, None
        if team is None:
            return False, None
        return True, team.owner_user_id

    async def _load_run_scope(self, run_id: int) -> tuple[int, int | None] | None:
        try:
            from model.dbModel.gtTaskRun import GtTaskRun

            run = await GtTaskRun.aio_get_or_none(GtTaskRun.id == run_id)
        except Exception:
            logger.exception("[ws] Failed to resolve run scope: run_id=%s", run_id)
            return None
        scope = None if run is None else (run.team_id, run.owner_user_id)
        return scope

    @staticmethod
    def _payload_team_id(payload: dict[str, Any]) -> int | None:
        direct = payload.get("team_id")
        if isinstance(direct, int):
            return direct
        for key in ("gt_room", "gt_agent", "activity", "task", "room_run", "run"):
            team_id = _field(payload.get(key), "team_id")
            if isinstance(team_id, int):
                return team_id
        return None

    @staticmethod
    def _payload_run_id(payload: dict[str, Any]) -> int | None:
        direct = payload.get("run_id")
        if isinstance(direct, int):
            return direct
        for key in ("run", "room_run"):
            run_id = _field(payload.get(key), "id" if key == "run" else "run_id")
            if isinstance(run_id, int):
                return run_id
        return None

    async def _resolve_event_scope(self, msg: messageBus.EventBusMessage) -> _EventScope:
        payload = msg.payload
        team_id = self._payload_team_id(payload)

        # Reload is the ownership/config invalidation signal. Invalidate before
        # resolving this event so every recipient observes fresh authority.
        if msg.topic == MessageBusTopic.TEAM_RELOADED and team_id is not None:
            _SCOPE_CACHE.invalidate_team(team_id)

        run_id = self._payload_run_id(payload) if msg.topic in _RUN_TOPICS else None
        if run_id is not None and msg.topic == MessageBusTopic.RUN_CREATED:
            _SCOPE_CACHE.invalidate_run(run_id)

        run_owner: int | None = None
        if msg.topic in _RUN_TOPICS:
            if run_id is None:
                return _EventScope(team_id=team_id, valid=False)
            scope = await _SCOPE_CACHE.run(run_id, self._load_run_scope)
            if scope is None:
                return _EventScope(team_id=team_id, run_id=run_id, valid=False)
            run_team_id, run_owner = scope
            payload_owner = _field(payload.get("run"), "owner_user_id")
            if team_id is not None and team_id != run_team_id:
                return _EventScope(team_id=team_id, run_id=run_id, valid=False)
            if payload_owner is not None and payload_owner != run_owner:
                return _EventScope(team_id=run_team_id, run_id=run_id, valid=False)
            team_id = run_team_id

        if team_id is None:
            return _EventScope(team_id=None, run_id=run_id, run_owner_id=run_owner, valid=False)
        found, team_owner = await _SCOPE_CACHE.team(team_id, self._load_team_owner)
        return _EventScope(
            team_id=team_id, team_found=found, team_owner_id=team_owner,
            run_id=run_id, run_owner_id=run_owner, valid=found,
        )

    async def _event_visible(self, msg: messageBus.EventBusMessage) -> bool:
        if self._principal_kind in {"disabled", "admin"}:
            return True
        if self._principal_kind != "user" or self._user_id is None:
            return False
        if msg.topic == MessageBusTopic.SCHEDULE_STATE_CHANGED:
            return True

        try:
            scope = await _SCOPE_CACHE.event(msg, lambda: self._resolve_event_scope(msg))
        except Exception:
            logger.exception("[ws] Failed to resolve event scope: topic=%s", msg.topic.name)
            return False
        if not scope.valid or not scope.team_found:
            return False
        if msg.topic in _RUN_TOPICS and scope.run_owner_id != self._user_id:
            return False
        return scope.team_owner_id is None or scope.team_owner_id == self._user_id

    async def _on_event(self, msg: messageBus.EventBusMessage) -> None:
        if not await self._event_visible(msg):
            logger.debug("[ws] event dropped by tenant scope: topic=%s user_id=%s", msg.topic.name, self._user_id)
            return

        payload = dict(msg.payload)
        payload["event"] = _EVENT_NAMES[msg.topic]
        if msg.event_id is not None:
            payload["event_id"] = msg.event_id
        logger.debug("[ws] event: topic=%s", msg.topic.name)
        serialized = jsonUtil.json_dump(payload)
        try:
            self._send_queue.put_nowait(serialized)
        except asyncio.QueueFull:
            # 活动与用量是高频快照事件，队列繁忙时允许丢弃旧瞬态，关键消息仍尽量入队。
            if msg.topic in {MessageBusTopic.AGENT_ACTIVITY_CHANGED, MessageBusTopic.USAGE_UPDATED, MessageBusTopic.AGENT_STATUS_CHANGED}:
                self._dropped_events += 1
                return
            try:
                self._send_queue.get_nowait()
                self._send_queue.task_done()
                self._send_queue.put_nowait(serialized)
                self._dropped_events += 1
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                self._dropped_events += 1

    async def _sender_loop(self) -> None:
        try:
            while True:
                payload = await self._send_queue.get()
                try:
                    await self.write_message(payload)
                finally:
                    self._send_queue.task_done()
        except asyncio.CancelledError:
            raise
        except tornado.websocket.WebSocketClosedError:
            logger.info("[ws] WebSocket closed, sender stopped")
        except Exception:
            logger.exception("[ws] sender loop failed")
