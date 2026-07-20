from datetime import datetime, timedelta
from controller.baseController import BaseHandler
from service import usageService
from util import configUtil


class UsageSummaryHandler(BaseHandler):
    """GET /usage/summary.json — Token 用量统计面板数据"""

    async def get(self) -> None:
        team_id_int = self.get_int_argument("team_id")
        agent_ids = self.get_argument("agent_ids", None)
        days = self.get_argument("days", "7")

        try:
            agent_ids_list = [int(x) for x in agent_ids.split(",") if x] if agent_ids else None
        except ValueError:
            self.set_status(400)
            self.return_json({"error_code": "invalid_argument", "error_desc": "参数 agent_ids 必须是逗号分隔的整数"})
            return
        if team_id_int is None and not agent_ids_list:
            self.set_status(400)
            self.return_json({"error_code": "resource_required", "error_desc": "必须指定 team_id 或 agent_ids"})
            return
        if team_id_int is not None:
            await self._assert_team_owned(team_id_int)
        for agent_id in agent_ids_list or []:
            await self._assert_agent_owned(agent_id)

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
        team_id_int = self.get_int_argument("team_id")
        days = self.get_argument("days", "7")

        if team_id_int is None:
            self.set_status(400)
            self.return_json({"error_code": "resource_required", "error_desc": "必须指定 team_id"})
            return
        await self._assert_team_owned(team_id_int)

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
        team_id_int = self.get_int_argument("team_id")
        if team_id_int is not None:
            await self._assert_team_owned(team_id_int)
        else:
            self._assert_admin()

        # 最近 1 小时的 token 消耗
        until = datetime.now()
        since = until - timedelta(hours=1)
        total = await usageService.get_usage_total(team_id=team_id_int, since=since, until=until)

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
