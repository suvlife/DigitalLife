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

from ._common import _collect_descendant_ids, _find_dept_node, _require_team_context, _serialize_dept_node


async def save_agent(
    name: str,
    role_template_name: str,
    model: str | None = None,
    driver: str = DriverType.TSP.value,
    allow_tools: list[str] | None = None,
    allow_skills: list[str] | None = None,
    i18n: dict | None = None,
    overwrite_existing: bool = False,
    agent_id: int | None = None,
    _context: ToolCallContext = None,
) -> dict:
    """在当前团队中创建或更新成员。

    Args:
        name: 成员名称。作为当前团队内的稳定标识符，建议使用英文小写字母和下划线。
        role_template_name: 要绑定的角色模板名称。工具会按名称解析为 role_template_id。
        model: 可选模型覆盖。留空（None）表示不覆盖模板/系统默认模型。
        driver: 驱动类型。可选值为 native、claude_sdk、tsp。无特别需要（如操作者明确指定）时建议省略，默认使用 tsp。
        allow_tools: 可见工具列表。支持具体工具名（如 "read_file"）或类别语法（如 "Category:Read"）。系统会自动合并类别和具体工具名。基础协作工具（Basic 类别）默认总是开启，无需显式包含。通常情况下此列表留空即可，系统会自动授予 Admin 以外的所有常规类别权限。
                     可用类别：Read, Write, Execute, Admin。注意：Admin 类别属于团队管理功能，严禁分配给除团队根主管以外的普通成员。
        allow_skills: 可见技能列表。指定该成员可以加载的技能名称列表，如 ["frontend-design"]。调用 load_skill 工具时仅允许加载已授权的技能。留空表示不授权任何技能。
        i18n: 可选多语言数据。示例：{"display_name": {"zh-CN": "Alice", "en": "Alice"}}
        overwrite_existing: 是否允许覆盖当前团队中已存在的同名成员。默认 false；为 true 时，若同名成员已存在则执行更新。当传入 agent_id 时，此参数不生效。
        agent_id: 可选成员 ID。传入后按 ID 精确定位成员（忽略 overwrite_existing），此时 name 可用于重命名。
    """
    ok, team_id = _require_team_context(_context)
    if not ok:
        return {"success": False, "message": "当前没有可用的团队上下文。"}

    normalized_name = name.strip()
    if not normalized_name:
        return {"success": False, "message": "成员名称不能为空。"}

    special_agent = SpecialAgent.value_of(normalized_name)
    if special_agent is not None:
        return {"success": False, "message": f"保留成员 {special_agent.name} 不允许通过工具创建或修改。"}

    normalized_role_template_name = role_template_name.strip()
    if not normalized_role_template_name:
        return {"success": False, "message": "角色模板名称不能为空。"}

    driver_type = DriverType.value_of(driver)
    if driver_type is None:
        return {"success": False, "message": "成员 driver 只允许 native、claude_sdk 或 tsp。"}

    error_msg = validate_tool_allow_specs(allow_tools or [])
    if error_msg is not None:
        return {"success": False, "message": error_msg}

    role_template = await gtRoleTemplateManager.get_role_template_by_name(normalized_role_template_name)
    if role_template is None:
        return {"success": False, "message": f"未找到角色模板: {normalized_role_template_name}"}

    if agent_id is not None:
        existing = await gtAgentManager.get_agent_by_id(agent_id)
        if existing is None or existing.team_id != team_id:
            return {"success": False, "message": f"未找到 ID 为 {agent_id} 的成员。"}
    else:
        existing = await gtAgentManager.get_agent(team_id, normalized_name, status=None)
        if existing is not None and overwrite_existing is False:
            return {
                "success": False,
                "message": f"成员 {normalized_name} 已存在；如需覆盖请将 overwrite_existing 设为 true。",
            }

    if existing is not None and existing.team_id == -1:
        return {"success": False, "message": f"保留成员 {existing.name} 不允许通过工具创建或修改。"}

    agent = existing or GtAgent(
        team_id=team_id,
        name=normalized_name,
        employ_status=EmployStatus.OFF_BOARD,
    )
    agent.name = normalized_name
    agent.role_template_id = role_template.id
    agent.model = model or ""
    agent.driver = driver_type
    agent.allow_tools = allow_tools
    agent.allow_skills = allow_skills
    agent.i18n = i18n or {}

    await gtAgentManager.batch_save_agents(team_id, [agent])
    saved = await gtAgentManager.get_agent_by_id(agent.id) if agent.id else await gtAgentManager.get_agent(team_id, normalized_name, status=None)
    if saved is None:
        return {"success": False, "message": f"成员保存失败: {normalized_name}"}

    action = "更新" if existing is not None else "创建"
    payload = saved.to_json()
    payload["driver"] = saved.driver.value
    payload["employ_status"] = saved.employ_status.name
    payload["role_template_name"] = role_template.name
    return {
        "success": True,
        "message": f"已{action}成员 {normalized_name}。配置已保存，需要 reload_team 后生效。",
        "agent": payload,
    }


