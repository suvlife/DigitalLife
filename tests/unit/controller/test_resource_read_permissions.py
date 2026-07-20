from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import tornado.web

from controller import activityController, fileController, usageController
from exception import TogoException


class FakeHandler:
    def __init__(self, arguments=None):
        self.arguments = arguments or {}
        self.status = None
        self.payload = None
        self.headers = {}
        self.written = b""
        self._assert_team_owned = AsyncMock()
        self._assert_room_owned = AsyncMock()
        self._assert_agent_owned = AsyncMock()

    def get_argument(self, name, default=None):
        return self.arguments.get(name, default)

    def get_query_argument(self, name, default=None):
        return self.arguments.get(name, default)

    def get_int_argument(self, name, default=None, min_val=None, max_val=None):
        raw = self.arguments.get(name, None)
        if raw is None:
            return default
        value = int(raw)
        if min_val is not None and value < min_val:
            self.set_status(400)
            self.return_json({"error_code": "invalid_argument", "error_desc": f"参数 {name} 不能小于 {min_val}"})
            raise tornado.web.Finish()
        if max_val is not None and value > max_val:
            self.set_status(400)
            self.return_json({"error_code": "invalid_argument", "error_desc": f"参数 {name} 不能大于 {max_val}"})
            raise tornado.web.Finish()
        return value

    def get_arguments(self, name):
        value = self.arguments.get(name, [])
        return value if isinstance(value, list) else [value]

    def set_status(self, status):
        self.status = status

    def set_header(self, name, value):
        self.headers[name] = value

    def return_json(self, payload):
        self.payload = payload

    def write(self, body):
        self.written += body

    async def flush(self):
        return None


@pytest.mark.asyncio
async def test_agent_and_team_activity_handlers_check_resource_ownership(monkeypatch):
    agent = FakeHandler()
    list_agent = AsyncMock(return_value=([], False))
    monkeypatch.setattr(activityController.gtAgentActivityManager, "list_agent_activities_page", list_agent)
    await activityController.AgentActivitiesHandler.get(agent, "7")
    agent._assert_agent_owned.assert_awaited_once_with(7)
    list_agent.assert_awaited_once()

    team = FakeHandler()
    list_team = AsyncMock(return_value=[])
    monkeypatch.setattr(activityController.gtAgentActivityManager, "list_team_activities", list_team)
    await activityController.TeamActivitiesHandler.get(team, "8")
    team._assert_team_owned.assert_awaited_once_with(8)
    list_team.assert_awaited_once_with(8)


@pytest.mark.asyncio
async def test_generic_activities_require_and_check_a_resource(monkeypatch):
    missing = FakeHandler()
    await activityController.ActivitiesHandler.get(missing)
    assert missing.status == 400
    assert missing.payload["error_code"] == "resource_required"

    room = FakeHandler({"room_id": "12"})
    list_activities = AsyncMock(return_value=[])
    monkeypatch.setattr(activityController.gtAgentActivityManager, "list_activities", list_activities)
    await activityController.ActivitiesHandler.get(room)
    room._assert_room_owned.assert_awaited_once_with(12)
    list_activities.assert_awaited_once_with(room_id=12, team_id=None, agent_id=None)


@pytest.mark.asyncio
async def test_usage_handlers_require_scoped_resources(monkeypatch):
    summary = FakeHandler({"team_id": "3", "agent_ids": "10,11"})
    get_summary = AsyncMock(return_value={})
    monkeypatch.setattr(usageController.usageService, "get_usage_summary", get_summary)
    await usageController.UsageSummaryHandler.get(summary)
    summary._assert_team_owned.assert_awaited_once_with(3)
    assert summary._assert_agent_owned.await_args_list[0].args == (10,)
    assert summary._assert_agent_owned.await_args_list[1].args == (11,)
    assert get_summary.await_args.kwargs["team_id"] == 3
    assert get_summary.await_args.kwargs["agent_ids"] == [10, 11]

    missing = FakeHandler()
    await usageController.UsageTotalHandler.get(missing)
    assert missing.status == 400
    assert missing.payload["error_code"] == "resource_required"

    realtime = FakeHandler({"team_id": "4"})
    get_total = AsyncMock(return_value={})
    monkeypatch.setattr(usageController.usageService, "get_usage_total", get_total)
    monkeypatch.setattr(
        usageController.configUtil,
        "get_app_config",
        lambda: SimpleNamespace(setting=SimpleNamespace(current_llm_service=None)),
    )
    await usageController.UsageRealtimeHandler.get(realtime)
    realtime._assert_team_owned.assert_awaited_once_with(4)
    assert get_total.await_args.kwargs["team_id"] == 4


