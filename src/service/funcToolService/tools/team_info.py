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

from ._common import _build_team_agent_name_map, _find_dept_node, _require_team_context, _resolve_agent_name, _serialize_dept_node, _truncate_error_message


async def get_dept_info(dept_id: Optional[int] = None, _context: ToolCallContext = None) -> dict:
    """查询部门信息。不传 dept_id 时返回整个团队部门树，传入时返回指定部门及其子树。

    Args:
        dept_id: 部门 ID，省略时返回整个团队
    """
    ok, team_id = _require_team_context(_context)
    if not ok:
        return {"success": False, "message": "当前没有可用的团队上下文。"}

    from service import deptService

    root = await deptService.get_dept_tree(team_id)
    if root is None:
        return {"success": False, "message": "当前团队还没有部门信息。"}

    target = root if dept_id is None else _find_dept_node(root, dept_id)
    if target is None:
        return {"success": False, "message": f"未找到部门: dept_id={dept_id}"}

    id_to_name = await _build_team_agent_name_map(team_id)
    return {"success": True, "dept": _serialize_dept_node(target, id_to_name)}


async def get_room_info(room_name: Optional[str] = None, _context: ToolCallContext = None) -> dict:
    """查询房间信息。不传 room_name 时返回团队房间列表，传入时返回指定房间详情。

    Args:
        room_name: 房间名称，省略时返回所有房间
    """
    ok, team_id = _require_team_context(_context)
    if not ok:
        return {"success": False, "message": "当前没有可用的团队上下文。"}

    id_to_name = await _build_team_agent_name_map(team_id)

    if room_name is None:
        room_configs = await gtRoomManager.get_rooms_by_team(team_id)
        rooms: list[dict[str, Any]] = []
        for room_config in room_configs:
            runtime_room = roomService.get_room(room_config.id)
            rooms.append({
                "room_name": room_config.name,
                "room_type": room_config.type.name,
                "state": runtime_room.state.name if runtime_room is not None else RoomState.INIT.name,
                "members": [
                    _resolve_agent_name(agent_id, id_to_name)
                    for agent_id in (room_config.agent_ids or [])
                    if agent_id != int(SpecialAgent.SYSTEM.value)
                ],
                "member_count": len([
                    agent_id
                    for agent_id in (room_config.agent_ids or [])
                    if agent_id != int(SpecialAgent.SYSTEM.value)
                ]),
                "tags": list(room_config.tags or []),
            })
        return {"success": True, "rooms": rooms}

    room_config = await gtRoomManager.get_room_by_team_and_name(team_id, room_name)
    if room_config is None:
        return {"success": False, "message": f"未找到房间: {room_name}"}

    runtime_room = roomService.get_room(room_config.id)
    room_dict: dict[str, Any] = {
        "room_name": room_config.name,
        "room_type": room_config.type.name,
        "state": runtime_room.state.name if runtime_room is not None else RoomState.INIT.name,
        "members": [
            _resolve_agent_name(agent_id, id_to_name)
            for agent_id in (room_config.agent_ids or [])
            if agent_id != int(SpecialAgent.SYSTEM.value)
        ],
        "member_count": len([
            agent_id
            for agent_id in (room_config.agent_ids or [])
            if agent_id != int(SpecialAgent.SYSTEM.value)
        ]),
        "current_turn": _resolve_agent_name(runtime_room.get_current_turn_agent_id(), id_to_name) if runtime_room is not None and runtime_room.state == RoomState.SCHEDULING else None,
        "total_messages": len(runtime_room.messages) if runtime_room is not None else 0,
        "tags": list(room_config.tags or []),
    }
    return {"success": True, "room": room_dict}


async def get_agent_info(agent_name: Optional[str] = None, _context: ToolCallContext = None) -> dict:
    """查询 Agent 信息。不传 agent_name 时返回团队成员列表，传入时返回指定成员详情。

    Args:
        agent_name: Agent 名称（内部标识符，即 name 字段，非 display_name），省略时返回所有 Agent
    """
    ok, team_id = _require_team_context(_context)
    if not ok:
        return {"success": False, "message": "当前没有可用的团队上下文。"}

    from service import agentService, deptService
    from dal.db import gtScheculeTaskManager

    team_agents = agentService.get_team_agents(team_id)

    async def _build_agent_dict(agent: Any, *, detail: bool) -> dict[str, Any]:
        agent_id = agent.gt_agent.id
        depts_with_paths: list[tuple[GtDept, str]] = await deptService.get_agent_depts(team_id, agent_id)
        first_task = await gtScheculeTaskManager.get_first_unfinish_task(agent_id) if agent.status == AgentStatus.FAILED else None
        info: dict[str, Any] = {
            "id": agent_id,
            "name": agent.gt_agent.name,
            "display_name": agent.gt_agent.display_name,
            "status": agent.status.name,
            "departments": [
                {
                    "name": path,
                    "position": "manager" if dept.manager_id == agent_id else "member"
                }
                for dept, path in depts_with_paths
            ] if depts_with_paths else None,
        }
        if first_task is not None:
            info["error_summary"] = _truncate_error_message(first_task.error_message)
        if detail:
            info["rooms"] = [
                room.name
                for room in roomService.get_all_rooms()
                if room.team_id == team_id and agent_id in room.get_agent_ids()
            ]
            info["can_wake_up"] = agent.status == AgentStatus.FAILED
        return info

    if agent_name is None:
        agents = [await _build_agent_dict(agent, detail=False) for agent in team_agents]
        return {"success": True, "agents": agents}

    target_agent = next((agent for agent in team_agents if agent.gt_agent.name == agent_name or agent.gt_agent.display_name == agent_name), None)
    if target_agent is None:
        return {"success": False, "message": f"未找到成员: {agent_name}"}

    return {"success": True, "agent": await _build_agent_dict(target_agent, detail=True)}