async def save_dept(
    name: str,
    responsibility: str,
    manager_name: str,
    member_names: list[str],
    parent_name: str | None = None,
    i18n: dict | None = None,
    overwrite_existing: bool = False,
    dept_id: int | None = None,
    _context: ToolCallContext = None,
) -> dict:
    """在当前团队中创建或更新组织（部门）。全量覆盖模式：每次调用会完整替换成员列表。

    Args:
        name: 组织名称。作为当前团队内的稳定标识符，建议使用英文小写字母和下划线。
        responsibility: 组织职责描述。
        manager_name: 负责人成员名。负责人若不在 member_names 中，将自动加入。
        member_names: 成员名称列表。全量覆盖，每次调用将完整替换现有成员列表。
        parent_name: 父组织名称。新建组织时必须指定；不能设置为自身或自身的子组织。更新已有根组织时可省略或传 null 以保持其根节点状态。
        i18n: 可选多语言数据。示例：{"dept_name": {"zh-CN": "研发部", "en": "R&D"}, "responsibility": {"zh-CN": "..."}}
        overwrite_existing: 是否允许覆盖已存在的同名组织。默认 false；为 true 时执行更新。当传入 dept_id 时，此参数不生效。
        dept_id: 可选组织 ID。传入后按 ID 精确定位组织（忽略 overwrite_existing），此时 name 可用于重命名。
    """
    ok, team_id = _require_team_context(_context)
    if not ok:
        return {"success": False, "message": "当前没有可用的团队上下文。"}

    normalized_name = name.strip()
    if not normalized_name:
        return {"success": False, "message": "组织名称不能为空。"}

    # 解析 manager
    normalized_manager = manager_name.strip()
    if not normalized_manager:
        return {"success": False, "message": "负责人名称不能为空。"}

    from dal.db import gtDeptManager
    from service import deptService

    all_agents = await gtAgentManager.get_team_all_agents(team_id)
    name_to_agent: dict[str, Any] = {a.name: a for a in all_agents}

    manager_agent = name_to_agent.get(normalized_manager)
    if manager_agent is None:
        return {"success": False, "message": f"未找到成员: {normalized_manager}"}

    # 解析 member_names → agent_ids，遇到找不到的立即报错
    resolved_ids: list[int] = []
    for mname in member_names:
        mname = mname.strip()
        agent = name_to_agent.get(mname)
        if agent is None:
            return {"success": False, "message": f"未找到成员: {mname}"}
        resolved_ids.append(agent.id)

    # 负责人自动加入成员列表
    if manager_agent.id not in resolved_ids:
        resolved_ids.insert(0, manager_agent.id)

    # 按 ID 或名称定位已有组织
    if dept_id is not None:
        existing = await gtDeptManager.get_dept_by_id(dept_id)
        if existing is None or existing.team_id != team_id:
            return {"success": False, "message": f"未找到 ID 为 {dept_id} 的组织。"}
    else:
        existing = await gtDeptManager.get_dept_by_name(team_id, normalized_name)
        if existing is not None and not overwrite_existing:
            return {
                "success": False,
                "message": f"组织 {normalized_name} 已存在；如需覆盖请将 overwrite_existing 设为 true。",
            }

    # 解析 parent_name → parent_id，并校验循环引用
    parent_id: int | None = None
    if parent_name is not None:
        normalized_parent = parent_name.strip()
        parent_dept = await gtDeptManager.get_dept_by_name(team_id, normalized_parent)
        if parent_dept is None:
            return {"success": False, "message": f"未找到父组织: {normalized_parent}"}
        if existing is not None:
            # 不能把自身设为父组织
            if parent_dept.id == existing.id:
                return {"success": False, "message": "父组织不能设置为当前组织自身。"}
            # 不能把子孙组织设为父组织（会产生环）
            dept_tree = await deptService.get_dept_tree(team_id)
            current_node = _find_dept_node(dept_tree, existing.id)
            if current_node is not None:
                descendant_ids = _collect_descendant_ids(current_node)
                if parent_dept.id in descendant_ids:
                    return {"success": False, "message": f"父组织 {normalized_parent} 是当前组织的子组织，不能形成循环引用。"}
        parent_id = parent_dept.id
    else:
        # parent_name=None：仅允许更新已是根节点的现有组织；新建时必须指定父组织
        if existing is None:
            return {"success": False, "message": "新建组织时必须指定父组织（parent_name）。如需创建根组织，请联系管理员通过组织树编辑器操作。"}
        if existing.parent_id is not None:
            return {"success": False, "message": f"组织 {normalized_name} 当前不是根组织，不能将父组织设为空。"}

    saved = await deptService.upsert_dept(
        team_id=team_id,
        name=normalized_name,
        responsibility=responsibility,
        manager_id=manager_agent.id,
        agent_ids=resolved_ids,
        parent_id=parent_id,
        dept_id=existing.id if existing is not None else None,
        i18n=i18n,
    )

    id_to_name = {a.id: a.name for a in all_agents}
    action = "更新" if existing is not None else "创建"
    return {
        "success": True,
        "message": f"已{action}组织 {normalized_name}。配置已保存，需要 reload_team 后生效。",
        "dept": _serialize_dept_node(saved, id_to_name),
    }


