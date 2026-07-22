# 标准库
import logging
import os
import time
from collections import Counter
from typing import List

# 第三方包
from pydantic import BaseModel, Field

# 内部包
from controller.baseController import BaseHandler
from dal.db import gtTeamManager, gtRoomManager, gtRoomMessageManager, gtAgentManager
from model.dbModel.gtRoom import GtRoom
from service import roomService, teamService, agentService
from service.roomService import ChatRoom
from constants import SpecialAgent, RoomState, RoomType
from util import assertUtil

logger = logging.getLogger(__name__)


# Room Config Request Models
class CreateRoomRequest(BaseModel):
    name: str
    type: RoomType = RoomType.GROUP
    initial_topic: str | None = None
    max_rounds: int | None = None
    agent_ids: List[int] = Field(default_factory=list)


class UpdateRoomRequest(BaseModel):
    name: str | None = None
    type: str | None = None
    initial_topic: str | None = None
    max_rounds: int | None = None


class UpdateAgentsRequest(BaseModel):
    agent_ids: List[int] = Field(default_factory=list)


class SendMessageRequest(BaseModel):
    content: str | None = None
    insert_immediately: bool = False


class RoomLastMessagesRequest(BaseModel):
    room_ids: List[int] = Field(default_factory=list)


class RoomApiResponse(BaseModel):
    model_config = {"extra": "ignore"}

    gt_room: dict
    state: str
    need_scheduling: bool
    current_turn_agent_id: int | None = None
    agents: List[int] = Field(default_factory=list)

    @classmethod
    def from_gt_room(cls, gt_room: GtRoom, runtime_room: ChatRoom | None = None) -> "RoomApiResponse":
        """构建 Room API 响应。
        若传入 runtime_room，则优先使用其运行时状态；
        否则以 IDLE 状态作为默认值（如 team 已禁用）。
        """
        if runtime_room is not None:
            return cls.model_validate(runtime_room.to_dict())
        return cls(
            gt_room=gt_room.to_json(),
            state=RoomState.IDLE.name,
            need_scheduling=False,
            current_turn_agent_id=None,
            agents=list(gt_room.agent_ids or []),
        )


async def _assert_agent_ids_in_team(team_id: int, agent_ids: List[int]) -> None:
    if len(agent_ids) == 0:
        return

    system_ids = [
        agent_id for agent_id in agent_ids
        if SpecialAgent.value_of(agent_id) == SpecialAgent.SYSTEM
    ]
    assertUtil.assertEqual(
        len(system_ids),
        0,
        error_message=f"system agent is not allowed in room agents: {system_ids}",
        error_code="system_agent_not_allowed",
    )

    duplicate_ids = sorted([agent_id for agent_id, count in Counter(agent_ids).items() if count > 1])
    assertUtil.assertEqual(
        len(duplicate_ids),
        0,
        error_message=f"agent_ids duplicated: {duplicate_ids}",
        error_code="duplicate_agent_ids",
    )

    normal_agent_ids = [agent_id for agent_id in agent_ids if SpecialAgent.value_of(agent_id) is None]
    gt_agents = await gtAgentManager.get_agents_by_ids(normal_agent_ids)
    id_to_agent = {agent.id: agent for agent in gt_agents}

    missing_ids = [
        agent_id for agent_id in normal_agent_ids
        if agent_id not in id_to_agent
    ]
    assertUtil.assertEqual(
        len(missing_ids),
        0,
        error_message=f"agents not found: {missing_ids}",
        error_code="agent_not_found",
    )

    out_of_team_ids = [agent_id for agent_id in normal_agent_ids if id_to_agent[agent_id].team_id != team_id]
    assertUtil.assertEqual(
        len(out_of_team_ids),
        0,
        error_message=f"agents not in team '{team_id}': {out_of_team_ids}",
        error_code="agent_not_in_team",
    )


async def _get_team_room_or_404(team_id: int, room_id: int) -> GtRoom:
    room = await GtRoom.aio_get_or_none(
        (GtRoom.id == room_id) & (GtRoom.team_id == team_id)
    )
    assertUtil.assertNotNull(room, error_message=f"Room ID '{room_id}' not found", error_code="room_not_found")
    return room


