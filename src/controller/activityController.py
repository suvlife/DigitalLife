"""活动记录查询接口。"""
import logging

from constants import AgentActivityType
from controller.baseController import BaseHandler
from dal.db import gtAgentActivityManager

logger = logging.getLogger(__name__)


class AgentActivitiesHandler(BaseHandler):
    """GET /agents/{agent_id}/activities.json?exclude=AGENT_STATE&limit=50&before_id=123"""

    async def get(self, agent_id: str) -> None:
        agent_id_int = int(agent_id)
        await self._assert_agent_owned(agent_id_int)
        exclude_raw = self.get_arguments("exclude")
        try:
            exclude_types = [AgentActivityType[name.upper()] for name in exclude_raw]
        except KeyError as e:
            self.set_status(400)
            self.return_json({"error_code": "invalid_argument", "error_desc": f"未知的活动类型: {e}"})
            return
        limit = self.get_int_argument("limit", default=100, min_val=1, max_val=100)
        before_id = self.get_int_argument("before_id")
        activities, has_more = await gtAgentActivityManager.list_agent_activities_page(
            agent_id_int,
            limit=limit,
            before_id=before_id,
            exclude_types=exclude_types or None,
        )
        self.return_json({
            "activities": [_serialize_activity(a) for a in activities],
            "pagination": {
                "has_more": has_more,
                "before_id": before_id,
                "limit": limit,
            },
        })


class TeamActivitiesHandler(BaseHandler):
    """GET /teams/{team_id}/activities.json"""

    async def get(self, team_id: str) -> None:
        team_id_int = int(team_id)
        await self._assert_team_owned(team_id_int)
        activities = await gtAgentActivityManager.list_team_activities(team_id_int)
        self.return_json({"activities": [_serialize_activity(a) for a in activities]})


class ActivitiesHandler(BaseHandler):
    """GET /activities.json，必须按 room/team/agent 之一限定资源。"""

    async def get(self) -> None:
        room_id_str = self.get_argument("room_id", default=None)
        team_id_str = self.get_argument("team_id", default=None)
        agent_id_str = self.get_argument("agent_id", default=None)
        if not any((room_id_str, team_id_str, agent_id_str)):
            self.set_status(400)
            self.return_json({"error_code": "resource_required", "error_desc": "必须指定 room_id、team_id 或 agent_id"})
            return

        room_id = self.get_int_argument("room_id")
        team_id = self.get_int_argument("team_id")
        agent_id = self.get_int_argument("agent_id")
        if room_id is not None:
            await self._assert_room_owned(room_id)
        if team_id is not None:
            await self._assert_team_owned(team_id)
        if agent_id is not None:
            await self._assert_agent_owned(agent_id)
        activities = await gtAgentActivityManager.list_activities(
            room_id=room_id, team_id=team_id, agent_id=agent_id
        )
        self.return_json({"activities": [_serialize_activity(a) for a in activities]})


class AgentThinkingTimelineHandler(BaseHandler):
    """GET /agents/{agent_id}/thinking_timeline.json — 返回 Agent 的完整思考时间线。

    按时间顺序返回 LLM_INFER / REASONING / TOOL_CALL / CHAT_REPLY / MESSAGE_RECEIVED / COMPACT 等活动，
    方便前端渲染 Agent 的思考过程。
    """

    async def get(self, agent_id: str) -> None:
        agent_id_int = int(agent_id)
        await self._assert_agent_owned(agent_id_int)
        limit = self.get_int_argument("limit", default=100, min_val=1, max_val=200)
        activities = await gtAgentActivityManager.list_agent_activities(
            agent_id_int,
            limit=limit,
            exclude_types=[AgentActivityType.AGENT_STATE],
        )
        # 按时间正序排列，方便时间线展示
        activities.reverse()
        self.return_json({
            "agent_id": agent_id_int,
            "timeline": [_serialize_activity(a) for a in activities],
        })


def _serialize_activity(activity) -> dict:
    """序列化 AgentActivity，把 metadata 中的关键字段展平，便于前端使用。"""
    data = activity.to_json()
    meta = data.get("metadata") or {}

    # 工具调用：展平工具名、参数、结果
    if activity.activity_type == AgentActivityType.TOOL_CALL:
        data["tool_name"] = meta.get("tool_name")
        data["tool_arguments"] = meta.get("tool_arguments")
        data["tool_result"] = meta.get("tool_result")
        data["command"] = meta.get("command")

    # LLM 推理：展平模型、token、重试状态
    if activity.activity_type == AgentActivityType.LLM_INFER:
        data["model"] = meta.get("model")
        data["estimated_prompt_tokens"] = meta.get("estimated_prompt_tokens")
        data["prompt_tokens"] = meta.get("prompt_tokens")
        data["completion_tokens"] = meta.get("completion_tokens")
        data["total_tokens"] = meta.get("total_tokens")
        data["overflow_retry"] = meta.get("overflow_retry")
        data["retry_attempt"] = meta.get("retry_attempt")
        data["retry_max_attempts"] = meta.get("retry_max_attempts")

    # 消息接收：展平来源消息
    if activity.activity_type == AgentActivityType.MESSAGE_RECEIVED:
        data["messages"] = meta.get("messages")
        data["task_room_id"] = meta.get("task_room_id")

    return data
