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


async def load_skill(
    skill_name: str,
    _context: Optional[ToolCallContext] = None,
) -> dict:
    """加载指定技能的完整信息，包含详细操作指引和文件清单。

    Args:
        skill_name: 要加载的技能名称。仅能加载当前 Agent 已授权的技能，未授权的技能会被拒绝。
    """
    if not _context or not _context.agent_id:
        return {"success": False, "message": "无法获取当前 Agent 上下文"}

    agent = await gtAgentManager.get_agent_by_id(_context.agent_id)
    if agent is None:
        return {"success": False, "message": f"未找到 Agent（ID: {_context.agent_id}）"}

    product_skills = {"document-studio", "spreadsheet-studio", "guizang-ppt-skill"}
    allow_skills = set(agent.allow_skills or []) | product_skills

    if skill_name not in allow_skills:
        return {"success": False, "message": f"技能 {skill_name} 未对当前 Agent 开放"}

    skill_info = skillService.get_skill(skill_name)
    if skill_info is None:
        return {"success": False, "message": f"技能 {skill_name} 不存在"}

    content = skill_info.content
    if not content:
        return {"success": False, "message": f"读取技能 {skill_name} 内容失败"}

    files = skill_info.files

    return {
        "success": True,
        "skill_name": skill_info.name,
        "skill_dir": skill_info.skill_dir,
        "is_builtin": skill_info.is_builtin,
        "description": skill_info.description,
        "content": content,
        "files": files,
    }