class RoomListHandler(BaseHandler):
    async def get(self) -> None:
        team_id = self.get_int_argument("team_id")

        if team_id is not None:
            await self._assert_team_owned(team_id)
            gt_rooms = await gtRoomManager.get_rooms_by_team(team_id)
            data = [
                RoomApiResponse.from_gt_room(gt_room, roomService.get_room(gt_room.id)).model_dump()
                for gt_room in gt_rooms
            ]
        else:
            # 多租户：只查当前用户的团队 + 公共团队
            user_id = self._current_user_id()
            all_teams = await gtTeamManager.get_all_teams(owner_user_id=user_id)
            data = []
            for team in all_teams:
                gt_rooms = await gtRoomManager.get_rooms_by_team(team.id)
                data.extend(
                    RoomApiResponse.from_gt_room(gt_room, roomService.get_room(gt_room.id)).model_dump()
                    for gt_room in gt_rooms
                )

        self.return_json({"rooms": data})


class RoomLastMessagesHandler(BaseHandler):
    """POST /rooms/last_messages.json - 按 room_ids 批量获取每个房间最后一条消息"""

    async def post(self) -> None:
        request = self.parse_request(RoomLastMessagesRequest)
        room_ids = [room_id for room_id in request.room_ids if room_id > 0]
        if not room_ids:
            self.return_json({"messages": []})
            return

        # 多租户：校验每个 room_id 归属当前用户
        for rid in room_ids:
            await self._assert_room_owned(rid)

        last_messages = await gtRoomMessageManager.get_last_messages_by_room_ids(room_ids)
        self.return_json({"messages": last_messages})


