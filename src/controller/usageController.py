from datetime import datetime, timedelta
from typing import Any

from controller.baseController import BaseHandler
from service import usageService
from util import configUtil


class UsageSummaryHandler(BaseHandler):
    """GET /usage/summary.json — Token 用量统计面板数据"""

    async def get(self) -> None:
        team_id = self.get_argument("team_id", None)
        agent_ids = self.get_argument("agent_ids", None)
        days = self.get_argument("days", "7")

        team_id_int = int(team_id) if team_id is not None else None
        agent_ids_list = [int(x) for x in agent_ids.split(",") if x] if agent_ids else None

        try:
            days_int = max(1, min(int(days), 90))
        except ValueError:
            days_int = 7

        until = datetime.now()
        since = until - timedelta(days=days_int - 1)

        summary = await usageService.get_usage_summary(
            team_id=team_id_int,
            agent_ids=agent_ids_list,
            since=since,
            until=until,
        )
        self.return_json(summary)


class UsageTotalHandler(BaseHandler):
    """GET /usage/total.json — Token 用量汇总"""

    async def get(self) -> None:
        team_id = self.get_argument("team_id", None)
        days = self.get_argument("days", "7")

        team_id_int = int(team_id) if team_id is not None else None

        try:
            days_int = max(1, min(int(days), 90))
        except ValueError:
            days_int = 7

        until = datetime.now()
        since = until - timedelta(days=days_int - 1)

        total = await usageService.get_usage_total(
            team_id=team_id_int,
            since=since,
            until=until,
        )
        self.return_json(total)


class UsageRealtimeHandler(BaseHandler):
    """GET /usage/realtime.json — 当前会话实时 Token 统计"""

    async def get(self) -> None:
        # 最近 1 小时的 token 消耗
        until = datetime.now()
        since = until - timedelta(hours=1)
        total = await usageService.get_usage_total(team_id=None, since=since, until=until)

        # 当前模型
        setting = configUtil.get_app_config().setting
        current_model = ""
        llm_config = setting.current_llm_service
        if llm_config is not None:
            current_model = llm_config.model

        self.return_json({
            "current_model": current_model,
            "session_prompt_tokens": total.get("prompt_tokens", 0),
            "session_completion_tokens": total.get("completion_tokens", 0),
            "session_total_tokens": total.get("total_tokens", 0),
            "session_request_count": total.get("request_count", 0),
        })
