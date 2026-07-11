import asyncio
import hmac
import json
import logging
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


class EventsWsHandler(tornado.websocket.WebSocketHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._subscribed = False
        self._send_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=512)
        self._sender_task: asyncio.Task | None = None
        self._dropped_events = 0

    def check_origin(self, origin: str) -> bool:
        """WebSocket Origin 校验：仅允许同源连接（公网部署安全防护）。"""
        # 开发模式（无 Host 头或 localhost）允许所有来源
        host = self.request.headers.get("Host", "")
        if not host or "localhost" in host or "127.0.0.1" in host:
            return True
        # 生产模式：校验 Origin 与 Host 一致
        from urllib.parse import urlparse
        try:
            parsed = urlparse(origin)
            origin_host = parsed.netloc or parsed.path
            return origin_host == host
        except Exception:
            return False

    def open(self):
        auth_config = configUtil.get_app_config().setting.auth
        if auth_config.enabled:
            logger.info("[ws] WebSocket opened, waiting for auth")
            return

        logger.info("[ws] WebSocket opened, auth disabled, subscribing events")
        self._subscribe_events()

    def on_close(self):
        logger.info("[ws] WebSocket closed: code=%s reason=%s queued=%s dropped=%s", self.close_code, self.close_reason, self._send_queue.qsize(), self._dropped_events)
        if self._subscribed:
            messageBus.unsubscribe_many(_WS_TOPICS, self._on_event)
            self._subscribed = False
        if self._sender_task is not None:
            self._sender_task.cancel()
            self._sender_task = None

    def on_message(self, message):
        """处理客户端消息（认证消息）。"""
        auth_config = configUtil.get_app_config().setting.auth

        # 鉴权未启用：忽略后续消息，避免重复订阅
        if not auth_config.enabled:
            return

        # 解析消息
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            logger.warning("[ws] Invalid message format")
            self.close(code=1008, reason="Invalid message")
            return

        # 检查是否为认证消息
        if data.get("type") != "auth":
            logger.warning("[ws] Expected auth message first")
            self.close(code=1008, reason="Auth required")
            return

        # 验证 token（常量时间比较，防时序攻击）
        token = data.get("token", "")
        if not hmac.compare_digest(token, auth_config.token):
            logger.warning("[ws] Auth failed: wrong token")
            self.close(code=1008, reason="Invalid token")
            return

        # 认证成功，订阅事件
        logger.info("[ws] Auth succeeded, subscribing events")
        self._subscribe_events()

    def _subscribe_events(self):
        """订阅消息总线事件（幂等，仅订阅一次）。"""
        if self._subscribed:
            return
        messageBus.subscribe_many(_WS_TOPICS, self._on_event)
        self._subscribed = True
        self._sender_task = asyncio.get_running_loop().create_task(self._sender_loop())

    def _on_event(self, msg: messageBus.EventBusMessage) -> None:
        payload = dict(msg.payload)
        if msg.topic == MessageBusTopic.ROOM_MSG_ADDED:
            payload["event"] = "message"
        if msg.topic == MessageBusTopic.ROOM_MSG_CHANGED:
            payload["event"] = "message_changed"
        if msg.topic == MessageBusTopic.ROOM_STATUS_CHANGED:
            payload["event"] = "room_status"
        if msg.topic == MessageBusTopic.ROOM_ADDED:
            payload["event"] = "room_added"
        if msg.topic == MessageBusTopic.AGENT_STATUS_CHANGED:
            payload["event"] = "agent_status"
        if msg.topic == MessageBusTopic.AGENT_ACTIVITY_CHANGED:
            payload["event"] = "agent_activity"
        if msg.topic == MessageBusTopic.SCHEDULE_STATE_CHANGED:
            payload["event"] = "schedule_state"
        if msg.topic == MessageBusTopic.TEAM_RELOADED:
            payload["event"] = "team_reloaded"
        if msg.topic == MessageBusTopic.TASK_CREATED:
            payload["event"] = "task_created"
        if msg.topic == MessageBusTopic.TASK_CHANGED:
            payload["event"] = "task_changed"
        if msg.topic == MessageBusTopic.USAGE_UPDATED:
            payload["event"] = "usage_updated"
        if msg.topic == MessageBusTopic.RUN_CREATED:
            payload["event"] = "run_created"
        if msg.topic == MessageBusTopic.RUN_PROGRESS_CHANGED:
            payload["event"] = "run_progress_changed"
        if msg.topic == MessageBusTopic.ROOM_RUN_CHANGED:
            payload["event"] = "room_run_changed"
        if msg.topic == MessageBusTopic.FINAL_ANSWER_COMPLETED:
            payload["event"] = "final_answer_completed"
        if msg.topic == MessageBusTopic.BLOG_PUBLISH_CHANGED:
            payload["event"] = "blog_publish_changed"
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
