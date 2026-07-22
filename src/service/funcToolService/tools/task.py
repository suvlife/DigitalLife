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

from ._common import _require_team_context


async def create_task(
    title: str,
    assignee_id: int,
    description: str = '',
    manager_id: Optional[int] = None,
    priority: str = 'NORMAL',
    parent_id: Optional[int] = None,
    depends_on: Optional[list[int]] = None,
    room_id: Optional[int] = None,
    _context: Optional[ToolCallContext] = None,
) -> dict:
    """创建协作任务。

    Args:
        title: 任务标题
        assignee_id: 执行人 Agent ID
        description: 任务描述，含上下文、约束和交付标准
        manager_id: 完成时若需要他人验收，则设置验收人 Agent ID，不填则无需验收流程；不能与 assignee_id 相同（同一人无需设置验收）
        priority: 优先级，HIGH / NORMAL / LOW，默认 NORMAL
        parent_id: 父任务 ID，用于子任务拆解
        depends_on: 依赖的任务 ID 列表，全部完成后才允许开始
        room_id: 关联房间 ID，便于溯源
    """
    import service.taskService as taskService

    ok, team_id = _require_team_context(_context)
    if not ok:
        return {"success": False, "message": "无法获取团队上下文"}

    return await taskService.create_task(
        team_id=team_id,
        creator_id=_context.agent_id,  # type: ignore[union-attr]
        title=title,
        assignee_id=assignee_id,
        description=description,
        manager_id=manager_id,
        priority=priority,
        parent_id=parent_id,
        depends_on=[int(x) for x in (depends_on or [])],
        room_id=room_id,
    )


async def update_task(
    task_id: int,
    status: str,
    result: str = '',
    block_reason: str = '',
    _context: Optional[ToolCallContext] = None,
) -> dict:
    """更新协作任务状态或附加信息。

    Args:
        task_id: 任务 ID
        status: 新状态（TODO / PENDING / IN_PROGRESS / ON_HOLD / REVIEWING / DONE / CANCELLED）
        result: 完成/提交摘要，在 status=REVIEWING 或 DONE 时填写
        block_reason: 搁置原因，在 status=ON_HOLD 时填写
    """
    import service.taskService as taskService

    ok, team_id = _require_team_context(_context)
    if not ok:
        return {"success": False, "message": "无法获取团队上下文"}

    return await taskService.update_task(
        team_id=team_id,
        caller_id=_context.agent_id,  # type: ignore[union-attr]
        task_id=task_id,
        status=status,
        result=result,
        block_reason=block_reason,
    )


async def get_task(task_id: int, _context: Optional[ToolCallContext] = None) -> dict:
    """查询单个协作任务详情，包含依赖任务状态摘要。

    Args:
        task_id: 任务 ID
    """
    import service.taskService as taskService

    ok, team_id = _require_team_context(_context)
    if not ok:
        return {"success": False, "message": "无法获取团队上下文"}

    return await taskService.get_task(team_id=team_id, task_id=task_id)


async def list_tasks(
    assignee_id: Optional[int] = None,
    manager_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 20,
    _context: Optional[ToolCallContext] = None,
) -> dict:
    """查询协作任务列表。

    Args:
        assignee_id: 按执行人 Agent ID 过滤
        manager_id: 按验收人 Agent ID 过滤
        status: 按状态过滤（TODO / PENDING / IN_PROGRESS / ON_HOLD / REVIEWING / DONE / CANCELLED）
        limit: 最多返回条数，默认 20
    """
    import service.taskService as taskService

    ok, team_id = _require_team_context(_context)
    if not ok:
        return {"success": False, "message": "无法获取团队上下文"}

    return await taskService.list_tasks(
        team_id=team_id,
        assignee_id=assignee_id,
        manager_id=manager_id,
        status=status,
        limit=limit,
    )
