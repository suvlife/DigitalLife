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


async def send_chat_msg(room_name: str, msg: str, _context: ToolCallContext = None) -> dict:
    """向聊天窗口发送消息

    Args:
        room_name: 要发送消息的窗口名称
        msg: 要发送的消息
    """
    if _context is None:
        logger.warning("发送消息失败，聊天室上下文未设置")
        return {"success": False, "message": "当前没有可用的房间上下文。"}

    logger.info(f"发送消息: sender_id={_context.agent_id}, room={room_name}, msg={msg}")

    try:
        room_config = await gtRoomManager.get_room_by_team_and_name(_context.team_id, room_name)
        target_room = roomService.get_room(room_config.id) if room_config is not None else None
    except Exception:
        try:
            team_rooms = await gtRoomManager.get_rooms_by_team(_context.team_id)
            room_config = next((room for room in team_rooms if room.name == room_name), None)
            target_room = roomService.get_room(room_config.id) if room_config else None
        except Exception:
            target_room = None

    if target_room is None:
        logger.warning(f"send_chat_msg: 目标房间不存在 room={room_name} team_id={_context.team_id}")
        return {"success": False, "message": f"目标房间不存在: {room_name} (team_id={_context.team_id})"}

    if not target_room.can_post_message(_context.agent_id):
        logger.warning(
            "send_chat_msg: 发言者不在目标房间 agents 中 sender_id=%s room=%s team_id=%s agents=%s",
            _context.agent_id,
            room_name,
            _context.team_id,
            target_room.get_agent_ids(),
        )
        return {"success": False, "message": f"你不在房间 {target_room.name} 中，发送失败。"}

    await target_room.add_message(_context.agent_id, msg)

    if _context.chat_room is not None and target_room.room_id == _context.chat_room.room_id:
        return {"success": True, "message": "消息已送达房间。如果你还有其他工具需要调用，请继续；如果本轮操作已全部完成，请调用 finish_action 结束行动。"}

    return {"success": True, "message": f"消息已送达 {target_room.name}。如果你还有其他工具需要调用，请继续；如果本轮操作已全部完成，请调用 finish_action 结束行动。"}


async def dispatch_to_room(room_name: str, question: str, _context: ToolCallContext = None) -> dict:
    """向指定研究室派发讨论问题（组织者专用，无需是房间成员）。

    以系统身份向目标研究室发送派发消息并激活该室的讨论调度。
    Root Leader 可用此工具将用户问题拆分后分发给各研究室并行讨论，
    各研究室讨论完成后结果会回流到主问策室供综合研判。

    Args:
        room_name: 目标研究室名称
        question: 要派发给该研究室讨论的问题/子任务
    """
    if _context is None:
        return {"success": False, "message": "当前没有可用的团队上下文。"}

    # 查找目标房间
    try:
        room_config = await gtRoomManager.get_room_by_team_and_name(_context.team_id, room_name)
    except Exception:
        room_config = None
    if room_config is None:
        try:
            team_rooms = await gtRoomManager.get_rooms_by_team(_context.team_id)
            room_config = next((r for r in team_rooms if r.name == room_name), None)
        except Exception:
            room_config = None
    if room_config is None:
        return {"success": False, "message": f"目标房间不存在: {room_name}"}

    # 获取或加载房间（研究室可能未在内存中）
    target_room = roomService.get_room(room_config.id)
    if target_room is None:
        target_room = await roomService.load_and_activate_room(room_config.id)
    if target_room is None:
        return {"success": False, "message": f"房间 {room_name} 无法加载"}

    # 以 SYSTEM 身份发送派发消息（can_post_message 允许 SYSTEM，触发 handle_message 激活调度）
    dispatch_content = f"【组织者派发】{question}"
    await target_room.add_message(int(SpecialAgent.SYSTEM.value), dispatch_content)
    logger.info(f"dispatch_to_room: agent={_context.agent_id} -> room={room_name}(id={room_config.id}), question={question[:80]}")
    return {
        "success": True,
        "message": f"已向 {room_name} 派发讨论问题，该室大师将开始研讨。完成后结果将回流至主问策室。",
        "room_id": room_config.id,
    }


async def submit_conclusion(
    conclusion: str,
    confidence: str = "中等",
    _context: ToolCallContext = None,
) -> dict:
    """提交辩论综合结论。仅限房间内的综合研判角色（如 CIO/综合研判官）使用。

    调用后房间将进入"结论已达成"状态，调度器在当前轮次结束后直接转入 IDLE，
    不再继续推进下一轮。请在各流派大师充分辩论后调用此工具。

    Args:
        conclusion: 综合结论内容。应包含：方向判断、关键依据、各方共识与分歧、风险提示、建议行动。
        confidence: 结论置信度，可选值为"高"、"中等"、"低"。默认"中等"。
    """
    if _context is None or _context.chat_room is None:
        return {"success": False, "message": "当前没有激活的房间上下文。"}

    room = _context.chat_room

    # 防御性校验：房间必须在调度中才能提交结论
    if room.state != RoomState.SCHEDULING:
        return {"success": False, "message": "房间当前未在调度中，无法提交综合结论。"}

    # 校验调用者是否为 root leader（综合研判角色）
    from service import agentService
    agent = agentService.get_agent_or_none(_context.agent_id)
    if agent is None or not agent.is_root_leader:
        return {"success": False, "message": "只有团队最高负责人（综合研判角色）才能提交综合结论。"}

    # 设置结论标志，调度器在当前轮次结束后停止
    room.scheduler._conclusion_submitted = True

    # 将结论作为消息发送到房间
    conclusion_msg = f"【综合结论】（置信度：{confidence}）\n{conclusion}"
    await room.add_message(_context.agent_id, conclusion_msg)

    logger.info(f"综合结论已提交: agent_id={_context.agent_id}, room={room.name}, confidence={confidence}")

    # 最终答案由 runService 在消息持久化后统一入队发布，避免工具层重复触发。

    return {
        "success": True,
        "message": "综合结论已提交并广播到房间。当前辩论轮次将在你结束行动后终止。请调用 finish_action 结束本轮行动。",
    }