@pytest.mark.asyncio
async def test_team_file_resolution_accepts_relative_uploads_and_outputs_only(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    team_dir = workspace / "team-a"
    (team_dir / "uploads").mkdir(parents=True)
    (team_dir / "outputs").mkdir()
    upload = team_dir / "uploads" / "input.txt"
    report = team_dir / "outputs" / "report.md"
    upload.write_text("input", encoding="utf-8")
    report.write_text("report", encoding="utf-8")

    team = SimpleNamespace(name="team-a", config={}, deleted=0)
    from dal.db import gtTeamManager
    monkeypatch.setattr(gtTeamManager, "get_team_by_id", AsyncMock(return_value=team))
    monkeypatch.setattr(
        fileController.configUtil,
        "get_app_config",
        lambda: SimpleNamespace(setting=SimpleNamespace(workspace_root=str(workspace))),
    )

    assert await fileController._resolve_team_file_path(1, "uploads/input.txt") == str(upload)
    assert await fileController._resolve_team_file_path(1, "outputs/report.md") == str(report)

    with pytest.raises(TogoException) as absolute:
        await fileController._resolve_team_file_path(1, str(report))
    assert absolute.value.error_code == "absolute_path_forbidden"

    with pytest.raises(TogoException) as traversal:
        await fileController._resolve_team_file_path(1, "../team-b/secret.txt")
    assert traversal.value.error_code == "path_outside_sandbox"


@pytest.mark.asyncio
async def test_preview_requires_team_and_returns_team_scoped_download_url(monkeypatch, tmp_path):
    missing = FakeHandler({"path": "outputs/report.pdf"})
    await fileController.FilePreviewHandler.get(missing)
    assert missing.status == 400
    assert missing.payload["error_code"] == "team_id_required"

    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF")
    preview = FakeHandler({"team_id": "6", "path": "outputs/report.pdf"})
    monkeypatch.setattr(fileController, "_resolve_team_file_path", AsyncMock(return_value=str(pdf)))
    await fileController.FilePreviewHandler.get(preview)
    preview._assert_team_owned.assert_awaited_once_with(6)
    assert preview.payload["preview_type"] == "pdf"
    assert preview.payload["url"] == "/files/download.json?team_id=6&path=outputs/report.pdf"

@pytest.mark.asyncio
async def test_agent_list_checks_team_read_permission_before_querying(monkeypatch) -> None:
    from controller.agentController import AgentListHandler
    from dal.db import gtAgentManager

    handler = object.__new__(AgentListHandler)
    handler.get_query_argument = MagicMock(side_effect=lambda name, default=None: "9" if name == "team_id" else default)
    handler._assert_team_readable = AsyncMock(side_effect=tornado.web.Finish())
    list_agents = AsyncMock()
    monkeypatch.setattr(gtAgentManager, "get_team_all_agents", list_agents)

    with pytest.raises(tornado.web.Finish):
        await handler.get()

    handler._assert_team_readable.assert_awaited_once_with(9)
    list_agents.assert_not_awaited()


@pytest.mark.asyncio
async def test_download_streams_in_chunks_and_sets_safe_utf8_filename(monkeypatch, tmp_path):
    payload = b"abcdefghijklmnopqrstuvwxyz"
    file_path = tmp_path / "报告\nfinal.txt"
    file_path.write_bytes(payload)
    handler = FakeHandler({"team_id": "7", "path": "outputs/report.txt"})
    flush = AsyncMock()
    handler.flush = flush
    monkeypatch.setattr(fileController, "_resolve_team_file_path", AsyncMock(return_value=str(file_path)))
    monkeypatch.setattr(fileController, "_DOWNLOAD_CHUNK_SIZE", 5)

    await fileController.FileDownloadHandler.get(handler)

    assert handler.written == payload
    assert flush.await_count == 6
    assert handler.headers["Content-Length"] == str(len(payload))
    disposition = handler.headers["Content-Disposition"]
    assert "\n" not in disposition
    assert "filename*=UTF-8''" in disposition
    assert "%E6%8A%A5%E5%91%8A_final.txt" in disposition


@pytest.mark.asyncio
async def test_download_rejects_files_above_configured_limit(monkeypatch, tmp_path):
    file_path = tmp_path / "large.bin"
    file_path.write_bytes(b"123456")
    handler = FakeHandler({"team_id": "7", "path": "outputs/large.bin"})
    monkeypatch.setattr(fileController, "_resolve_team_file_path", AsyncMock(return_value=str(file_path)))
    monkeypatch.setattr(fileController, "_MAX_DOWNLOAD_BYTES", 5)

    await fileController.FileDownloadHandler.get(handler)

    assert handler.status == 413
    assert handler.payload["error_code"] == "file_too_large"
    assert handler.written == b""


def test_content_disposition_sanitizes_control_characters_and_quotes():
    value = fileController._content_disposition('evil\r\n";name=报告.pdf')
    assert "\r" not in value and "\n" not in value
    assert 'filename="evil____name=.pdf"' in value
    assert "filename*=UTF-8''" in value
    assert "%E6%8A%A5%E5%91%8A.pdf" in value