async def delete_dept(
    name: str,
    dept_id: int | None = None,
    recursive: bool = False,
    _context: ToolCallContext = None,
) -> dict:
    """删除当前团队中的指定组织（部门）。

    Args:
        name: 要删除的组织名称。
        dept_id: 可选组织 ID。传入后按 ID 精确定位组织，此时 name 仅用于确认提示。
        recursive: 是否递归删除子组织。默认 false；为 true 时会一并删除所有子孙组织。
    """
    ok, team_id = _require_team_context(_context)
    if not ok:
        return {"success": False, "message": "当前没有可用的团队上下文。"}

    from dal.db import gtDeptManager
    from service import deptService

    if dept_id is not None:
        target = await gtDeptManager.get_dept_by_id(dept_id)
        if target is None or target.team_id != team_id:
            return {"success": False, "message": f"未找到 ID 为 {dept_id} 的组织。"}
    else:
        normalized_name = name.strip()
        if not normalized_name:
            return {"success": False, "message": "组织名称不能为空。"}
        target = await gtDeptManager.get_dept_by_name(team_id, normalized_name)
        if target is None:
            return {"success": False, "message": f"未找到组织: {normalized_name}"}

    try:
        await deptService.delete_dept(team_id, target.id, recursive=recursive)
    except Exception as exc:
        return {"success": False, "message": str(exc)}

    return {
        "success": True,
        "message": f"已删除组织 {target.name}{'（含子组织）' if recursive else ''}。配置已保存，需要 reload_team 后生效。",
    }


