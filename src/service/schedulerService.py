import asyncio
import logging
import time

from service import messageBus
from service.messageBus import EventBusMessage
from service import agentService, roomService as chat_room
from dal.db import gtScheculeTaskManager
from constants import MessageBusTopic, AgentTaskType, SpecialAgent, ScheduleState, RoomState
from model.dbModel.gtAgent import GtAgent
from util import configUtil

logger = logging.getLogger(__name__)

_schedule_state: ScheduleState = ScheduleState.STOPPED
_schedule_not_running_reason: str = ""  # 调度未运行原因，仅在非 RUNNING 状态时可能有值
# per-agent 任务创建锁，防止 check-then-insert 竞态导致重复创建 PENDING 任务
_task_create_locks: dict[int, asyncio.Lock] = {}

# ---- 房间级熔断（审计 M2 / 关联 C2）----------------------------------------
# 防止异常/对抗性房间在单个讨论周期内无限调度轮次、无限占用事件循环与 API 配额。
# 阈值给足冗余，正常多轮讨论不受影响，仅作为调度层最后兜底安全网；房间进入
# IDLE（讨论周期结束）时自动复位。轮次上限从 default_room_max_rounds 放大得到，
# 无需额外配置即可随房间配置伸缩。
_ROOM_TURN_LIMIT_FACTOR = 5
_ROOM_TURN_HARD_MINIMUM = 200
_ROOM_MAX_DURATION_SECONDS = 6 * 60 * 60  # 单个讨论周期最长 6 小时
# 每个房间当前讨论周期内已触发的调度轮次数
_room_turn_counts: dict[int, int] = {}
# 每个房间当前讨论周期首次调度的单调时间戳
_room_cycle_started_at: dict[int, float] = {}
# 已熔断房间集合，避免重复刷日志
_room_tripped: set[int] = set()


def _room_turn_limit() -> int:
    """房间级调度轮次熔断上限，随 default_room_max_rounds 伸缩并留足冗余。"""
    try:
        base = configUtil.get_app_config().setting.default_room_max_rounds or 100
    except Exception:
        base = 100
    return max(_ROOM_TURN_HARD_MINIMUM, base * _ROOM_TURN_LIMIT_FACTOR)


def _reset_room_breaker(room_id: int) -> None:
    """房间讨论周期结束（IDLE）时复位熔断计数，使下一周期重新计量。"""
    _room_turn_counts.pop(room_id, None)
    _room_cycle_started_at.pop(room_id, None)
    _room_tripped.discard(room_id)


def _room_breaker_tripped(room_id: int) -> bool:
    """记录并判断房间是否触发轮次/时长熔断。

    返回 True 表示应停止本轮调度（不再创建轮次任务，不再唤醒 Agent）。
    """
    now = time.monotonic()
    started = _room_cycle_started_at.setdefault(room_id, now)
    count = _room_turn_counts.get(room_id, 0) + 1
    _room_turn_counts[room_id] = count

    limit = _room_turn_limit()
    elapsed = now - started
    if count > limit or elapsed > _ROOM_MAX_DURATION_SECONDS:
        if room_id not in _room_tripped:
            _room_tripped.add(room_id)
            logger.warning(
                "房间级熔断已触发，停止继续调度: room_id=%s turns=%s/%s elapsed=%.0fs/%ss",
                room_id, count, limit, elapsed, _ROOM_MAX_DURATION_SECONDS,
            )
        return True
    return False



def _get_task_create_lock(agent_id: int) -> asyncio.Lock:
    """获取（或创建）指定 agent 的任务创建锁。"""
    if agent_id not in _task_create_locks:
        _task_create_locks[agent_id] = asyncio.Lock()
    return _task_create_locks[agent_id]


def get_schedule_state() -> ScheduleState:
    return _schedule_state


def get_schedule_not_running_reason() -> str:
    """获取调度未运行原因，仅在非 RUNNING 状态时可能有值。"""
    return _schedule_not_running_reason


def _publish_state_change() -> None:
    """发布调度状态变更事件。"""
    messageBus.publish(
        MessageBusTopic.SCHEDULE_STATE_CHANGED,
        schedule_state=_schedule_state.name,
        not_running_reason=_schedule_not_running_reason,
    )


async def startup() -> None:
    """初始化调度器，订阅事件。需在 team 恢复完成后手动调用 start_schedule() 开启调度。"""
    messageBus.subscribe(MessageBusTopic.ROOM_STATUS_CHANGED, _on_room_status_changed)


