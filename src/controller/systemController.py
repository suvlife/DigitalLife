import asyncio
import logging
import os

from controller.baseController import BaseHandler
from constants import ScheduleState
from service import ormService, schedulerService, updateService
from util import configUtil
from version import __version__

logger = logging.getLogger(__name__)


class SystemStatusHandler(BaseHandler):
    """GET /system/status.json — 返回系统运行状态（含初始化状态）。"""

    async def get(self):
        initialized = configUtil.is_initialized()
        schedule_state = schedulerService.get_schedule_state()
        not_running_reason = schedulerService.get_schedule_not_running_reason()
        setting = configUtil.get_app_config().setting
        demo_mode = setting.demo_mode

        # 安全策略：未鉴权时仅返回初始化所需最小集，
        # auth_enabled/demo_mode/development_mode 等安全态势仅在已鉴权后返回。
        is_authed = self._is_authed()
        response = {
            "initialized": initialized,
            "language": configUtil.get_language(),
            "version": __version__,
            # 客户端必须知道是否需要认证，布尔值本身不属于敏感信息。
            "auth_enabled": setting.auth.enabled,
        }
        if is_authed or not setting.auth.enabled:
            # 已鉴权或鉴权未启用时返回完整状态
            response["schedule_state"] = schedule_state
            response["not_running_reason"] = not_running_reason
            response["demo_mode"] = demo_mode.enabled
            response["freeze_data"] = demo_mode.read_only
            response["read_only"] = demo_mode.read_only
            response["hide_sensitive_info"] = demo_mode.hide_sensitive
            response["development_mode"] = setting.development_mode
            response["auto_check_update"] = setting.auto_check_update
        if initialized:
            response["default_llm_server"] = setting.default_llm_server
        else:
            response["message"] = "当前未配置大模型服务"

        # 运行时健康探针（仅管理员可见）：DB 连通、调度、进程指标。
        # 供负载均衡/监控系统做存活与就绪判断，未鉴权不暴露内部细节。
        if self._is_admin():
            response["health"] = self._build_health(schedule_state)

        self.return_json(response)

    @staticmethod
    def _build_health(schedule_state) -> dict:
        """构建运行时健康信息（admin-only）。

        包含 DB 连通性、调度状态、进程运行时长与内存占用，供监控/告警系统消费。
        """
        import time
        db_ready = False
        try:
            db_ready = ormService.is_ready()
        except Exception:
            db_ready = False

        memory_mb = None
        try:
            import resource
            # ru_maxrss 单位：macOS 为字节，Linux 为 KB
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            memory_mb = round(rss / (1024 * 1024) if rss > 10 ** 8 else rss / 1024, 1)
        except Exception:
            memory_mb = None

        return {
            "db_ready": db_ready,
            "schedule_state": getattr(schedule_state, "value", str(schedule_state)),
            "uptime_seconds": round(time.monotonic(), 1),
            "memory_rss_mb": memory_mb,
        }


class SystemScheduleResumeHandler(BaseHandler):
    """POST /system/schedule/resume.json — 尝试恢复调度。"""

    async def post(self):
        self._assert_admin()
        await schedulerService.start_schedule()
        schedule_state = schedulerService.get_schedule_state()
        not_running_reason = schedulerService.get_schedule_not_running_reason()
        if schedule_state != ScheduleState.RUNNING:
            self.return_with_error(
                error_code="schedule_not_running",
                error_desc=not_running_reason or "调度未恢复",
            )
        self.return_success(
            schedule_state=schedule_state,
            not_running_reason=not_running_reason,
        )


class SystemDatabaseBackupHandler(BaseHandler):
    """POST /system/database/backup.json — 备份当前数据库文件。"""

    async def post(self):
        self._assert_admin()
        # backup_database 执行同步 sqlite3.backup，会阻塞事件循环，
        # 丢到线程池执行以避免冻结所有并发请求与调度。
        backup_path = await asyncio.to_thread(ormService.backup_database)
        self.return_success(
            backup_path=backup_path,
            backup_file_name=os.path.basename(backup_path),
        )


class SystemMetricsHandler(BaseHandler):
    """GET /system/metrics.json — 进程内指标（admin-only）。

    暴露 HTTP 请求计数、LLM 推理成功/失败计数、运行时仪表盘等，供监控与告警消费。
    仅管理员可见，避免向未授权方暴露内部运行细节。
    """

    async def get(self):
        self._assert_admin()
        from service import metricsService
        self.return_json(metricsService.get_metrics())


class CheckUpdateHandler(BaseHandler):
    """GET /system/check_update.json — 检查 GitHub 最新版本。"""

    async def get(self):
        force = self.get_argument("force", "false").lower() == "true"
        result = await updateService.check_for_update(force=force)
        self.return_json(result)


class UpdateConfigHandler(BaseHandler):
    """POST /system/update_config.json — 修改自动检查更新等设置。"""

    async def post(self):
        self._assert_admin()
        body = self.parse_request_dict()
        auto_check = body.get("auto_check_update")
        if auto_check is not None:
            configUtil.update_setting(lambda s: setattr(s, "auto_check_update", bool(auto_check)))
        setting = configUtil.get_app_config().setting
        self.return_success(auto_check_update=setting.auto_check_update)
