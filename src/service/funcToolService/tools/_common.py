from __future__ import annotations
from typing import Any, Optional
import asyncio
import datetime
import logging
from zoneinfo import ZoneInfo

from constants import AgentStatus, AgentTaskType, DriverType, EmployStatus, RoleTemplateType, RoomState, SpecialAgent, TaskStatus
from dal.db import gtAgentManager, gtRoomManager, gtRoleTemplateManager, gtTeamManager, gtAgentTaskManager
from model.dbModel.gtAgent import GtAgent
from model.dbModel.gtDept import GtDept
from model.dbModel.gtRoleTemplate import GtRoleTemplate
from service.roomService import ToolCallContext
import service.roomService as roomService
import service.skillService as skillService
from service.agentService.toolRegistry import validate_tool_allow_specs
from util import configUtil, i18nUtil

logger = logging.getLogger(__name__)


def _require_team_context(_context: ToolCallContext | None) -> tuple[bool, int]:
    if _context is None or _context.team_id <= 0:
        return False, 0
    return True, _context.team_id


def _resolve_agent_name(agent_id: int, id_to_name: dict[int, str]) -> str:
    if agent_id == int(SpecialAgent.SYSTEM.value):
        return SpecialAgent.SYSTEM.name
    if agent_id == int(SpecialAgent.OPERATOR.value):
        return SpecialAgent.OPERATOR.name
    return id_to_name.get(agent_id, f"unknown({agent_id})")


def _find_dept_node(node: GtDept | None, dept_id: int) -> GtDept | None:
    if node is None:
        return None
    if node.id == dept_id:
        return node
    for child in node.children:
        found = _find_dept_node(child, dept_id)
        if found is not None:
            return found
    return None


def _serialize_dept_node(node: GtDept, id_to_name: dict[int, str]) -> dict[str, Any]:
    lang = configUtil.get_language()
    dept_name = i18nUtil.extract_i18n_str(
        node.i18n.get("dept_name") if node.i18n else None,
        default=node.name,
        lang=lang,
    ) or node.name
    responsibility = i18nUtil.extract_i18n_str(
        node.i18n.get("responsibility") if node.i18n else None,
        default=node.responsibility,
        lang=lang,
    ) or node.responsibility
    members = [_resolve_agent_name(agent_id, id_to_name) for agent_id in node.agent_ids]
    return {
        "dept_id": node.id,
        "dept_name": dept_name,
        "dept_responsibility": responsibility,
        "manager": _resolve_agent_name(node.manager_id, id_to_name),
        "members": members,
        "member_count": len(members),
        "children": [_serialize_dept_node(child, id_to_name) for child in node.children],
    }


async def _build_team_agent_name_map(team_id: int) -> dict[int, str]:
    # 临时优先复用运行态 Agent，拿不到时再回退 DB，避免工具在测试/恢复场景下名称缺失。
    try:
        from service import agentService

        team_agents = agentService.get_team_agents(team_id)
        if team_agents:
            return {agent.gt_agent.id: agent.gt_agent.name for agent in team_agents}
    except Exception:
        logger.debug("build team agent name map from runtime failed, fallback to db", exc_info=True)

    gt_agents = await gtAgentManager.get_team_all_agents(team_id)
    return {agent.id: agent.name for agent in gt_agents}


def _collect_descendant_ids(node: GtDept) -> set[int]:
    """递归收集节点的所有后代 dept id（不含自身）。"""
    ids: set[int] = set()
    for child in node.children:
        if child.id is not None:
            ids.add(child.id)
        ids |= _collect_descendant_ids(child)
    return ids


def _truncate_error_message(message: str | None, limit: int = 100) -> str:
    if not message:
        return ""
    if len(message) <= limit:
        return message
    return message[:limit].rstrip() + "..."


def get_time(timezone: Optional[str] = None) -> dict:
    """获取当前时间

    Args:
        timezone: 可选的时区名称，如 "Asia/Shanghai"，默认使用本地时区
    """
    if timezone:
        try:
            tz = ZoneInfo(timezone)
            now = datetime.datetime.now(tz)
            return {"success": True, "message": f"当前时间（时区 {timezone}）: {now.strftime('%Y-%m-%d %H:%M:%S')}"}
        except Exception:
            return {"success": False, "message": f"未知时区: {timezone}"}
    else:
        now = datetime.datetime.now()
        return {"success": True, "message": f"当前本地时间: {now.strftime('%Y-%m-%d %H:%M:%S')}"}