async def start_schedule() -> None:
    """检查前置条件并尝试开启调度。成功切到 RUNNING 并激活所有 team，否则切到 BLOCKED。"""
    global _schedule_state, _schedule_not_running_reason
    if configUtil.get_app_config().setting.demo_mode.read_only:
        _schedule_state = ScheduleState.BLOCKED
        _schedule_not_running_reason = "演示模式已冻结数据"
        logger.info("调度闸门已阻塞: state=%s, reason=%s", _schedule_state.value, _schedule_not_running_reason)
        _publish_state_change()
        return
    if configUtil.is_initialized():
        _schedule_state = ScheduleState.RUNNING
        _schedule_not_running_reason = ""
        logger.info("调度闸门已开启: state=%s", _schedule_state.value)
        _publish_state_change()
        await start_scheduling(team_name=None)
    else:
        _schedule_state = ScheduleState.BLOCKED
        _schedule_not_running_reason = "未配置大模型服务，请到后台配置大模型服务"
        logger.info("调度闸门已阻塞: state=%s, reason=%s", _schedule_state.value, _schedule_not_running_reason)
        _publish_state_change()


def stop_schedule(reason: str = "") -> None:
    """显式停止调度。

    Args:
        reason: 停止/阻塞原因，可选。
    """
    global _schedule_state, _schedule_not_running_reason
    _schedule_state = ScheduleState.BLOCKED if reason else ScheduleState.STOPPED
    _schedule_not_running_reason = reason
    logger.info("调度闸门已停止/阻塞: state=%s, reason=%s", _schedule_state.value, _schedule_not_running_reason)
    _publish_state_change()


def stop_agent_task(agent_id: int) -> None:
    """停止 Agent 对应的消费 task。"""
    try:
        agent = agentService.get_agent(agent_id)
    except KeyError:
        return
    agent.stop_consumer_task()


async def _on_room_status_changed(msg: EventBusMessage) -> None:
    """订阅 ROOM_STATUS_CHANGED：need_scheduling=True 时创建任务记录并在需要时启动消费协程。"""
    room_id_for_breaker: int = msg.payload["gt_room"].id
    # 房间进入 IDLE 表示当前讨论周期结束，复位熔断计数，下一周期重新计量。
    if msg.payload.get("state") == RoomState.IDLE:
        _reset_room_breaker(room_id_for_breaker)

    if not msg.payload["need_scheduling"]:
        return

    if _schedule_state != ScheduleState.RUNNING:
        return

    agent_id: int = msg.payload["current_turn_agent_id"]
    room_id: int = msg.payload["gt_room"].id

    assert SpecialAgent.value_of(agent_id) is None, \
        f"need_scheduling=True must not be set for special agents: agent_id={agent_id}, room_id={room_id}"

    # 房间级熔断（审计 M2）：超过轮次/时长上限即停止继续调度该房间，
    # 避免异常房间无限推进、烧配额并占满事件循环。
    if _room_breaker_tripped(room_id):
        return

    agent = agentService.get_agent(agent_id)

    # 用 per-agent 锁串行化 check-then-insert，防止并发事件触发重复创建 PENDING 任务
    async with _get_task_create_lock(agent_id):
        # 去重：只检查 PENDING 任务（不检查 FAILED），避免旧 FAILED 任务永久阻塞新任务创建
        if await gtScheculeTaskManager.has_pending_room_task(agent_id, room_id, include_failed=False):
            logger.debug(f"跳过重复任务创建: agent_id={agent_id}, room_id={room_id}")
            agent.start_consumer_task()
            return

        # 创建任务记录
        await gtScheculeTaskManager.create_task(
            agent_id,
            AgentTaskType.ROOM_MESSAGE,
            {"room_id": room_id},
        )

    agent.start_consumer_task()


async def start_scheduling(team_name: str | None = None) -> None:
    """统一开始调度入口：激活/重放房间轮次事件。仅在 RUNNING 状态下执行。"""
    if _schedule_state != ScheduleState.RUNNING:
        logger.info("调度闸门未开启，跳过房间激活: state=%s, team=%s", _schedule_state.value, team_name or "ALL")
        return
    await chat_room.activate_rooms(team_name)
    logger.info("开始调度完成: team=%s", team_name or "ALL")


def shutdown() -> None:
    """清空调度状态。"""
    global _schedule_state, _schedule_not_running_reason
    messageBus.unsubscribe(MessageBusTopic.ROOM_STATUS_CHANGED, _on_room_status_changed)
    for agent in agentService.get_all_agents():
        agent.stop_consumer_task()
    _schedule_state = ScheduleState.STOPPED
    _schedule_not_running_reason = ""
    _room_turn_counts.clear()
    _room_cycle_started_at.clear()
    _room_tripped.clear()
    logger.info("Scheduler 已停止运行")
    for runtime_room in chat_room.get_all_rooms():
        logger.info(f"\n{runtime_room.format_log()}")


def stop_scheduler_team(team_id: int) -> None:
    """停止指定 Team 的所有运行中消费 task。"""
    team_agents = agentService.get_team_agents(team_id)
    for agent in team_agents:
        agent.stop_consumer_task()
    logger.info(f"Team ID={team_id} 的 {len(team_agents)} 个 Agent 已停止")
