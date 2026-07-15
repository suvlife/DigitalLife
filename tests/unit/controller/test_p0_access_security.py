from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import tornado.web

from controller.baseController import BaseHandler
from controller.settingController import _assert_safe_llm_url, _assert_safe_service_url
from model.dbModel.gtUser import UserRole
from service import ghostService


def _handler(user, *, token_admin=False):
    handler = object.__new__(BaseHandler)
    handler.get_current_user = MagicMock(return_value=user)
    handler._is_authed = MagicMock(return_value=token_admin)
    handler.set_status = MagicMock()
    handler.return_json = MagicMock()
    return handler


def test_assert_admin_rejects_normal_cookie_user() -> None:
    handler = _handler(SimpleNamespace(id=7, role=UserRole.USER))

    with pytest.raises(tornado.web.Finish):
        handler._assert_admin()

    handler.set_status.assert_called_once_with(403)
    assert handler.return_json.call_args.args[0]["error_code"] == "admin_required"


def test_assert_admin_accepts_admin_and_global_token() -> None:
    _handler(SimpleNamespace(id=1, role=UserRole.ADMIN))._assert_admin()
    _handler(None, token_admin=True)._assert_admin()


@pytest.mark.asyncio
async def test_public_team_is_readable_but_not_writable_by_normal_user(monkeypatch) -> None:
    team = SimpleNamespace(id=3, owner_user_id=None)
    monkeypatch.setattr(BaseHandler, "_get_accessible_team", AsyncMock(return_value=team))
    handler = _handler(SimpleNamespace(id=7, role=UserRole.USER))

    await handler._assert_team_readable(3)
    with pytest.raises(tornado.web.Finish):
        await handler._assert_team_writable(3)

    handler.set_status.assert_called_once_with(403)


@pytest.mark.asyncio
async def test_owned_team_is_writable_by_owner(monkeypatch) -> None:
    team = SimpleNamespace(id=3, owner_user_id=7)
    monkeypatch.setattr(BaseHandler, "_get_accessible_team", AsyncMock(return_value=team))
    handler = _handler(SimpleNamespace(id=7, role=UserRole.USER))

    await handler._assert_team_writable(3)


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data",
        "ftp://example.com/resource",
        "https://user:pass@example.com/",
    ],
)
def test_shared_ssrf_validator_rejects_unsafe_targets(url: str) -> None:
    # Ghost URL 校验始终严格（不允许私有/回环地址）
    with pytest.raises(ValueError):
        ghostService.assert_safe_http_url(url)
    with pytest.raises(Exception) as ghost_error:
        _assert_safe_service_url(url, field_name="Ghost API URL")
    assert getattr(ghost_error.value, "error_code", None) == "unsafe_url"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/v1",
        "http://[::1]:8080/v1",
        "http://localhost:11434/v1",
        "http://192.168.1.100:8080/v1",
        "http://10.0.0.5:11434/v1",
    ],
)
def test_llm_url_allows_private_addresses(url: str) -> None:
    """LLM base_url 允许私有/回环地址（用户可配置本地 Ollama 等服务）。"""
    _assert_safe_llm_url(url)  # 不应抛异常


def test_ghost_url_rejects_loopback() -> None:
    """Ghost 博客地址仍拒绝回环地址。"""
    with pytest.raises(Exception) as ghost_error:
        _assert_safe_service_url("http://127.0.0.1:2368", field_name="Ghost API URL")
    assert getattr(ghost_error.value, "error_code", None) == "unsafe_url"


def test_shared_ssrf_validator_keeps_only_public_addresses(monkeypatch) -> None:
    """混合解析（公网+私有）时通过校验，但只保留公网 IP 供 pinned resolver 使用。"""
    monkeypatch.setattr(
        ghostService.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", ("10.0.0.5", 443)),
        ],
    )

    from util import safeHttpUtil
    _, _, addresses = safeHttpUtil.resolve_public_addresses("https://mixed.example/api")
    assert "93.184.216.34" in addresses
    assert "10.0.0.5" not in addresses


def test_shared_ssrf_validator_rejects_all_private_addresses(monkeypatch) -> None:
    """所有解析地址均为私有/回环时仍拒绝（SSRF 防护不降级）。"""
    monkeypatch.setattr(
        ghostService.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (2, 1, 6, "", ("10.0.0.5", 443)),
            (2, 1, 6, "", ("172.16.0.2", 443)),
        ],
    )

    with pytest.raises(ValueError, match="non-public"):
        ghostService.assert_safe_http_url("https://private.example/api")


def test_shared_ssrf_validator_accepts_public_resolution(monkeypatch) -> None:
    monkeypatch.setattr(
        ghostService.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )

    ghostService.assert_safe_http_url("https://example.com/api")

@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_class", "method_args"),
    [
        pytest.param(
            __import__("controller.configController", fromlist=["LlmServiceFromProviderHandler"]).LlmServiceFromProviderHandler,
            (),
            id="llm-from-provider",
        ),
        pytest.param(
            __import__("controller.roleTemplateController", fromlist=["RoleTemplateCreateHandler"]).RoleTemplateCreateHandler,
            (),
            id="role-create",
        ),
        pytest.param(
            __import__("controller.roleTemplateController", fromlist=["RoleTemplateModifyHandler"]).RoleTemplateModifyHandler,
            ("1",),
            id="role-modify",
        ),
        pytest.param(
            __import__("controller.roleTemplateController", fromlist=["RoleTemplateDeleteHandler"]).RoleTemplateDeleteHandler,
            ("1",),
            id="role-delete",
        ),
        pytest.param(
            __import__("controller.systemController", fromlist=["SystemScheduleResumeHandler"]).SystemScheduleResumeHandler,
            (),
            id="schedule-resume",
        ),
        pytest.param(
            __import__("controller.systemController", fromlist=["SystemDatabaseBackupHandler"]).SystemDatabaseBackupHandler,
            (),
            id="database-backup",
        ),
        pytest.param(
            __import__("controller.systemController", fromlist=["UpdateConfigHandler"]).UpdateConfigHandler,
            (),
            id="system-update-config",
        ),
        pytest.param(
            __import__("controller.settingController", fromlist=["LanguageHandler"]).LanguageHandler,
            (),
            id="language-update",
        ),
    ],
)
async def test_global_write_handlers_require_admin_before_side_effects(handler_class, method_args) -> None:
    handler = object.__new__(handler_class)
    handler._assert_admin = MagicMock(side_effect=tornado.web.Finish())

    with pytest.raises(tornado.web.Finish):
        await handler.post(*method_args)

    handler._assert_admin.assert_called_once_with()
