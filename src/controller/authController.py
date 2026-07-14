"""用户认证控制器 — 登录/登出/注册/当前用户信息。"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta

from controller.baseController import BaseHandler
from model.dbModel.gtUser import (
    GtUser, GtSession, UserRole,
    hash_password, verify_password, generate_session_token,
)
from util import assertUtil, configUtil

logger = logging.getLogger(__name__)

_SESSION_TTL_DAYS = 7
_SESSION_COOKIE_NAME = "dl_session"

# 固定的 dummy 哈希，用于用户不存在时执行等价耗时校验，消除时序侧信道（审计 L3）。
# 在模块加载时生成一次（真实 PBKDF2 结构），不对应任何真实账户。
_DUMMY_PASSWORD_HASH = hash_password(secrets.token_hex(16))


class LoginHandler(BaseHandler):
    """POST /auth/login.json — 用户登录，返回 Set-Cookie。"""

    async def post(self) -> None:
        body = self.parse_request_dict()
        username = body.get("username", "").strip()
        password = body.get("password", "")

        if not username or not password:
            self.set_status(400)
            self.return_json({"error_code": "invalid_input", "error_desc": "用户名和密码不能为空"})
            return

        user = await GtUser.aio_get_or_none(GtUser.username == username)
        if user is None or not user.enabled:
            # 防用户名枚举时序侧信道（审计 L3）：用户不存在/禁用时也执行一次
            # 等价耗时的 PBKDF2 校验，使两条路径的响应时延一致。
            verify_password(password, _DUMMY_PASSWORD_HASH)
            self.set_status(401)
            self.return_json({"error_code": "auth_failed", "error_desc": "用户名或密码错误"})
            return

        if not verify_password(password, user.password_hash):
            self.set_status(401)
            self.return_json({"error_code": "auth_failed", "error_desc": "用户名或密码错误"})
            return

        # 创建 session
        token = generate_session_token()
        expires_at = datetime.now() + timedelta(days=_SESSION_TTL_DAYS)
        session = GtSession(
            token=token,
            user_id=user.id,
            expires_at=expires_at,
            ip_address=self.request.remote_ip or "",
            user_agent=self.request.headers.get("User-Agent", "")[:200],
        )
        await session.aio_save()

        # 更新最后登录时间
        user.last_login = datetime.now()
        await user.aio_save()

        # 设置 Cookie
        is_https = self.request.protocol == "https"
        self.set_cookie(_SESSION_COOKIE_NAME, token, expires_days=_SESSION_TTL_DAYS,
                        httponly=True, secure=is_https, samesite="Strict")

        logger.info("用户登录成功: username=%s, user_id=%d, ip=%s", username, user.id, self.request.remote_ip)

        self.return_json({
            "status": "ok",
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name or user.username,
                "role": user.role.name,
            },
        })


class LogoutHandler(BaseHandler):
    """POST /auth/logout.json — 用户登出，清除 session。"""

    async def post(self) -> None:
        token = self.get_cookie(_SESSION_COOKIE_NAME)
        if token:
            # 删除 session 记录
            session = await GtSession.aio_get_or_none(GtSession.token == token)
            if session is not None:
                await session.aio_delete_instance()
        self.clear_cookie(_SESSION_COOKIE_NAME)
        self.return_success()


class CurrentUserHandler(BaseHandler):
    """GET /auth/me.json — 获取当前登录用户信息。"""

    async def get(self) -> None:
        user = self.get_current_user()
        if user is None:
            self.set_status(401)
            self.return_json({"error_code": "not_authenticated", "error_desc": "未登录"})
            return
        self.return_json({
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name or user.username,
            "role": user.role.name,
        })


class RegisterHandler(BaseHandler):
    """POST /auth/register.json — 用户注册（仅 admin 可调用，或首个用户自动成为 admin）。"""

    async def post(self) -> None:
        body = self.parse_request_dict()
        username = body.get("username", "").strip()
        password = body.get("password", "")
        display_name = body.get("display_name", "").strip()

        if not username or not password:
            self.set_status(400)
            self.return_json({"error_code": "invalid_input", "error_desc": "用户名和密码不能为空"})
            return

        if len(password) < 6:
            self.set_status(400)
            self.return_json({"error_code": "weak_password", "error_desc": "密码至少 6 位"})
            return

        # 检查用户名是否已存在
        existing = await GtUser.aio_get_or_none(GtUser.username == username)
        if existing is not None:
            self.set_status(409)
            self.return_json({"error_code": "username_exists", "error_desc": "用户名已被注册"})
            return

        # 判断是否首个用户（自动成为 admin）
        # 用 aio_get_or_none 查任意用户判断是否已有用户（兼容 peewee-async 无 aio_count）
        any_user = await GtUser.aio_get_or_none()
        is_first_user = any_user is None
        role = UserRole.ADMIN if is_first_user else UserRole.USER

        # 如果已有用户，需要 admin 权限才能注册新用户
        if not is_first_user:
            current = self.get_current_user()
            if current is None or current.role != UserRole.ADMIN:
                self.set_status(403)
                self.return_json({"error_code": "forbidden", "error_desc": "仅管理员可注册新用户"})
                return

        user = GtUser(
            username=username,
            password_hash=hash_password(password),
            role=role,
            display_name=display_name or username,
        )
        await user.aio_save()
        logger.info("用户注册: username=%s, role=%s, user_id=%d", username, role.name, user.id)

        self.return_json({
            "status": "ok",
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "role": user.role.name,
            },
        })