class RoomMessagesHandler(BaseHandler):
    """GET /rooms/{id}/messages/list.json; POST /rooms/{id}/messages/send.json"""

    async def get(self, room_id_str: str) -> None:
        room_id = int(room_id_str)
        await self._assert_room_owned(room_id)
        gt_room = await GtRoom.aio_get_or_none(GtRoom.id == room_id)
        assertUtil.assertNotNull(gt_room, error_message=f"room_id '{room_id}' not found", error_code="room_not_found")
        gt_team = await gtTeamManager.get_team_by_id(gt_room.team_id)
        team_name = gt_team.name if gt_team else ""

        limit = self.get_int_argument("limit", min_val=1, max_val=100)
        before_id = self.get_int_argument("before_id")

        gt_messages, has_more = await roomService.get_room_messages_from_db(
            room_id,
            before_id=before_id,
            limit=limit,
        )
        self.return_json({
            "room_id": gt_room.id,
            "room_name": gt_room.name,
            "team_name": team_name,
            "messages": gt_messages,
            "pagination": {
                "has_more": has_more,
                "before_id": before_id,
                "limit": limit,
            },
        })

    async def post(self, room_id_str: str) -> None:
        # 通过数据库 ID 获取内存中的 ChatRoom
        request = self.parse_request(SendMessageRequest)
        room_id = int(room_id_str)
        await self._assert_room_owned(room_id)
        gt_room = await GtRoom.aio_get_or_none(GtRoom.id == room_id)
        assertUtil.assertNotNull(gt_room, error_message=f"room_id '{room_id}' not found", error_code="room_not_found")
        gt_team = await gtTeamManager.get_team_by_id(gt_room.team_id)
        assertUtil.assertTrue(gt_team is not None and gt_team.enabled, error_message="team is not active", error_code="team_not_active")
        room = roomService.get_room(room_id)
        assertUtil.assertNotNull(room, error_message=f"room_id '{room_id}' not found", error_code="room_not_found")
        if room.state == RoomState.INIT:
            # 房间未激活，通常是因为 LLM 服务未配置导致调度器被阻塞
            from service import schedulerService
            reason = schedulerService.get_schedule_not_running_reason()
            self.set_status(400)
            self.return_json({
                "error_code": "room_not_ready",
                "error_desc": f"房间未激活，{'原因：' + reason if reason else '系统调度未启动，请检查大模型服务配置'}",
            })
            return
        content = request.content
        assertUtil.assertNotNull(content, error_message="content is required", error_code="invalid_request")

        if request.insert_immediately:
            assertUtil.assertTrue(
                room.room_type == RoomType.PRIVATE,
                error_message="只有单独问道的雅室支持在当前一轮中立即插话；本研讨室请按普通传讯发送",
                error_code="room_immediate_insert_not_supported",
            )
            ai_agents = [
                a for a in agentService.get_room_agents(room_id)
                if a.gt_agent.id != room.OPERATOR_MEMBER_ID
            ]
            assertUtil.assertTrue(
                len(ai_agents) > 0 and ai_agents[0].host_managed_turn_loop,
                error_message="这位先生当前的推演方式不支持立即插话，请改用普通传讯",
                error_code="immediate_insert_driver_not_supported",
            )

        message = await room.add_message(room.OPERATOR_MEMBER_ID, content, insert_immediately=request.insert_immediately)
        # 每条普通用户问题建立一个可恢复 Run；立即插话属于当前 Run，不新建。
        if not request.insert_immediately and message.id is not None:
            from service import runService
            new_run = await runService.create_run_for_user_message(
                team_id=gt_room.team_id,
                root_room_id=room_id,
                user_message_id=message.id,
                query=content,
                owner_user_id=self._current_user_id(),
            )
            # 设置当前活动 Run ID，使后续调度事件能精准关联到此 Run
            room.current_run_id = new_run.id if new_run else None

            # 自动跨室派发：用户在主殿（GROUP 房间）提问时，把问题派发到团队的其他
            # GROUP 研究室，激活并行讨论。不依赖 LLM 调用 dispatch_to_room 工具
            # （部分模型 function calling 不可靠），改为代码层自动派发。
            if room.room_type == RoomType.GROUP:
                await self._auto_dispatch_to_research_rooms(gt_room.team_id, room_id, content)

        if room.get_current_turn_agent_id() == room.OPERATOR_MEMBER_ID:
            await room.handle_finish_request(room.OPERATOR_MEMBER_ID)
        self.return_success()

    @staticmethod
    async def _auto_dispatch_to_research_rooms(team_id: int, source_room_id: int, question: str) -> None:
        """将用户问题自动派发到团队的其他 GROUP 研究室，激活并行讨论。

        以 SYSTEM 身份向每个目标研究室发送派发消息，触发该室的调度激活。
        仅派发到 GROUP 类型且非源房间的房间，跳过 PRIVATE 单聊和空房间。
        """
        from constants import SpecialAgent, RoomType
        from service import roomService as _rs
        import logging as _lg
        _logger = _lg.getLogger("service.roomService")

        _logger.info("auto-dispatch 开始: team_id=%s, source_room=%s, question=%s", team_id, source_room_id, question[:60])

        try:
            team_rooms = await gtRoomManager.get_rooms_by_team(team_id)
        except Exception as e:
            _logger.warning("auto-dispatch: 获取团队房间失败: %s", e)
            return
        dispatch_content = f"【主问策室派发】操作者提问：{question}"
        dispatched = 0
        for gt_r in team_rooms:
            if gt_r.id == source_room_id:
                continue  # 跳过源房间（主殿）
            if gt_r.type != RoomType.GROUP:
                continue  # 仅派发到 GROUP 研究室
            if not (gt_r.agent_ids or []):
                continue  # 跳过空房间
            target = _rs.get_room(gt_r.id)
            if target is None:
                try:
                    target = await _rs.load_and_activate_room(gt_r.id)
                except Exception:
                    _logger.warning("auto-dispatch: 房间 %s 加载失败", gt_r.id)
                    continue
            if target is None:
                continue
            try:
                await target.add_message(int(SpecialAgent.OPERATOR.value), dispatch_content)
                dispatched += 1
                _logger.info("auto-dispatch: room=%s(源=%s) 已派发问题", gt_r.name, source_room_id)
            except Exception as e:
                _logger.warning("auto-dispatch: 房间 %s 派发失败: %s", gt_r.name, e)


