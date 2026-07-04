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
]


class EventsWsHandler(tornado.websocket.WebSocketHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._subscribed = False
        # 保留后台发送任务的强引用，避免被 GC 中途回收，
        # 并在连接关闭时统一取消未完成的发送任务。
        self._pending_send_tasks: set[asyncio.Task] = set()

    def open(self):
        auth_config = configUtil.get_app_config().setting.auth
        if auth_config.enabled:
            logger.info("[ws] WebSocket opened, waiting for auth")
            return

        logger.info("[ws] WebSocket opened, auth disabled, subscribing events")
        self._subscribe_events()

    def on_close(self):
        logger.info("[ws] WebSocket closed")
        if self._subscribed:
            messageBus.unsubscribe_many(_WS_TOPICS, self._on_event)
            self._subscribed = False
        # 取消所有未完成的发送任务，避免向已关闭连接写入
        for task in self._pending_send_tasks:
            task.cancel()
        self._pending_send_tasks.clear()

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
        logger.info(f"[ws] event: topic={msg.topic.name}, payload={payload}")
        task = asyncio.get_running_loop().create_task(self._send(jsonUtil.json_dump(payload)))
        self._pending_send_tasks.add(task)
        task.add_done_callback(self._pending_send_tasks.discard)

    async def _send(self, payload: str) -> None:
        try:
            logger.debug(f"[ws] sending: {payload[:100]}...")
            self.write_message(payload)
            logger.debug(f"[ws] sent successfully")
        except tornado.websocket.WebSocketClosedError:
            logger.info("[ws] WebSocket closed, skipping message")
        except Exception as e:
            logger.error(f"[ws] error sending message: {e}")
