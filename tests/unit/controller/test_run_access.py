from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import tornado.web

from controller.runController import _RunOwnedHandler
from model.dbModel.gtUser import UserRole
from service import runService


def _handler(*, user, token_admin=False):
    handler = object.__new__(_RunOwnedHandler)
    handler.get_current_user = MagicMock(return_value=user)
    handler._is_authed = MagicMock(return_value=token_admin)
    handler._assert_team_readable = AsyncMock()
    handler.set_status = MagicMock()
    handler.return_json = MagicMock()
    return handler


@pytest.mark.asyncio
async def test_public_team_run_rejects_another_cookie_user_for_all_owned_endpoints(monkeypatch):
    run = SimpleNamespace(id=41, team_id=7, owner_user_id=22)
    monkeypatch.setattr(runService, "get_run", AsyncMock(return_value=run))
    handler = _handler(user=SimpleNamespace(id=11, role=UserRole.USER))

    with pytest.raises(tornado.web.Finish):
        await handler._load_owned_run(run.id)

    handler._assert_team_readable.assert_awaited_once_with(7)
    handler.set_status.assert_called_once_with(403)
    assert handler.return_json.call_args.args[0]["error_code"] == "forbidden"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user,token_admin",
    [
        (SimpleNamespace(id=22, role=UserRole.USER), False),
        (SimpleNamespace(id=1, role=UserRole.ADMIN), False),
        (None, True),
    ],
)
async def test_run_owner_admin_and_legacy_global_token_are_allowed(monkeypatch, user, token_admin):
    run = SimpleNamespace(id=42, team_id=7, owner_user_id=22)
    monkeypatch.setattr(runService, "get_run", AsyncMock(return_value=run))
    handler = _handler(user=user, token_admin=token_admin)

    assert await handler._load_owned_run(run.id) is run


@pytest.mark.asyncio
async def test_legacy_ownerless_run_remains_team_readable(monkeypatch):
    run = SimpleNamespace(id=43, team_id=7, owner_user_id=None)
    monkeypatch.setattr(runService, "get_run", AsyncMock(return_value=run))
    handler = _handler(user=SimpleNamespace(id=11, role=UserRole.USER))

    assert await handler._load_owned_run(run.id) is run
