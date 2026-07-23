"""_assert_rooms_owned_batch 单元测试：批量归属校验（两次查询替代 2N 次）。

通过 monkeypatch GtRoom/GtTeam 的 select 链注入测试数据，验证：
- 房间不存在 -> 404 room_not_found
- 房间存在但团队不存在 -> 404 team_not_found
- 他人私有团队 -> 403 forbidden
- 合法批量 -> 无异常（管理员 / 公共团队可读 / 所有者）
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import tornado.web
from controller import baseController
from model.dbModel.gtRoom import GtRoom
from model.dbModel.gtTeam import GtTeam
from model.dbModel.gtUser import UserRole


class FakeHandler:
    def __init__(self, method="POST", user=None, authed=True):
        self.request = SimpleNamespace(method=method)
        self._user = user
        self._authed = authed
        self.status = None
        self.payload = None

    def get_current_user(self):
        return self._user

    def _is_authed(self):
        return self._authed

    def set_status(self, status):
        self.status = status

    def return_json(self, payload):
        self.payload = payload


def _patch_select(monkeypatch, model, rows):
    q2 = MagicMock()
    q2.aio_execute = AsyncMock(return_value=rows)
    q1 = MagicMock()
    q1.where.return_value = q2
    monkeypatch.setattr(model, "select", lambda *a, **k: q1)


async def _run(handler, room_ids):
    """执行批量校验；返回 (raised_finish, status, payload)。"""
    try:
        await baseController.BaseHandler._assert_rooms_owned_batch(handler, room_ids)
        return False, handler.status, handler.payload
    except tornado.web.Finish:
        return True, handler.status, handler.payload


@pytest.mark.asyncio
async def test_missing_room_returns_404(monkeypatch):
    _patch_select(monkeypatch, GtRoom, [])  # 房间不存在
    _patch_select(monkeypatch, GtTeam, [])
    handler = FakeHandler()
    raised, status, payload = await _run(handler, [1])
    assert raised and status == 404
    assert payload["error_code"] == "room_not_found"


@pytest.mark.asyncio
async def test_missing_team_returns_404(monkeypatch):
    _patch_select(monkeypatch, GtRoom, [SimpleNamespace(id=1, team_id=10)])
    _patch_select(monkeypatch, GtTeam, [])  # 团队不存在（已删除）
    handler = FakeHandler()
    raised, status, payload = await _run(handler, [1])
    assert raised and status == 404
    assert payload["error_code"] == "team_not_found"


@pytest.mark.asyncio
async def test_other_owner_private_team_forbidden(monkeypatch):
    _patch_select(monkeypatch, GtRoom, [SimpleNamespace(id=1, team_id=10)])
    _patch_select(monkeypatch, GtTeam, [SimpleNamespace(id=10, owner_user_id=999, deleted=0)])
    # 普通用户（非 admin、非所有者、非 legacy token）
    handler = FakeHandler(user=SimpleNamespace(id=1, role=UserRole.USER), authed=False)
    raised, status, payload = await _run(handler, [1])
    assert raised and status == 403
    assert payload["error_code"] == "forbidden"


@pytest.mark.asyncio
async def test_public_team_readable_without_auth(monkeypatch):
    _patch_select(monkeypatch, GtRoom, [SimpleNamespace(id=1, team_id=10)])
    _patch_select(monkeypatch, GtTeam, [SimpleNamespace(id=10, owner_user_id=None, deleted=0)])
    handler = FakeHandler(method="GET", user=None, authed=False)
    raised, status, _ = await _run(handler, [1])
    assert not raised  # 公共团队对任意用户可读


@pytest.mark.asyncio
async def test_admin_passes_all_rooms(monkeypatch):
    rooms = [SimpleNamespace(id=i, team_id=10) for i in (1, 2, 3)]
    _patch_select(monkeypatch, GtRoom, rooms)
    _patch_select(monkeypatch, GtTeam, [SimpleNamespace(id=10, owner_user_id=999, deleted=0)])
    handler = FakeHandler(user=SimpleNamespace(id=1, role=UserRole.ADMIN))
    raised, status, _ = await _run(handler, [1, 2, 3])
    assert not raised  # 管理员可访问全部