async def wake_up_agent(agent_name: str, _context: ToolCallContext = None) -> dict:
    """唤醒处于 FAILED 状态的 Agent，使其重新进入调度循环。

    Args:
        agent_name: 要唤醒的 Agent 名称（内部标识符，即 name 字段，非 display_name）
    """
    ok, team_id = _require_team_context(_context)
    if not ok:
        return {"success": False, "message": "当前没有可用的团队上下文。"}

    from service import agentService

    team_agents = agentService.get_team_agents(team_id)
    target_agent = next((agent for agent in team_agents if agent.gt_agent.name == agent_name), None)
    if target_agent is None:
        return {"success": False, "message": f"未找到成员: {agent_name}"}

    if target_agent.status != AgentStatus.FAILED:
        return {"success": False, "message": f"{agent_name} 当前状态为 {target_agent.status.name}，无需唤醒。"}

    target_agent.start_consumer_task()
    return {"success": True, "message": f"已成功唤醒 {agent_name}，该成员将重新进入调度循环。"}


async def reload_team(_context: ToolCallContext = None) -> dict:
    """重载当前团队的运行时。

    注意：该操作会重启当前团队的运行时，可能中断团队内正在执行的任务。
    """
    ok, team_id = _require_team_context(_context)
    if not ok:
        return {"success": False, "message": "当前没有可用的团队上下文。"}

    from service import teamService

    team = await gtTeamManager.get_team_by_id(team_id)
    if team is None:
        return {"success": False, "message": f"未找到团队: team_id={team_id}"}

    # 在独立 task 里执行 hot_reload，使其不受当前 consumer task 取消的影响。
    # hot_reload 内部会调用 stop_team_runtime（取消当前 consumer），
    # 若直接 await，stop_team_runtime 的取消信号会打断自身，导致 restore_team 永远无法执行。
    asyncio.create_task(teamService.hot_reload_team(team.name))

    # 等待被 stop_team_runtime 取消，代码正常情况下不会走到 return。
    # 真正的成功结果由重启后的自中断恢复逻辑（self_interrupt）写入。
    await asyncio.get_event_loop().create_future()

    return {"success": False, "message": f"团队 {team.name} 重载已触发，等待 agent 重启后确认。"}


async def start_chat(
    agent_name: str,
    _context: ToolCallContext = None,
) -> dict:
    """与指定 Agent 发起单聊（私聊）。若两人之间已有房间则直接返回，不重复创建。

    Args:
        agent_name: 要发起对话的目标 Agent 名称（内部标识符，即 name 字段，非 display_name）。
    """
    ok, team_id = _require_team_context(_context)
    if not ok:
        return {"success": False, "message": "当前没有可用的团队上下文。"}

    if _context is None or not _context.agent_id:
        return {"success": False, "message": "无法获取当前 Agent 身份。"}

    normalized = agent_name.strip()
    if not normalized:
        return {"success": False, "message": "目标 Agent 名称不能为空。"}

    all_agents = await gtAgentManager.get_team_all_agents(team_id)
    name_to_agent: dict[str, Any] = {a.name: a for a in all_agents}
    id_to_name: dict[int, str] = {a.id: a.name for a in all_agents}

    target = name_to_agent.get(normalized)
    if target is None:
        return {"success": False, "message": f"未找到成员: {normalized}"}

    self_id = _context.agent_id
    if target.id == self_id:
        return {"success": False, "message": "不能与自己发起单聊。"}

    member_ids = [self_id, target.id]
    member_set = set(member_ids)

    # 若已存在成员相同的房间，直接返回
    existing_rooms = await gtRoomManager.get_rooms_by_team(team_id)
    for existing_room in existing_rooms:
        if set(existing_room.agent_ids or []) == member_set:
            if roomService.get_room(existing_room.id) is None:
                await roomService.load_and_activate_room(existing_room.id)
            return {
                "success": True,
                "message": f"已存在与 {normalized} 的单聊房间 {existing_room.name}，无需重复创建。",
                "room": {
                    "room_id": existing_room.id,
                    "name": existing_room.name,
                    "members": [id_to_name.get(aid, str(aid)) for aid in (existing_room.agent_ids or [])],
                },
                "is_new_created": False,
            }

    # 按名称字母序生成房间名，保证唯一且可预测
    self_name = id_to_name.get(self_id, str(self_id))
    room_name = "_".join(sorted([self_name, normalized]))

    saved = await roomService.create_room(
        team_id=team_id,
        name=room_name,
        agent_ids=member_ids,
    )

    return {
        "success": True,
        "message": f"已创建与 {normalized} 的单聊房间 {saved.name}。",
        "room": {
            "room_id": saved.id,
            "name": saved.name,
            "members": [id_to_name.get(aid, str(aid)) for aid in (saved.agent_ids or [])],
        },
        "is_new_created": True,
    }