class RoomNewSessionHandler(BaseHandler):
    """POST /rooms/{room_id}/new_session.json - 归档当前讨论，开启全新会话。"""

    async def post(self, room_id_str: str) -> None:
        room_id = int(room_id_str)
        await self._assert_room_owned(room_id)
        gt_room = await GtRoom.aio_get_or_none(GtRoom.id == room_id)
        assertUtil.assertNotNull(gt_room, error_message=f"room_id '{room_id}' not found", error_code="room_not_found")
        room = roomService.get_room(room_id)
        assertUtil.assertNotNull(room, error_message=f"room_id '{room_id}' not found", error_code="room_not_found")

        # 1. 快速归档当前活动 Run：后台异步生成结论+发布博客，API 立即返回
        from service import runService
        import asyncio
        try:
            current_run = await runService.get_current_run(gt_room.team_id)
            if current_run and current_run.status not in ('COMPLETED', 'PARTIAL_FAILED', 'FAILED', 'CANCELLED'):
                # 后台异步：生成 LLM 结论 -> 完成Run -> 发布博客（不阻塞 API 响应）
                async def _archive_run_background(run_id: int, team_id: int):
                    try:
                        room_runs = await runService.list_room_runs(run_id)
                        if room_runs:
                            conclusion = await runService._fallback_conclusion_for_run(
                                await runService.get_run(run_id), room_runs
                            )
                            if conclusion:
                                await runService.complete_final_answer(
                                    run_id=run_id, final_answer=conclusion
                                )
                                logger.info("归档Run %s 的结论已生成并发布", run_id)
                                return
                        # 没有讨论内容，直接标记完成（不发布博客）
                        from dal.db import gtTaskRunManager
                        from constants import TaskRunStatus
                        from datetime import datetime
                        await gtTaskRunManager.update_run(
                            run_id, status=TaskRunStatus.COMPLETED,
                            progress_percent=100, finished_at=datetime.now(),
                        )
                    except Exception as e:
                        logger.warning("后台归档Run %s 失败: %s", run_id, e)

                asyncio.create_task(_archive_run_background(current_run.id, gt_room.team_id))
        except Exception as e:
            logger.warning("归档当前Run失败（不影响新会话）: %s", e)

        # 2. 重置房间调度状态：取消当前轮次，回到 IDLE
        room.cancel_current_turn()
        room.current_run_id = None

        # 3. 清空房间旧消息（DB + 内存，旧讨论已保存在 Run 中不会丢失）
        from dal.db import gtRoomMessageManager
        await gtRoomMessageManager.delete_room_messages(room_id)
        room.clear_messages()

        # 4. 持久化重置状态
        await gtRoomManager.update_room_state(room_id, {}, None)

        self.return_json({"status": "ok", "message": "新会话已就绪"})


class EscalateMessageToImmediateHandler(BaseHandler):
    """POST /rooms/{room_id}/messages/{msg_id}/escalate_to_immediate.json"""

    async def post(self, room_id_str: str, msg_id_str: str) -> None:
        room_id = int(room_id_str)
        await self._assert_room_owned(room_id)
        db_id = int(msg_id_str)
        room = roomService.get_room(room_id)
        assertUtil.assertNotNull(room, error_message=f"room_id '{room_id}' not found", error_code="room_not_found")
        assertUtil.assertTrue(
            room.room_type == RoomType.PRIVATE,
            error_message="只有单独问道的雅室支持将传讯提升为本轮急件",
            error_code="room_immediate_insert_not_supported",
        )
        await room.escalate_message_to_immediate(db_id)
        self.return_success()


# Team Room Management Handlers
class TeamRoomsHandler(BaseHandler):
    """GET /teams/{team_id}/rooms/list.json - 获取 Team 下的所有 Room"""

    async def get(self, team_id_str: str) -> None:
        team_id = int(team_id_str)
        await self._assert_team_owned(team_id)
        assertUtil.assertNotNull(
            await gtTeamManager.get_team_by_id(team_id),
            error_message=f"Team ID '{team_id}' not found",
            error_code="team_not_found",
        )

        rooms = await gtRoomManager.get_rooms_by_team(team_id)
        self.return_json({"rooms": rooms})


class TeamRoomCreateHandler(BaseHandler):
    """POST /teams/{team_id}/rooms/create.json - 在 Team 下创建 Room"""

    async def post(self, team_id_str: str) -> None:
        request = self.parse_request(CreateRoomRequest)
        team_id = int(team_id_str)
        await self._assert_team_owned(team_id)

        await roomService.create_room(
            team_id=team_id,
            name=request.name,
            agent_ids=list(request.agent_ids),
            initial_topic=request.initial_topic or "",
            max_rounds=request.max_rounds,
        )

        self.return_json({"status": "created", "room_name": request.name})


class TeamRoomDetailHandler(BaseHandler):
    """GET /teams/{team_id}/rooms/{room_id}.json - 获取指定 Room 详情"""

    async def get(self, team_id_str: str, room_id_str: str) -> None:
        team_id = int(team_id_str)
        await self._assert_team_owned(team_id)
        room_id = int(room_id_str)
        await self._assert_room_owned(room_id)
        assertUtil.assertNotNull(
            await gtTeamManager.get_team_by_id(team_id),
            error_message=f"Team ID '{team_id}' not found",
            error_code="team_not_found",
        )
        room = await _get_team_room_or_404(team_id, room_id)

        data = {
            "id": room.id,
            "name": room.name,
            "i18n": room.i18n or {},
            "type": room.type.name,
            "initial_topic": room.initial_topic,
            "max_rounds": room.max_rounds,
            "agent_ids": room.agent_ids or [],
        }
        self.return_json(data)


