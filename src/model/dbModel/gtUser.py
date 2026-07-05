"""用户模型 — 公网部署多用户鉴权。"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime

import peewee

from .base import DbModelBase, EnumField
from constants import EnhanceEnum, auto


class UserRole(EnhanceEnum):
    ADMIN = auto()    # 管理员：全部权限
    USER = auto()     # 普通用户：可使用团队/Agent，不能改系统配置
    VIEWER = auto()   # 只读用户：仅查看，不能操作


def hash_password(password: str) -> str:
    """使用 PBKDF2-SHA256 哈希密码（无需额外依赖）。

    Returns: "pbkdf2_sha256$iterations$salt$hash"
    """
    iterations = 100000
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    hash_hex = dk.hex()
    return f"pbkdf2_sha256${iterations}${salt}${hash_hex}"


def verify_password(password: str, stored_hash: str) -> bool:
    """验证密码是否匹配存储的哈希。"""
    try:
        parts = stored_hash.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        iterations = int(parts[1])
        salt = parts[2]
        expected_hash = parts[3]
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
        return hmac.compare_digest(dk.hex(), expected_hash)
    except Exception:
        return False


def generate_session_token() -> str:
    """生成安全的随机 session token。"""
    return secrets.token_urlsafe(32)


class GtUser(DbModelBase):
    """用户账号。"""
    username: str = peewee.CharField(unique=True, null=False)
    password_hash: str = peewee.TextField(null=False)
    role: UserRole = EnumField(UserRole, default=UserRole.USER, null=False)
    display_name: str = peewee.CharField(default="")
    enabled: bool = peewee.BooleanField(default=True)
    last_login: datetime | None = peewee.DateTimeField(null=True)

    # 非数据库字段
    JSON_EXCLUDE = ["password_hash"]

    class Meta:
        table_name = "users"


class GtSession(DbModelBase):
    """用户会话（Cookie-based session）。"""
    token: str = peewee.CharField(unique=True, null=False, index=True)
    user_id: int = peewee.IntegerField(null=False, index=True)
    expires_at: datetime = peewee.DateTimeField(null=False)
    ip_address: str = peewee.CharField(default="")
    user_agent: str = peewee.CharField(default="")

    class Meta:
        table_name = "user_sessions"
