"""AgentTaskConsumer: 任务管道 — 取任务、执行、状态流转、恢复失败任务。"""
from __future__ import annotations

import asyncio
import logging

from constants import AgentTaskStatus, AgentStatus, AgentActivityType, AgentActivityStatus, MessageBusTopic, AgentTaskType
from model.dbModel.gtAgent import GtAgent
from model.dbModel.gtScheculeTask import GtScheculeTask
from dal.db import gtAgentTaskManager, gtScheculeTaskManager
from service import messageBus, agentActivityService
from service.agentService.agentTurnRunner import AgentTurnRunner
from service.agentService.driver import AgentDriverConfig
from util import assertUtil, asyncUtil

logger = logging.getLogger(__name__)


class AgentTaskConsumer:
    """任务管道：认领 → 执行 → 状态流转。合并了原 AgentTaskExecutor 的职责。

    自行构建 AgentTurnRunner，对外只暴露任务消费接口。
    """

    def __init__(
        self,
        *,
        gt_agent: GtAgent,
        system_prompt: str,
        agent_workdir: str = "",
        driver_config: AgentDriverConfig | None = None,
    ):
        self.gt_agent: GtAgent = gt_agent
        self._turn_runner: AgentTurnRunner = AgentTurnRunner(
            gt_agent=gt_agent,
            system_prompt=system_prompt,
            agent_workdir=agent_workdir,
            driver_config=driver_config,
        )
        self.status: AgentStatus = AgentStatus.IDLE
        self._aio_consumer_task: asyncio.Task | None = None
        self._cancel_requested: bool = False
        self._failure_redrive_handle: asyncio.TimerHandle | None = None

    # 任务执行失败后的自动重驱动延迟（秒）：避免确定性失败任务紧循环重跑（活锁）。
    # 重跑次数仍受 task_data.retry_count 上限（消费循环内 _MAX_RETRY=3）约束。
    _FAILURE_REDRIVE_DELAY_SECONDS = 5.0

    async def _set_status(self, status: AgentStatus, error_message: str | None = None) -> None:
        """统一处理 Agent 状态切换：更新运行时状态、广播事件并记录活动。"""
        if self.status == status:
            return
        self.status = status
        messageBus.publish(MessageBusTopic.AGENT_STATUS_CHANGED, gt_agent=self.gt_agent, status=status)
        await agentActivityService.add_activity(
            gt_agent=self.gt_agent, activity_type=AgentActivityType.AGENT_STATE,
            status=AgentActivityStatus.SUCCEEDED, detail=status.name, error_message=error_message,
        )

    def start(self) -> None:
        """如果没有消费协程在运行，则启动一个。"""
        existing = self._aio_consumer_task
        if existing is not None and not existing.done():
            logger.debug(f"消费协程已在运行，跳过启动: {self.gt_agent.name}(agent_id={self.gt_agent.id})")
            return
        logger.info(f"启动消费协程: {self.gt_agent.name}(agent_id={self.gt_agent.id})")
        task = asyncio.create_task(self.consume())
        # 注册 done_callback 检索异常：fire-and-forget 任务若崩溃，仅会在 GC 时
        # 打印 "Task exception was never retrieved"，不落业务日志（审计 H6）。
        task.add_done_callback(self._on_consumer_done)
        self._aio_consumer_task = task

    def _on_consumer_done(self, task: asyncio.Task) -> None:
        """消费协程结束回调：检索并记录未处理异常，保证故障可观测。"""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error(
                "消费协程异常退出: %s(agent_id=%d), error=%s",
                self.gt_agent.name, self.gt_agent.id, exc, exc_info=exc,
            )

    def stop(self) -> None:
        """停止消费协程。"""
        if self._failure_redrive_handle is not None:
            # 卸载/热更新/关闭路径：取消挂起的失败重驱动，避免已停 Agent 被复活。
            self._failure_redrive_handle.cancel()
            self._failure_redrive_handle = None
        task = self._aio_consumer_task
        self._aio_consumer_task = None
        if task is not None:
            logger.info(f"停止消费协程: {self.gt_agent.name}(agent_id={self.gt_agent.id}), task_done={task.done()}")
        asyncUtil.cancel_task_safely(task)

    def _schedule_retry_after_failure(self) -> None:
        """任务失败后的延迟重驱动：重启消费协程，让 FAILED 任务走内建重试。

        没有这一看门狗时，FAILED 即 break 后该 Agent 不再消费：房间停在
        SCHEDULING 等待一个永远不会发消息的失败 Agent，讨论永久中断（审计 H3）。
        延迟启动避免确定性失败任务紧循环；stop() 会取消挂起的重驱动。
        """
        if self._failure_redrive_handle is not None:
            return  # 已安排，避免堆叠
        loop = asyncio.get_running_loop()
        self._failure_redrive_handle = loop.call_later(
            self._FAILURE_REDRIVE_DELAY_SECONDS, self._redrive_after_failure
        )

    def _redrive_after_failure(self) -> None:
        self._failure_redrive_handle = None
        if self.status != AgentStatus.FAILED:
            # 状态已被外部改变（人工恢复/热更新/人工停止），不再自动重驱动。
            return
        logger.info(f"任务失败后自动重驱动消费: {self.gt_agent.name}(agent_id={self.gt_agent.id})")
        self.start()

    def cancel_current_turn(self) -> bool:
        """人工停止当前 turn。返回 True 表示已发出取消信号，False 表示当前不可取消。"""
        if self.status != AgentStatus.ACTIVE:
            logger.info(f"取消请求被忽略（非 ACTIVE 状态）: {self.gt_agent.name}(agent_id={self.gt_agent.id}), status={self.status.name}")
            return False
        task = self._aio_consumer_task
        if task is None or task.done():
            logger.info(f"取消请求被忽略（消费协程不存在或已结束）: {self.gt_agent.name}(agent_id={self.gt_agent.id})")
            return False
        self._cancel_requested = True
        task.cancel()
        logger.info(f"已发出取消信号: {self.gt_agent.name}(agent_id={self.gt_agent.id})")
        return True

    async def _check_and_schedule_collaboration_tasks(self) -> None:
        """扫描协作任务表，若有待处理任务且无对应 PENDING 调度记录，则自动创建。"""
        agent_task = await gtAgentTaskManager.get_first_active_task(self.gt_agent.id)
        if agent_task is None:
            return

        already_scheduled = await gtScheculeTaskManager.has_pending_collaboration_task(
            self.gt_agent.id, agent_task.id
        )
        if already_scheduled:
            logger.debug(f"协作任务已有 PENDING 调度记录，跳过: {self.gt_agent.name}(agent_id={self.gt_agent.id}), agent_task_id={agent_task.id}")
            return

        logger.info(f"自动创建协作任务调度: {self.gt_agent.name}(agent_id={self.gt_agent.id}), agent_task_id={agent_task.id}, title={agent_task.title!r}")
        await gtScheculeTaskManager.create_task(
            self.gt_agent.id,
            AgentTaskType.TODO_TASK,
            {"agent_task_id": agent_task.id},
        )

    # ─── 消费循环 ─────────────────────────────────────────────
    async def consume(self) -> None:
        """从数据库获取并处理任务，直到没有待处理任务为止。"""
        self._cancel_requested = False  # 防御性重置

        current_consumer = asyncio.current_task()
        if current_consumer is not None and self._aio_consumer_task not in (None, current_consumer):
            existing = self._aio_consumer_task
            assert existing is None or existing.done(), (
                f"消费协程重入: {self.gt_agent.name}(agent_id={self.gt_agent.id}), "
                f"existing_task={id(existing)}, current_task={id(current_consumer)}"
            )

        try:
            await self._consume_tasks(current_consumer)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # 外层兜底：循环体外的 await（_set_status / 取任务 / 收尾续起等）抛出时，
            # 保证 Agent 不会静默卡死——落业务日志、置 FAILED、清理死任务引用（审计 H6）。
            logger.error(
                f"消费循环未捕获异常，Agent 置 FAILED: {self.gt_agent.name}(agent_id={self.gt_agent.id}), error={e}",
                exc_info=True,
            )
            try:
                await self._set_status(AgentStatus.FAILED, str(e))
            except Exception:
                logger.error(f"兜底置 FAILED 状态失败: agent_id={self.gt_agent.id}", exc_info=True)
            if self._aio_consumer_task is current_consumer:
                self._aio_consumer_task = None

    async def _consume_tasks(self, current_consumer: "asyncio.Task | None") -> None:
        """消费循环主体：取任务 → 执行 → 状态流转，直至无待处理任务。"""
        while True:
            await self._set_status(AgentStatus.ACTIVE)
            task = await gtScheculeTaskManager.get_first_unfinish_task(self.gt_agent.id)

            logger.info(f"检查待处理任务: {self.gt_agent.name}(agent_id={self.gt_agent.id})")

            if task is None:
                logger.info(f"无待处理任务，退出消费循环: {self.gt_agent.name}(agent_id={self.gt_agent.id})")
                break

            if task.status not in (AgentTaskStatus.PENDING, AgentTaskStatus.RUNNING, AgentTaskStatus.FAILED):
                logger.info(f"首个未完成任务状态不可消费，退出消费循环: {self.gt_agent.name}(agent_id={self.gt_agent.id}), task_id={task.id}, task_status={task.status}")
                break

            if task.status in (AgentTaskStatus.PENDING, AgentTaskStatus.FAILED):
                # FAILED 任务重试限流：防止确定性失败任务无限重跑（活锁），
                # 每次重跑自增 task_data.retry_count，超过阈值标记为 CANCELLED 终态。
                _MAX_RETRY = 3
                if task.status == AgentTaskStatus.FAILED:
                    retry_count = (task.task_data or {}).get("retry_count", 0)
                    if retry_count >= _MAX_RETRY:
                        logger.warning(
                            "FAILED 任务达到最大重试次数，标记为 CANCELLED: %s(agent_id=%d), task_id=%s, retry=%d/%d",
                            self.gt_agent.name, self.gt_agent.id, task.id, retry_count, _MAX_RETRY,
                        )
                        await gtScheculeTaskManager.update_task_status(
                            task.id, AgentTaskStatus.CANCELLED,
                            error_message=f"达到最大重试次数({_MAX_RETRY})，自动取消",
                        )
                        # 主动告警：任务最终失败（达到最大重试），需人工介入
                        try:
                            from service import alertService
                            alertService.alert_task_failed(
                                self.gt_agent.id, task.id,
                                (task.error_message or "达到最大重试次数自动取消"),
                            )
                        except Exception:
                            pass
                        continue  # 重新取下一个任务
                    # 自增 retry_count 并持久化
                    task_data = dict(task.task_data or {})
                    task_data["retry_count"] = retry_count + 1
                    await gtScheculeTaskManager.update_task_data(task.id, task_data)

                claimed_task = await gtScheculeTaskManager.transition_task_status(task.id, task.status, AgentTaskStatus.RUNNING)
                if claimed_task is None:
                    logger.debug(f"任务认领失败（已被其他消费者抢占），重试: {self.gt_agent.name}(agent_id={self.gt_agent.id}), task_id={task.id}")
                    continue
                if task.status == AgentTaskStatus.FAILED:
                    logger.info(f"重跑 FAILED 任务: {self.gt_agent.name}(agent_id={self.gt_agent.id}), task_id={task.id}")
            else:
                claimed_task = task  # 已经是 RUNNING，直接使用

            logger.info(f"开始执行任务: {self.gt_agent.name}(agent_id={self.gt_agent.id}), task_id={claimed_task.id}")

            try:
                await self._turn_runner.run_task_turn(claimed_task)
            except asyncio.CancelledError:
                # 无论取消来源（人工停止 / hot_reload / 服务关闭），
                # 都先确保 activity 不残留 STARTED 状态。
                try:
                    await agentActivityService.fail_started_activities(
                        self.gt_agent.id, error_message="cancelled",
                    )
                except Exception:
                    logger.warning("fail_started_activities during cancel failed", exc_info=True)

                if not self._cancel_requested:
                    # 非人工停止（hot reload / 服务关闭），保持原有穿透行为
                    raise
                self._cancel_requested = False
                logger.info(f"Agent 任务被人工停止: {self.gt_agent.name}(agent_id={self.gt_agent.id}), task_id={claimed_task.id}")
                await self._turn_runner.handle_cancel_turn()
                await gtScheculeTaskManager.update_task_status(claimed_task.id, AgentTaskStatus.CANCELLED, error_message="cancelled by user")
                await agentActivityService.add_activity(
                    gt_agent=self.gt_agent, activity_type=AgentActivityType.AGENT_STATE,
                    status=AgentActivityStatus.CANCELLED, detail="Turn 被操作者停止",
                )
                break
            except Exception as e:
                logger.error(f"Agent 任务执行失败: {self.gt_agent.name}(agent_id={self.gt_agent.id}), task_id={claimed_task.id}, error={e}")
                await gtScheculeTaskManager.update_task_status(claimed_task.id, AgentTaskStatus.FAILED, error_message=str(e))
                await self._set_status(AgentStatus.FAILED, str(e))
                # 安排延迟自动重驱动，让 FAILED 任务走内建 retry_count 重试，
                # 避免房间永久卡在 SCHEDULING（审计 H3）。
                self._schedule_retry_after_failure()
                break

            logger.info(f"任务执行完成: {self.gt_agent.name}(agent_id={self.gt_agent.id}), task_id={claimed_task.id}")
            await gtScheculeTaskManager.update_task_status(claimed_task.id, AgentTaskStatus.COMPLETED)
            await self._check_and_schedule_collaboration_tasks()

        # 清理逻辑
        if self.status != AgentStatus.FAILED:
            await self._set_status(AgentStatus.IDLE)
            logger.info(f"消费循环结束，状态回到 IDLE: {self.gt_agent.name}(agent_id={self.gt_agent.id})")

        if self._aio_consumer_task is current_consumer:
            self._aio_consumer_task = None
            if self.status != AgentStatus.FAILED:
                has_pending = await gtScheculeTaskManager.has_consumable_task(self.gt_agent.id)
                if has_pending:
                    logger.info(f"Agent 任务收尾时检测到待处理任务，自动续起消费: {self.gt_agent.name}(agent_id={self.gt_agent.id})")
                    self.start()