async def finish_action(_context: ToolCallContext = None, confirm_no_need_talk: bool = False) -> dict:
    """结束行动。当你完成所有发言和工具调用后（或者无需行动时），必须调用此工具来把行动机会让给下一位成员。

    参数：
    - confirm_no_need_talk (bool)：确认本轮无需在收到消息通知的房间发言。
      - 本轮未在对应房间发言时：若确认不需要发言，须设置为 true 才能结束行动。
      - 本轮已在对应房间发言时：不得设置此参数，直接调用 finish_action 即可。
      ⚠️ 注意：直接输出（非 send_chat_msg）的文字用户看不到，不算发言。"""
    if _context is None:
        logger.warning("结束行动失败，上下文未设置")
        return {"success": False, "message": "当前没有激活的上下文。"}

    task_type = _context.schedule_task.task_type if _context.schedule_task is not None else AgentTaskType.ROOM_MESSAGE

    if task_type == AgentTaskType.TODO_TASK:
        agent_task_id = _context.schedule_task.task_data.get("agent_task_id")
        agent_task = await gtAgentTaskManager.get_task(agent_task_id) if agent_task_id else None
        if agent_task is not None:
            is_assignee = agent_task.assignee_id == _context.agent_id
            is_manager  = agent_task.manager_id == _context.agent_id

            if is_assignee and agent_task.status in (TaskStatus.TODO, TaskStatus.IN_PROGRESS):
                logger.warning(f"finish_action 被拒绝，协作任务仍为 {agent_task.status.value}: agent_id={_context.agent_id}, agent_task_id={agent_task_id}")
                return {
                    "success": False,
                    "message": f"""\
finish 失败，你负责执行的任务【{agent_task.title}】状态仍为 {agent_task.status.value}，尚未处理完毕。

请先完成任务处理：
- 若已完成，请调用 `update_task` 将状态改为 REVIEWING（有验收人时）或 DONE 并填写结果。
- 若需暂缓（本轮无法完成），请调用 `update_task` 将状态改为 ON_HOLD。
- 若需取消，请调用 `update_task` 将状态改为 CANCELLED。
完成后再调用 finish_action。""",
                }
            elif is_manager and agent_task.status == TaskStatus.REVIEWING:
                logger.warning(f"finish_action 被拒绝，协作任务待验收: agent_id={_context.agent_id}, agent_task_id={agent_task_id}")
                return {
                    "success": False,
                    "message": f"""\
finish 失败，你负责验收的任务【{agent_task.title}】依然为 reviewing状态，未完成审核。

请先完成验收：
- 验收通过：请调用 `update_task` 将状态改为 DONE。
- 打回重做：请调用 `update_task` 将状态改为 IN_PROGRESS。
完成后再调用 finish_action。""",
                }
        logger.info(f"Agent 结束协作任务行动: agent_id={_context.agent_id}")
        return {"success": True, "message": "已结束了本轮行动."}

    elif task_type == AgentTaskType.ROOM_MESSAGE:
        if _context.chat_room is None:
            logger.warning("结束行动失败，聊天室上下文未设置")
            return {"success": False, "message": "当前没有激活的房间上下文。"}

        if confirm_no_need_talk and _context.chat_room.current_turn_has_content:
            return {
                "success": False,
                "message": "finish_action 失败：你本轮已经通过 send_chat_msg 发过消息了，不需要设置 confirm_no_need_talk=true。请直接调用 finish_action（不带任何参数）结束行动。",
            }

        if not confirm_no_need_talk and not _context.chat_room.current_turn_has_content:
            room_name = _context.chat_room.name
            return {
                "success": False,
                "message": f"""\
finish 失败，你本次行动中，未在收到消息的房间【{room_name}】发言。

1. 如果你忘记发言（或者是不小心用直接输出替代了向房间发言），那么请调用 send_chat_msg 发送消息。
2. 如果你确认不需要发言，请设置 confirm_no_need_talk=true 重新调用 finish_action。""",
            }

        logger.info(f"Agent 结束行动: agent_id={_context.agent_id}")
        ok = await _context.chat_room.handle_finish_request(_context.agent_id)

        if not ok:
            current_id = _context.chat_room.get_current_turn_agent_id()
            logger.warning(f"finish_turn 被房间拒绝（发言位不匹配），但仍视为行动结束: agent_id={_context.agent_id}, current_turn_id={current_id}, room={_context.chat_room.key}")

        return {"success": True, "message": "已结束了本轮行动."}



# ---------------------------------------------------------------------------
# Task 工具：协作任务管理（委托给 taskService）
# ---------------------------------------------------------------------------
