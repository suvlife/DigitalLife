import datetime
import os

import tornado.web

from controller import roleTemplateController, agentController, roomController, wsController, teamController, deptController, configController, activityController, settingController, systemController, initController, superviseController, usageController, fileController, authController, runController

from controller.baseController import set_security_headers

import sys as _sys
if getattr(_sys, "frozen", False):
    _FRONTEND_DIST = os.path.join(_sys._MEIPASS, "assets/frontend")
    _FRONTEND_V2_DIST = os.path.join(_sys._MEIPASS, "assets/frontend-v2")
else:
    _FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "../assets/frontend")
    _FRONTEND_V2_DIST = os.path.join(os.path.dirname(__file__), "../assets/frontend-v2")


class _SPAHandler(tornado.web.StaticFileHandler):
    """Vue SPA fallback：文件不存在时回退到 index.html。"""

    def set_default_headers(self) -> None:
        set_security_headers(self)

    @staticmethod
    def _is_shell_path(path: str) -> bool:
        return path in ("", "/", "index.html")

    async def get(self, path: str, include_body: bool = True) -> None:
        try:
            await super().get(path, include_body)
        except tornado.web.HTTPError as e:
            if e.status_code == 404:
                await super().get("index.html", include_body)
            else:
                raise

    def get_cache_time(self, path: str, modified: datetime.datetime | None, mime_type: str) -> int:
        # SPA 壳文件不缓存，保证每次都拿到最新页面（避免浏览器继续引用旧 bundle）
        if self._is_shell_path(path):
            return 0
        return super().get_cache_time(path, modified, mime_type)

    def set_extra_headers(self, path: str) -> None:
        if self._is_shell_path(path):
            # 对 SPA 壳文件使用强 no-store，避免浏览器继续复用旧页面。
            self.set_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.set_header("Pragma", "no-cache")
            self.set_header("Expires", "0")
            self.clear_header("Etag")
            self.clear_header("Last-Modified")


class _V2CompatibilityRedirectHandler(tornado.web.RequestHandler):
    """兼容旧 /v2 链接，永久跳转到默认 V2 根路径。"""

    def set_default_headers(self) -> None:
        set_security_headers(self)

    def get(self, path: str = "") -> None:
        target = "/" + path.lstrip("/")
        if self.request.query:
            target += "?" + self.request.query
        self.redirect(target, permanent=True)


tornado_settings = {
    'debug': False,
    'compress_response': True,
    # WebSocket 心跳配置（Tornado 内置）
    'websocket_ping_interval': 30,
    'websocket_ping_timeout': 30,
    # Cookie 安全
    'xsrf_cookies': True,  # 启用 XSRF 防护（BaseHandler.check_xsrf_cookie 按需豁免）
    'cookie_secret': __import__('secrets').token_hex(32),
}

