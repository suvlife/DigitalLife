import os
import sys

import aiohttp

from ...base import ServiceTestCase

if os.name == "posix" and sys.platform == "darwin":
    os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")


class _AuthServiceCase(ServiceTestCase):
    use_custom_config = True


class TestAuthController(_AuthServiceCase):
    requires_backend = True

    async def test_system_status_reports_auth_enabled(self):
        """system/status.json 应返回 auth_enabled=true"""
        async with aiohttp.ClientSession() as client:
            async with client.get(f"{self.backend_base_url}/system/status.json") as resp:
                assert resp.status == 200
                data = await resp.json()

        assert data["auth_enabled"] is True

    async def test_api_without_token_returns_401(self):
        """未携带 token 时应返回 401 auth_required"""
        async with aiohttp.ClientSession() as client:
            async with client.get(f"{self.backend_base_url}/teams/list.json") as resp:
                assert resp.status == 401
                data = await resp.json()

        assert data["error_code"] == "auth_required"

    async def test_api_with_wrong_token_returns_401(self):
        """错误 token 时应返回 401 auth_invalid"""
        async with aiohttp.ClientSession() as client:
            async with client.get(
                f"{self.backend_base_url}/teams/list.json",
                headers={"Authorization": "Bearer wrong_token"},
            ) as resp:
                assert resp.status == 401
                data = await resp.json()

        assert data["error_code"] == "auth_invalid"

    async def test_api_with_correct_token_returns_200(self):
        """正确 token 时应正常返回"""
        async with aiohttp.ClientSession() as client:
            async with client.get(
                f"{self.backend_base_url}/teams/list.json",
                headers={"Authorization": "Bearer test_access_token"},
            ) as resp:
                assert resp.status == 200
                data = await resp.json()

        assert "teams" in data

    async def test_system_status_exempt_from_auth(self):
        """system/status.json 应豁免鉴权，无需 token"""
        async with aiohttp.ClientSession() as client:
            async with client.get(f"{self.backend_base_url}/system/status.json") as resp:
                assert resp.status == 200
                data = await resp.json()

        assert data["auth_enabled"] is True
    async def test_concurrent_first_registration_yields_single_admin(self):
        """并发首用户注册：注册串行化（模块级锁）保证至多产生一个 ADMIN（TOCTOU 修复）。

        无锁时多个并发请求可同时通过"无用户"检查而都获得 ADMIN；
        有锁后第 1 个注册成功为 ADMIN，其余因无 admin 会话被 403。
        """
        import asyncio

        # 仅在干净的 users 表上执行（本测试类共享后端，其他用例不注册用户）
        async with aiohttp.ClientSession() as client:
            async def register(i: int):
                return await client.post(
                    f"{self.backend_base_url}/auth/register.json",
                    json={"username": f"concurrent_user_{i}", "password": "passw0rd"},
                )

            responses = await asyncio.gather(*[register(i) for i in range(5)])
            try:
                results = []
                for resp in responses:
                    body = await resp.json()
                    results.append((resp.status, body))
            finally:
                for resp in responses:
                    resp.close()

        ok = [b for status, b in results if status == 200]
        forbidden = [b for status, b in results if status == 403]
        assert len(ok) == 1, f"应恰好 1 个注册成功，实际 {len(ok)}: {results}"
        assert ok[0]["user"]["role"] == "ADMIN"
        assert len(forbidden) == len(results) - 1, "其余并发注册应因无 admin 权限被拒绝"
        assert all(b["error_code"] == "forbidden" for b in forbidden)
