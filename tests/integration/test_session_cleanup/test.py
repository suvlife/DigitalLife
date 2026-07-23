"""过期 session 清理（cleanup_expired_sessions）集成测试。"""
import os
import sys
from datetime import datetime, timedelta

import service.ormService as ormService
from controller import authController
from model.dbModel.gtUser import GtSession, generate_session_token
from tests.base import ServiceTestCase

if os.name == "posix" and sys.platform == "darwin":
    os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")


class TestSessionCleanup(ServiceTestCase):
    @classmethod
    async def async_setup_class(cls):
        db_path = cls._get_test_db_path()
        await ormService.startup(db_path)

    @classmethod
    async def async_teardown_class(cls):
        await ormService.shutdown()

    async def _reset(self):
        await GtSession.delete().aio_execute()

    async def test_cleanup_deletes_only_expired(self):
        await self._reset()
        now = datetime.now()
        # 2 条已过期 + 1 条恰好临界过期 + 2 条有效
        for i in range(2):
            await GtSession(
                token=generate_session_token(), user_id=1,
                expires_at=now - timedelta(days=i + 1),
            ).aio_save()
        await GtSession(
            token=generate_session_token(), user_id=1,
            expires_at=now - timedelta(seconds=1),
        ).aio_save()
        valid_tokens = []
        for i in range(2):
            token = generate_session_token()
            valid_tokens.append(token)
            await GtSession(
                token=token, user_id=1,
                expires_at=now + timedelta(days=i + 1),
            ).aio_save()

        deleted = await authController.cleanup_expired_sessions()
        assert deleted == 3

        remaining = list(await GtSession.select().aio_execute())
        assert sorted(s.token for s in remaining) == sorted(valid_tokens)

    async def test_cleanup_on_empty_table_is_noop(self):
        await self._reset()
        deleted = await authController.cleanup_expired_sessions()
        assert deleted == 0