class TeamRoomModifyHandler(BaseHandler):
    """POST /teams/{team_id}/rooms/{room_id}/modify.json - 更新 Room"""

    async def post(self, team_id_str: str, room_id_str: str) -> None:
        request = self.parse_request(UpdateRoomRequest)

        team_id = int(team_id_str)
        await self._assert_team_owned(team_id)
        room_id = int(room_id_str)
        await self._assert_room_owned(room_id)
        team = await gtTeamManager.get_team_by_id(team_id)
        assertUtil.assertNotNull(team, error_message=f"Team ID '{team_id}' not found", error_code="team_not_found")
        team_name = team.name

        room = await _get_team_room_or_404(team_id, room_id)

        if request.name is not None:
            assertUtil.assertTrue(
                "DEPT" not in (room.tags or []),
                error_message="Dept rooms cannot be renamed",
                error_code="dept_room_rename_not_allowed",
            )
            room_name = request.name.strip()
            assertUtil.assertTrue(
                bool(room_name),
                error_message="Room name must not be empty",
                error_code="room_name_empty",
            )
            existing = await gtRoomManager.get_room_by_team_and_name(team_id, room_name)
            assertUtil.assertTrue(
                existing is None or existing.id == room.id,
                error_message=f"Room '{room_name}' already exists",
                error_code="room_exists",
            )
            room.name = room_name
        if request.type is not None:
            room.type = RoomType(request.type)
        if request.initial_topic is not None:
            room.initial_topic = request.initial_topic
        if request.max_rounds is not None:
            room.max_rounds = request.max_rounds

        await gtRoomManager.save_room(room)
        await teamService.hot_reload_team(team_name)

        self.return_json({"status": "updated", "room_name": room.name})


class TeamRoomDeleteHandler(BaseHandler):
    """POST /teams/{team_id}/rooms/{room_id}/delete.json - 删除 Room"""

    async def post(self, team_id_str: str, room_id_str: str) -> None:
        team_id = int(team_id_str)
        await self._assert_team_owned(team_id)
        room_id = int(room_id_str)
        await self._assert_room_owned(room_id)
        team = await gtTeamManager.get_team_by_id(team_id)
        assertUtil.assertNotNull(team, error_message=f"Team ID '{team_id}' not found", error_code="team_not_found")
        team_name = team.name

        room = await _get_team_room_or_404(team_id, room_id)
        room_name = room.name

        await gtRoomManager.delete_room(room_id)
        await teamService.hot_reload_team(team_name)

        self.return_json({"status": "deleted", "room_name": room_name})


class TeamRoomAgentsHandler(BaseHandler):
    """GET /teams/{team_id}/rooms/{room_id}/agents/list.json - 获取 Room Agent ID 列表"""

    async def get(self, team_id_str: str, room_id_str: str) -> None:
        team_id = int(team_id_str)
        await self._assert_team_owned(team_id)
        room_id = int(room_id_str)
        await self._assert_room_owned(room_id)
        assertUtil.assertNotNull(
            await gtTeamManager.get_team_by_id(team_id),
            error_message=f"Team ID '{team_id}' not found",
            error_code="team_not_found",
        )
        room = await _get_team_room_or_404(team_id, room_id)

        self.return_json({"agent_ids": room.agent_ids or []})


class TeamRoomAgentsModifyHandler(BaseHandler):
    """POST /teams/{team_id}/rooms/{room_id}/agents/modify.json - 更新 Room Agent ID 列表"""

    async def post(self, team_id_str: str, room_id_str: str) -> None:
        request = self.parse_request(UpdateAgentsRequest)

        team_id = int(team_id_str)
        await self._assert_team_owned(team_id)
        room_id = int(room_id_str)
        await self._assert_room_owned(room_id)
        team = await gtTeamManager.get_team_by_id(team_id)
        assertUtil.assertNotNull(team, error_message=f"Team ID '{team_id}' not found", error_code="team_not_found")
        team_name = team.name

        room = await _get_team_room_or_404(team_id, room_id)

        await _assert_agent_ids_in_team(team_id, request.agent_ids)
        await roomService.update_room_agents(room.id, request.agent_ids)
        await teamService.hot_reload_team(team_name)

        self.return_json({"status": "updated", "room_name": room.name})


# ─── 文件上传 ─────────────────────────────────────────────

_MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB
_ALLOWED_UPLOAD_EXTENSIONS = {
    "txt", "md", "markdown", "json", "csv", "pdf", "doc", "docx", "ppt", "pptx", "xlsx", "xls",
    "png", "jpg", "jpeg", "gif", "svg", "zip",
    "py", "js", "ts", "sql", "yaml", "yml",
}


class RoomMessageUploadHandler(BaseHandler):
    """POST /rooms/{room_id}/messages/upload.json — 上传文件到团队工作目录并在房间发送通知消息。"""

    async def post(self, room_id_str: str) -> None:
        room_id = int(room_id_str)
        await self._assert_room_owned(room_id)

        room_config = await gtRoomManager.get_room_by_id(room_id)
        assertUtil.assertNotNull(room_config, error_message=f"Room ID '{room_id}' not found", error_code="room_not_found")
        team = await gtTeamManager.get_team_by_id(room_config.team_id)
        assertUtil.assertNotNull(team, error_message="Team not found", error_code="team_not_found")

        files = self.request.files.get("file")
        if not files or len(files) == 0:
            self.set_status(400)
            self.return_json({"error_code": "no_file", "error_desc": "未上传文件"})
            return

        uploaded_file = files[0]
        filename = uploaded_file.filename or "unnamed"
        file_body = uploaded_file.body

        if len(file_body) > _MAX_UPLOAD_SIZE:
            self.set_status(400)
            self.return_json({"error_code": "file_too_large", "error_desc": f"文件大小超过限制（{_MAX_UPLOAD_SIZE // 1024 // 1024}MB）"})
            return

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in _ALLOWED_UPLOAD_EXTENSIONS:
            self.set_status(400)
            self.return_json({"error_code": "invalid_format", "error_desc": f"不支持的文件格式: .{ext}，支持: {', '.join(sorted(_ALLOWED_UPLOAD_EXTENSIONS))}"})
            return

        from util import configUtil
        workspace_root = configUtil.get_app_config().setting.workspace_root
        if not workspace_root:
            self.set_status(400)
            self.return_json({"error_code": "workspace_not_configured", "error_desc": "workspace_root 未配置"})
            return

        team_config = team.config or {}
        team_workdir = team_config.get("working_directory") or os.path.join(workspace_root, team.name)

        # 审计 L6：与下载侧一致，先校验团队工作目录本身在 workspace_root 沙箱内，
        # 防止 working_directory 曾被配置到工作空间之外导致上传落盘越界。
        from util import fileUtil
        try:
            fileUtil.assert_path_within_sandbox(team_workdir, workspace_root)
        except Exception:
            self.set_status(400)
            self.return_json({"error_code": "invalid_workdir", "error_desc": "团队工作目录不在工作空间沙箱内"})
            return

        upload_dir = os.path.join(team_workdir, "uploads")
        os.makedirs(upload_dir, exist_ok=True)

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        safe_filename = "".join(c for c in filename if c.isalnum() or c in ("._-"))
        # 防御：拒绝空文件名或纯点号文件名
        if not safe_filename or safe_filename.strip(".") == "":
            self.set_status(400)
            self.return_json({"error_code": "invalid_filename", "error_desc": "文件名不合法"})
            return
        saved_filename = f"{timestamp}_{safe_filename}"
        saved_path = os.path.join(upload_dir, saved_filename)

        # 沙箱校验：确保最终路径在 upload_dir 内
        fileUtil.assert_path_within_sandbox(saved_path, upload_dir)
        saved_path = os.path.join(upload_dir, saved_filename)

        try:
            with open(saved_path, "wb") as f:
                f.write(file_body)
        except OSError as e:
            self.set_status(500)
            self.return_json({"error_code": "save_failed", "error_desc": str(e)})
            return

        file_size_kb = len(file_body) / 1024
        message_text = self.get_body_argument("message", "")
        notification = f"[文件:uploads/{saved_filename}]{filename}|{len(file_body)}\n已递交卷宗，可请本室大师读取并分析。"
        if message_text:
            notification += f"\n{message_text}"

        room = roomService.get_room(room_id)
        if room is not None:
            await room.add_message(SpecialAgent.OPERATOR.value, notification)

        logger.info("文件上传: room_id=%d, filename=%s, size=%d", room_id, filename, len(file_body))

        self.return_json({
            "success": True,
            "filename": filename,
            "saved_path": f"uploads/{saved_filename}",
            "size": len(file_body),
            "message": "文件上传成功，已通知房间内的 Agent。",
        })