application = tornado.web.Application([
    # Auth (用户认证)
    (r"/auth/login.json",                           authController.LoginHandler),
    (r"/auth/logout.json",                          authController.LogoutHandler),
    (r"/auth/me.json",                              authController.CurrentUserHandler),
    (r"/auth/register.json",                        authController.RegisterHandler),

    # Global config
    (r"/config/frontend.json",                       configController.ConfigHandler),
    (r"/config/directories.json",                    configController.DirectoriesHandler),
    (r"/config/llm_providers/catalog.json",          configController.LlmProviderCatalogHandler),
    (r"/config/llm_services/from_provider.json",     configController.LlmServiceFromProviderHandler),

    # LLM Service Config (V12)
    (r"/config/llm_services/list.json",              settingController.LlmServiceListHandler),
    (r"/config/llm_services/create.json",            settingController.LlmServiceCreateHandler),
    (r"/config/llm_services/test.json",              settingController.LlmServiceTestHandler),
    (r"/config/llm_services/(\d+)/modify.json",      settingController.LlmServiceModifyHandler),
    (r"/config/llm_services/(\d+)/delete.json",      settingController.LlmServiceDeleteHandler),
    (r"/config/llm_services/(\d+)/set_default.json",  settingController.LlmServiceSetDefaultHandler),
    (r"/config/language.json",                       settingController.LanguageHandler),
    (r"/config/skills/list.json",                   settingController.SkillListHandler),
    (r"/config/skills/import.json",                 settingController.SkillImportHandler),
    (r"/config/skills/([^/]+)/delete.json",          settingController.SkillDeleteHandler),
    (r"/config/tools/list.json",                    settingController.ToolListHandler),
    (r"/config/ghost.json",                         settingController.GhostConfigHandler),
    (r"/config/ghost/test.json",                    settingController.GhostTestHandler),

    # System Status & Quick Init (V13)
    (r"/system/status.json",                         systemController.SystemStatusHandler),
    (r"/system/check_update.json",                   systemController.CheckUpdateHandler),
    (r"/system/update_config.json",                  systemController.UpdateConfigHandler),
    (r"/system/schedule/resume.json",                systemController.SystemScheduleResumeHandler),
    (r"/system/database/backup.json",                systemController.SystemDatabaseBackupHandler),
    (r"/config/quick_init.json",                     initController.QuickInitHandler),

    # Role templates
    (r"/role_templates/list.json",                   roleTemplateController.RoleTemplateListHandler),
    (r"/role_templates/create.json",                 roleTemplateController.RoleTemplateCreateHandler),
    (r"/role_templates/([^/]+).json",               roleTemplateController.RoleTemplateDetailHandler),
    (r"/role_templates/([^/]+)/modify.json",         roleTemplateController.RoleTemplateModifyHandler),
    (r"/role_templates/([^/]+)/delete.json",         roleTemplateController.RoleTemplateDeleteHandler),

    # Agents (运行时成员)
    (r"/agents/list.json",                          agentController.AgentListHandler),
    (r"/agents/(\d+).json",                         agentController.AgentDetailByIdHandler),
    (r"/agents/(\d+)/tasks.json",                   agentController.AgentTasksHandler),
    (r"/agents/(\d+)/resume.json",                  agentController.AgentResumeHandler),
    (r"/agents/(\d+)/stop.json",                    agentController.AgentStopHandler),
    (r"/agents/(\d+)/clear_data.json",              agentController.AgentClearDataHandler),
    (r"/agents/(\d+)/modify_properties.json",       agentController.AgentModifyPropertiesHandler),
    (r"/agents/(\d+)/supervise.json",               superviseController.AgentSuperviseHandler),
    (r"/teams/(\d+)/agents/save.json",              agentController.TeamAgentsSaveHandler),
    (r"/teams/(\d+)/agents/([^/]+).json",           agentController.AgentDetailHandler),

    # Room (运行时)
    (r"/rooms/list.json",                           roomController.RoomListHandler),
    (r"/rooms/last_messages.json",                  roomController.RoomLastMessagesHandler),
    (r"/rooms/(\d+)/messages/list.json",            roomController.RoomMessagesHandler),
    (r"/rooms/(\d+)/messages/send.json",            roomController.RoomMessagesHandler),
    (r"/rooms/(\d+)/messages/(\d+)/escalate_to_immediate.json", roomController.EscalateMessageToImmediateHandler),

    # Task Runs (可恢复进度快照)
    (r"/runs/current.json",                         runController.CurrentRunHandler),
    (r"/runs/list.json",                            runController.RunListHandler),
    (r"/runs/(\d+).json",                          runController.RunDetailHandler),
    (r"/runs/(\d+)/rooms.json",                    runController.RunRoomsHandler),
    (r"/runs/(\d+)/timeline.json",                 runController.RunTimelineHandler),
    (r"/runs/(\d+)/final_answer.json",             runController.RunFinalAnswerHandler),

    # WebSocket
    (r"/ws/events.json",                            wsController.EventsWsHandler),

    # Team (配置管理)
    (r"/teams/list.json",                           teamController.TeamListHandler),
    (r"/teams/create.json",                         teamController.TeamCreateHandler),
    (r"/teams/(\d+).json",                          teamController.TeamDetailHandler),
    (r"/teams/(\d+)/tasks.json",                    agentController.TeamTasksHandler),
    (r"/teams/(\d+)/export_preset.json",            teamController.TeamPresetExportHandler),
    (r"/teams/(\d+)/modify.json",                   teamController.TeamModifyHandler),
    (r"/teams/(\d+)/delete.json",                   teamController.TeamDeleteHandler),
    (r"/teams/(\d+)/set_enabled.json",              teamController.TeamSetEnabledHandler),
    (r"/teams/(\d+)/clear_data.json",               teamController.TeamClearDataHandler),

    # Team Rooms (配置管理)
    (r"/teams/(\d+)/rooms/list.json",               roomController.TeamRoomsHandler),
    (r"/teams/(\d+)/rooms/create.json",             roomController.TeamRoomCreateHandler),
    (r"/teams/(\d+)/rooms/(\d+).json",              roomController.TeamRoomDetailHandler),
    (r"/teams/(\d+)/rooms/(\d+)/modify.json",       roomController.TeamRoomModifyHandler),
    (r"/teams/(\d+)/rooms/(\d+)/delete.json",       roomController.TeamRoomDeleteHandler),
    (r"/teams/(\d+)/rooms/(\d+)/agents/list.json",  roomController.TeamRoomAgentsHandler),
    (r"/teams/(\d+)/rooms/(\d+)/agents/modify.json",roomController.TeamRoomAgentsModifyHandler),

    # Dept Tree (V10)
    (r"/teams/(\d+)/dept_tree.json",                deptController.DeptTreeDetailHandler),
    (r"/teams/(\d+)/dept_tree/update.json",         deptController.DeptTreeUpdateHandler),

    # Activities (V11)
    (r"/activities.json",                            activityController.ActivitiesHandler),
    (r"/agents/(\d+)/activities.json",               activityController.AgentActivitiesHandler),
    (r"/agents/(\d+)/thinking_timeline.json",       activityController.AgentThinkingTimelineHandler),
    (r"/teams/(\d+)/activities.json",                activityController.TeamActivitiesHandler),

    # Usage (Token statistics)
    (r"/usage/summary.json",                         usageController.UsageSummaryHandler),
    (r"/usage/total.json",                           usageController.UsageTotalHandler),
    (r"/usage/realtime.json",                        usageController.UsageRealtimeHandler),

    # File upload/download/preview
    (r"/rooms/(\d+)/messages/upload.json",           roomController.RoomMessageUploadHandler),
    (r"/files/download.json",                        fileController.FileDownloadHandler),
    (r"/files/preview.json",                         fileController.FilePreviewHandler),

    # 双前端静态文件（必须放最后）：V2 为默认入口，经典版固定在 /v1。
    (r"/v2/?(.*)", _V2CompatibilityRedirectHandler),
    (r"/v1/?(.*)", _SPAHandler, {"path": _FRONTEND_DIST, "default_filename": "index.html"}),
    (r"/(.*)", _SPAHandler, {"path": _FRONTEND_V2_DIST, "default_filename": "index.html"}),

], **tornado_settings)  # type: ignore [arg-type]
