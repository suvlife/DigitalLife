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


async def list_role_templates(keywords: list[str] | None = None, _context: ToolCallContext = None) -> dict:
    """查询全部角色模板列表。

    返回精简字段，不包含 soul；display_name 为当前语言下的名称。

    Args:
        keywords: 可选，关键词搜索列表。若提供，则仅返回名称或 soul 中包含这些词的模板。
    """
    if keywords:
        templates = await gtRoleTemplateManager.search_role_templates(keywords)
    else:
        templates = await gtRoleTemplateManager.get_all_role_templates()

    # 转换为 JSON 字典并剔除 soul 以节省 Token
    role_templates = []

    for t in templates:
        data = t.to_json()
        data.pop("soul", None)
        role_templates.append(data)

    return {
        "success": True,
        "role_templates": role_templates,
    }


async def get_role_template(role_name: str, _context: ToolCallContext = None) -> dict:
    """按名称查询单个角色模板详情。

    Args:
        role_name: 角色模板名称
    """
    template = await gtRoleTemplateManager.get_role_template_by_name(role_name.strip())
    if template is None:
        return {"success": False, "message": f"未找到角色模板: {role_name}"}
    return {"success": True, "role_template": template.to_json()}


async def save_role_template(
    name: str,
    type: str,
    soul: str,
    i18n: dict | None = None,
    overwrite_existing: bool = False,
    _context: ToolCallContext = None,
) -> dict:
    """创建或更新角色模板。若指定的 name 不存在则新建（必须设为 USER 类型），若已存在则更新该模板（注意：SYSTEM 类型的内置模板不可通过此工具修改）。

    Args:
        name: 角色模板名称。作为系统唯一标识符，建议使用英文小写字母和下划线。对应的多语言显示名称请通过 i18n 参数设置。
        type: 角色模板类型。SYSTEM 代表系统内置模版（随系统发布，只读）；USER 代表用户自定义模版（可增删改）。通过此工具操作时，请统一指定为 USER。
        soul: 角色模板的核心提示词。应包含角色的身份定位、职责边界和行为准则，是 Agent 运行的"灵魂"。该内容会作为核心指令注入到对应角色的 System Prompt 中。
        i18n: 可选多语言数据。示例：{"display_name": {"zh-CN": "高级写手", "en": "Senior Writer"}}
        overwrite_existing: 是否允许覆盖同名模板。默认 false；为 true 时，若同名模板已存在则执行更新。
    """
    from service import roleTemplateService

    normalized_name = name.strip()
    if not normalized_name:
        return {"success": False, "message": "角色模板名称不能为空。"}

    role_type = RoleTemplateType.value_of(type)
    if role_type is None:
        return {"success": False, "message": "角色模板 type 只允许 SYSTEM 或 USER。"}

    existing = await gtRoleTemplateManager.get_role_template_by_name(normalized_name)
    if existing is None and role_type == RoleTemplateType.SYSTEM:
        return {"success": False, "message": "SYSTEM 角色模板不允许通过工具创建。"}
    if existing is not None and existing.type == RoleTemplateType.SYSTEM:
        return {"success": False, "message": f"SYSTEM 角色模板 {normalized_name} 不允许通过工具修改。"}
    if existing is not None and overwrite_existing is False:
        return {
            "success": False,
            "message": f"角色模板 {normalized_name} 已存在；如需覆盖请将 overwrite_existing 设为 true。",
        }

    saved = await roleTemplateService.save_role_template(
        GtRoleTemplate(
            name=normalized_name,
            soul=soul,
            type=role_type,
            i18n=i18n or {},
        )
    )
    action = "更新" if existing is not None else "创建"
    return {
        "success": True,
        "message": f"已{action}角色模板 {normalized_name}。",
        "role_template": saved.to_json(),
    }


async def delete_role_template(role_name: str, _context: ToolCallContext = None) -> dict:
    """删除指定的角色模板。注意：仅能删除由用户创建（USER 类型）且当前未被任何成员使用的模板。

    Args:
        role_name: 要删除的角色模板名称
    """

    normalized_name = role_name.strip()
    template = await gtRoleTemplateManager.get_role_template_by_name(normalized_name)
    if template is None:
        return {"success": False, "message": f"未找到角色模板: {role_name}"}
    if template.type == RoleTemplateType.SYSTEM:
        return {"success": False, "message": f"SYSTEM 角色模板 {template.name} 不允许通过工具删除。"}

    referenced_agents = list(
        await GtAgent.select()
        .where(GtAgent.role_template_id == template.id)
        .order_by(GtAgent.team_id, GtAgent.name)
        .aio_execute()
    )
    if referenced_agents:
        agents = [{"name": agent.name, "team_id": agent.team_id} for agent in referenced_agents]
        agent_names = ", ".join(agent["name"] for agent in agents)
        return {
            "success": False,
            "message": f"角色模板 {template.name} 正在被以下 Agent 使用，无法删除: {agent_names}",
            "agents": agents,
        }

    await gtRoleTemplateManager.delete_role_template(template.id)
    return {
        "success": True,
        "message": f"已删除角色模板 {template.name}。",
        "role_template": {"id": template.id, "name": template.name},
    }