async def save_room(
    name: str,
    member_names: list[str],
    initial_topic: str = "",
    max_rounds: int | None = None,
    overwrite_existing: bool = False,
    room_id: int | None = None,
    _context: ToolCallContext = None,
) -> dict:
    """在当前团队中创建或更新房间。房间类型按成员数量自动判断：2人为单聊，3人及以上为群聊。

    Args:
        name: 房间名称。团队内唯一标识，建议使用英文小写字母和下划线。
        member_names: 成员名称列表，至少 2 人。全量覆盖，每次调用将完整替换现有成员列表。
        initial_topic: 房间初始话题，可选。
        max_rounds: 最大轮次。不传则使用系统默认值；<=0 表示不限轮次。
        overwrite_existing: 同名房间已存在时是否允许覆盖。默认 false；为 true 时执行更新。当传入 room_id 时此参数不生效。
        room_id: 可选房间 ID。传入后按 ID 精确定位房间（忽略 overwrite_existing），此时 name 可用于重命名。
    """
    ok, team_id = _require_team_context(_context)
    if not ok:
        return {"success": False, "message": "当前没有可用的团队上下文。"}

    normalized_name = name.strip()
    if not normalized_name:
        return {"success": False, "message": "房间名称不能为空。"}

    if len(member_names) < 2:
        return {"success": False, "message": f"房间成员不足 2 人（当前 {len(member_names)} 人）。"}

    all_agents = await gtAgentManager.get_team_all_agents(team_id)
    name_to_agent: dict[str, Any] = {a.name: a for a in all_agents}

    resolved_ids: list[int] = []
    for mname in member_names:
        mname = mname.strip()
        agent = name_to_agent.get(mname)
        if agent is None:
            return {"success": False, "message": f"未找到成员: {mname}"}
        resolved_ids.append(agent.id)

    # 按 ID 或名称定位已有房间
    if room_id is not None:
        existing = await gtRoomManager.get_room_by_id(room_id)
        if existing is None or existing.team_id != team_id:
            return {"success": False, "message": f"未找到 ID 为 {room_id} 的房间。"}
    else:
        existing = await gtRoomManager.get_room_by_team_and_name(team_id, normalized_name)
        if existing is not None and not overwrite_existing:
            return {
                "success": False,
                "message": f"房间 {normalized_name} 已存在；如需覆盖请将 overwrite_existing 设为 true。",
            }

    try:
        saved = await roomService.upsert_room(
            team_id=team_id,
            name=normalized_name,
            agent_ids=resolved_ids,
            initial_topic=initial_topic,
            max_rounds=max_rounds,
            room_id=existing.id if existing is not None else None,
        )
    except Exception as exc:
        return {"success": False, "message": str(exc)}

    id_to_name = {a.id: a.name for a in all_agents}
    action = "更新" if existing is not None else "创建"
    room_type_label = "单聊" if len(resolved_ids) == 2 else "群聊"
    return {
        "success": True,
        "message": f"已{action}{room_type_label}房间 {saved.name}。配置已保存，需要 reload_team 后生效。",
        "room": {
            "room_id": saved.id,
            "name": saved.name,
            "type": room_type_label,
            "members": [id_to_name.get(aid, str(aid)) for aid in (saved.agent_ids or [])],
            "max_rounds": saved.max_rounds,
            "initial_topic": saved.initial_topic,
        },
    }


async def delete_room(
    name: str,
    room_id: int | None = None,
    _context: ToolCallContext = None,
) -> dict:
    """删除当前团队中的指定房间。DEPT 房间不允许删除；运行中的房间不允许删除。

    Args:
        name: 要删除的房间名称。
        room_id: 可选房间 ID。传入后按 ID 精确定位，此时 name 仅用于确认提示。
    """
    ok, team_id = _require_team_context(_context)
    if not ok:
        return {"success": False, "message": "当前没有可用的团队上下文。"}

    if room_id is not None:
        target = await gtRoomManager.get_room_by_id(room_id)
        if target is None or target.team_id != team_id:
            return {"success": False, "message": f"未找到 ID 为 {room_id} 的房间。"}
    else:
        normalized_name = name.strip()
        if not normalized_name:
            return {"success": False, "message": "房间名称不能为空。"}
        target = await gtRoomManager.get_room_by_team_and_name(team_id, normalized_name)
        if target is None:
            return {"success": False, "message": f"未找到房间: {normalized_name}"}

    try:
        await roomService.delete_managed_room(team_id, target.id)
    except Exception as exc:
        return {"success": False, "message": str(exc)}

    return {
        "success": True,
        "message": f"已删除房间 {target.name}。配置已保存，需要 reload_team 后生效。",
    }
