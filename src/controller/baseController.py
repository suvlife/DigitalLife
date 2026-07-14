import hmac
import json
import logging
import re
import time
from typing import Any, TypeVar

import tornado.web
from pydantic import BaseModel, ValidationError
from tornado.web import HTTPError

from exception import TogoException
from util import jsonUtil, configUtil


logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


def format_validation_error(e: ValidationError) -> str:
    """将 Pydantic ValidationError 归纳为「字段级」提示，不回显 input_value。

    审计 L5：直接 str(e) 会带出 input_value（提交的原始字段值）与内部模型结构，
    这里只提取 loc + msg，避免把用户提交内容/模型细节回显给前端。
    """
    parts: list[str] = []
    try:
        for err in e.errors():
            loc = ".".join(str(x) for x in err.get("loc", ()))
            msg = err.get("msg", "校验失败")
            parts.append(f"{loc}: {msg}" if loc else str(msg))
    except Exception:  # pragma: no cover - 防御性兜底
        return "参数校验失败"
    return "; ".join(parts) or "参数校验失败"


_CSP_HEADER = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "font-src 'self' data:; "
    "connect-src 'self' ws: wss:; "
    "frame-ancestors 'none'; "
    "object-src 'none'; "
    "base-uri 'self'"
)


def set_security_headers(handler: tornado.web.RequestHandler) -> None:
    """为任意 RequestHandler 设置统一安全响应头。"""
    handler.set_header("X-Content-Type-Options", "nosniff")
    handler.set_header("X-Frame-Options", "DENY")
    handler.set_header("Referrer-Policy", "strict-origin-when-cross-origin")
    handler.set_header("Content-Security-Policy", _CSP_HEADER)
    if handler.request.protocol == "https":
        handler.set_header(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    # 确保每个响应都携带 _xsrf Cookie，供前端读取后在 POST 请求中回传
    if handler.application.settings.get("xsrf_cookies"):
        _ = handler.xsrf_token

# 简易内存速率限制器：按 IP + 路径 维护滑动窗口
# _rate_limit_store: dict[(ip, path), list[float]] -> 最近请求时间戳列表
_rate_limit_store: dict[tuple[str, str], list[float]] = {}
_RATE_LIMIT_WINDOW_SECONDS = 60  # 60 秒窗口
_rate_limit_last_prune: float = 0.0
_RATE_LIMIT_PRUNE_INTERVAL_SECONDS = 300  # 每 5 分钟清理一次空/过期 key


def _prune_rate_limit_store(now: float) -> None:
    """周期性清理窗口外的空 key，防止 _rate_limit_store 无界增长（审计 L2）。

    攻击者变换源 IP / 路径本可使字典无限膨胀；此处按窗口过滤后删除空列表 key。
    """
    global _rate_limit_last_prune
    if now - _rate_limit_last_prune < _RATE_LIMIT_PRUNE_INTERVAL_SECONDS:
        return
    _rate_limit_last_prune = now
    window = _RATE_LIMIT_WINDOW_SECONDS
    for key in list(_rate_limit_store.keys()):
        remaining = [ts for ts in _rate_limit_store[key] if now - ts < window]
        if remaining:
            _rate_limit_store[key] = remaining
        else:
            del _rate_limit_store[key]


def _check_rate_limit(ip: str, path: str, max_requests: int) -> bool:
    """检查 (ip, path) 在滑动窗口内是否超过 max_requests。返回 True 表示允许。"""
    key = (ip, path)
    now = time.monotonic()
    window = _RATE_LIMIT_WINDOW_SECONDS
    _prune_rate_limit_store(now)
    timestamps = _rate_limit_store.get(key, [])
    # 清理过期时间戳
    timestamps = [ts for ts in timestamps if now - ts < window]
    if len(timestamps) >= max_requests:
        _rate_limit_store[key] = timestamps
        return False
    timestamps.append(now)
    _rate_limit_store[key] = timestamps
    return True


# 需要速率限制的路径及其配额（每 60 秒最大请求数）
_RATE_LIMITED_PATHS: dict[str, int] = {
    "/config/llm_services/test.json": 10,
    "/system/check_update.json": 5,
    "/config/skills/import.json": 10,
    "/config/quick_init.json": 30,
    "/auth/login.json": 10,        # 登录限流
    "/auth/register.json": 3,      # 注册限流
}
_RATE_LIMITED_PATTERNS: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"^/rooms/\d+/messages/upload\.json$"), 20),
)


def _path_rate_limit(path: str) -> int | None:
    exact = _RATE_LIMITED_PATHS.get(path)
    if exact is not None:
        return exact
    for pattern, quota in _RATE_LIMITED_PATTERNS:
        if pattern.fullmatch(path):
            return quota
    return None

# 全局默认限流（非敏感接口）：每 IP 每 60 秒最大请求数
_GLOBAL_RATE_LIMIT = 120


class BaseHandler(tornado.web.RequestHandler):
    """所有 HTTP controller 的基类，提供统一的 JSON 响应方法。"""

    # 安全头（所有响应自动携带）
    def set_default_headers(self) -> None:
        set_security_headers(self)

    def check_xsrf_cookie(self) -> None:
        """XSRF 检查：仅对 Cookie 会话鉴权生效。

        - 鉴权未启用时无 Cookie，跳过（无 CSRF 风险）
        - 登录/注册端点豁免（首次 POST，尚未获取 _xsrf Cookie）
        - Bearer Token 请求不依赖 Cookie，不受 CSRF 攻击影响
        - 其余 Cookie 会话请求强制校验 XSRF Token
        """
        if not configUtil.get_app_config().setting.auth.enabled:
            return
        if self.request.path in {"/auth/login.json", "/auth/register.json"}:
            return
        auth_header = self.request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return
        super().check_xsrf_cookie()

    _READONLY_BLOCKED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
    _AUTH_EXEMPT_PATHS = {
        "/system/status.json",
        "/auth/login.json",
        "/auth/register.json",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.enhance = {}

    def prepare(self) -> None:
        """统一处理鉴权检查和演示模式只读闸门。

        顺序：先鉴权（确认身份），再 demo 闸门（业务态）。
        避免未鉴权调用方通过响应差异探测 read_only 状态。
        """
        # 1. 鉴权检查
        self._check_auth()

        # 1.5 速率限制检查
        client_ip = self.request.remote_ip or "unknown"
        # 敏感接口特殊限流
        max_req = _path_rate_limit(self.request.path)
        if max_req is not None:
            if not _check_rate_limit(client_ip, self.request.path, max_req):
                self.set_status(429)
                self.return_json({"error_code": "rate_limited", "error_desc": "请求过于频繁，请稍后再试"})
                raise tornado.web.Finish()
        # 全局默认限流（排除静态文件和 WebSocket）
        elif not self.request.path.startswith("/assets/") and self.request.path != "/ws/events.json":
            if not _check_rate_limit(client_ip, "_global", _GLOBAL_RATE_LIMIT):
                self.set_status(429)
                self.return_json({"error_code": "rate_limited", "error_desc": "请求过于频繁，请稍后再试"})
                raise tornado.web.Finish()

        # 2. 演示模式检查
        if self.request.method.upper() in self._READONLY_BLOCKED_METHODS:
            demo_mode = configUtil.get_app_config().setting.demo_mode
            if demo_mode.read_only:
                self.set_status(400)
                self.return_json(
                    {
                        "error_code": "demo_mode_data_frozen",
                        "error_desc": "演示模式已冻结数据，当前操作不可用",
                    }
                )
                raise tornado.web.Finish()

    def _check_auth(self) -> None:
        """检查请求是否已认证。支持 Cookie session 和 Bearer Token 两种方式。"""
        # 豁免路径
        if self.request.path in self._AUTH_EXEMPT_PATHS:
            return

        # 优先尝试 Cookie session 鉴权
        if self.get_current_user() is not None:
            return

        # 回退到 Bearer Token 鉴权
        auth_config = configUtil.get_app_config().setting.auth
        if auth_config.enabled:
            auth_header = self.request.headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                self.set_status(401)
                self.return_json({"error_code": "auth_required", "error_desc": "请登录或输入访问 Token"})
                raise tornado.web.Finish()

            token = auth_header[7:]
            if not hmac.compare_digest(token, auth_config.token):
                self.set_status(401)
                self.return_json({"error_code": "auth_invalid", "error_desc": "Token 无效"})
                raise tornado.web.Finish()

    def get_current_user(self):
        """获取当前登录用户（通过 Cookie session）。返回 GtUser 或 None。"""
        token = self.get_cookie("dl_session")
        if not token:
            return None
        try:
            from model.dbModel.gtUser import GtUser, GtSession
            from model.dbModel.base import _database_proxy
            from datetime import datetime
            db = _database_proxy.obj
            if db is None:
                return None
            with db.allow_sync():
                session = GtSession.get_or_none(GtSession.token == token)
                if session is None or session.expires_at < datetime.now():
                    return None
                user = GtUser.get_or_none(GtUser.id == session.user_id)
                if user is None or not user.enabled:
                    return None
                return user
        except Exception:
            return None

    def _is_authed(self) -> bool:
        """检查当前请求是否已通过鉴权（用于豁免路径按需返回敏感信息）。"""
        auth_config = configUtil.get_app_config().setting.auth
        if not auth_config.enabled:
            return True
        auth_header = self.request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return False
        return hmac.compare_digest(auth_header[7:], auth_config.token)

    def _current_user_id(self) -> int | None:
        """获取当前登录用户 ID，未登录返回 None。"""
        user = self.get_current_user()
        return user.id if user else None

    def _is_admin(self) -> bool:
        """判断当前请求是否具备管理员身份（不抛异常，供脱敏判定使用）。

        与 _assert_admin 判定一致：Cookie ADMIN 用户，或未启用多用户鉴权 / 合法
        全局 Token 的旧部署视为管理员。
        """
        from model.dbModel.gtUser import UserRole

        user = self.get_current_user()
        if user is not None and user.role == UserRole.ADMIN:
            return True
        if user is None and self._is_authed():
            return True
        return False

    def _assert_json_content_type(self) -> None:
        """审计 H4：可配置强制校验 JSON 接口的 Content-Type。

        setting.security.enforce_content_type=True 时，拒绝非 application/json 的
        请求体（阻断 text/plain 跨站状态变更）。默认关闭，保持功能优先不破坏现有调用。
        """
        if not configUtil.get_app_config().setting.security.enforce_content_type:
            return
        content_type = self.request.headers.get("Content-Type", "")
        # 取分号前的主类型，忽略 charset 等参数
        main_type = content_type.split(";", 1)[0].strip().lower()
        if main_type != "application/json":
            self.set_status(415)
            self.return_json({
                "error_code": "unsupported_media_type",
                "error_desc": "请求 Content-Type 必须为 application/json",
            })
            raise tornado.web.Finish()

    def _assert_admin(self) -> None:
        """要求管理员权限。

        Cookie 用户必须具有 ADMIN 角色；兼容旧的单 Token/未启用多用户鉴权
        部署时，合法的全局 Token（或关闭鉴权）视为管理员凭据。
        """
        from model.dbModel.gtUser import UserRole

        user = self.get_current_user()
        if user is not None and user.role == UserRole.ADMIN:
            return
        if user is None and self._is_authed():
            return
        self.set_status(403)
        self.return_json({"error_code": "admin_required", "error_desc": "仅管理员可执行此操作"})
        raise tornado.web.Finish()

    async def _get_accessible_team(self, team_id: int):
        from model.dbModel.gtTeam import GtTeam

        team = await GtTeam.aio_get_or_none(GtTeam.id == team_id, GtTeam.deleted == 0)
        if team is None:
            self.set_status(404)
            self.return_json({"error_code": "team_not_found", "error_desc": "团队不存在"})
            raise tornado.web.Finish()
        return team

    async def _assert_team_readable(self, team_id: int) -> None:
        """允许管理员、团队所有者以及任意已认证用户读取公共团队。"""
        from model.dbModel.gtUser import UserRole

        team = await self._get_accessible_team(team_id)
        user = self.get_current_user()
        if user is not None and user.role == UserRole.ADMIN:
            return
        if team.owner_user_id is None:
            return
        if user is not None and team.owner_user_id == user.id:
            return
        # 旧的全局 Token 部署没有用户归属概念，保持兼容。
        if user is None and self._is_authed():
            return
        self.set_status(403)
        self.return_json({"error_code": "forbidden", "error_desc": "无权访问该团队"})
        raise tornado.web.Finish()

    async def _assert_team_writable(self, team_id: int) -> None:
        """仅管理员或团队所有者可写；公共团队对普通用户只读。"""
        from model.dbModel.gtUser import UserRole

        team = await self._get_accessible_team(team_id)
        user = self.get_current_user()
        if user is not None and user.role == UserRole.ADMIN:
            return
        if user is not None and team.owner_user_id == user.id:
            return
        # 兼容关闭多用户鉴权或使用全局 Bearer Token 的旧部署。
        if user is None and self._is_authed():
            return
        self.set_status(403)
        self.return_json({"error_code": "forbidden", "error_desc": "无权修改该团队"})
        raise tornado.web.Finish()

    async def _assert_team_owned(self, team_id: int) -> None:
        """兼容旧调用名：安全方法按可读校验，写方法按可写校验。

        这样无需放宽公共团队写权限，也能让现有控制器的 GET 读取继续工作。
        """
        if self.request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
            await self._assert_team_readable(team_id)
        else:
            await self._assert_team_writable(team_id)

    async def _assert_room_owned(self, room_id: int) -> None:
        """校验房间归属：通过 room.team_id 链式校验。"""
        from model.dbModel.gtRoom import GtRoom
        room = await GtRoom.aio_get_or_none(GtRoom.id == room_id)
        if room is None:
            self.set_status(404)
            self.return_json({"error_code": "room_not_found", "error_desc": "房间不存在"})
            raise tornado.web.Finish()
        await self._assert_team_owned(room.team_id)

    async def _assert_agent_owned(self, agent_id: int) -> None:
        """校验 Agent 归属：通过 agent.team_id 链式校验。"""
        from model.dbModel.gtAgent import GtAgent
        agent = await GtAgent.aio_get_or_none(GtAgent.id == agent_id)
        if agent is None:
            self.set_status(404)
            self.return_json({"error_code": "agent_not_found", "error_desc": "Agent 不存在"})
            raise tornado.web.Finish()
        await self._assert_team_owned(agent.team_id)

    def parse_request(self, model_class: type[T]) -> T:
        """解析请求体为指定的 Pydantic 模型。"""
        self._assert_json_content_type()
        try:
            body = json.loads(self.request.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self.set_status(400)
            self.return_json({"error_code": "invalid_json", "error_desc": f"请求体必须是合法 JSON: {e}"})
            raise tornado.web.Finish()
        return model_class(**body)

    def parse_request_dict(self) -> dict:
        """解析请求体为 dict（用于不需要 Pydantic 模型的简单接口）。"""
        self._assert_json_content_type()
        try:
            body = json.loads(self.request.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self.set_status(400)
            self.return_json({"error_code": "invalid_json", "error_desc": f"请求体必须是合法 JSON: {e}"})
            raise tornado.web.Finish()
        if not isinstance(body, dict):
            self.set_status(400)
            self.return_json({"error_code": "invalid_json", "error_desc": "请求体必须是 JSON 对象"})
            raise tornado.web.Finish()
        return body

    def get_int_argument(self, name: str, default: int | None = None, min_val: int | None = None, max_val: int | None = None) -> int | None:
        """安全解析整数查询参数。非法值返回 400 并 raise Finish。"""
        raw = self.get_argument(name, default=None)
        if raw is None:
            return default
        try:
            value = int(raw)
        except (ValueError, TypeError):
            self.set_status(400)
            self.return_json({"error_code": "invalid_argument", "error_desc": f"参数 {name} 必须是整数"})
            raise tornado.web.Finish()
        if min_val is not None and value < min_val:
            self.set_status(400)
            self.return_json({"error_code": "invalid_argument", "error_desc": f"参数 {name} 不能小于 {min_val}"})
            raise tornado.web.Finish()
        if max_val is not None and value > max_val:
            self.set_status(400)
            self.return_json({"error_code": "invalid_argument", "error_desc": f"参数 {name} 不能大于 {max_val}"})
            raise tornado.web.Finish()
        return value

    def return_json(self, data, config: dict = None) -> None:
        """序列化并写入 JSON 响应。

        使用 jsonUtil.json_dump 处理 datetime、Enum、DbModelBase 等类型。
        DbModelBase 通过 to_json() 方法自动转换。
        """
        self.set_header("Content-Type", "application/json")
        if isinstance(data, BaseModel):
            # Pydantic 模型使用其内置序列化
            self.write(data.model_dump(mode="json"))
        else:
            # jsonUtil 会自动调用 DbModelBase.to_json()
            self.write(jsonUtil.json_dump(data, config=config))

    def return_success(self, **data) -> None:
        """返回统一成功响应。

        默认返回 {"status": "ok"}，可通过关键字参数追加字段。
        """
        payload = {"status": "ok"}
        payload.update(data)
        self.return_json(payload)

    def return_with_error(self, error_code: Any = None, error_desc: str = None) -> None:
        """抛出 HTTP 400 错误，并记录错误信息"""
        self.enhance['error_code'] = error_code
        self.enhance['error_desc'] = error_desc
        raise HTTPError(400)

    def log_exception(self, typ, value, tb) -> None:
        """处理异常日志"""
        if isinstance(value, TogoException):
            # 自定义业务异常，不记录堆栈
            logger.warning(f"Business exception: {value.error_message}")
        else:
            # 其他异常，正常记录
            super().log_exception(typ, value, tb)

    def write_error(self, status_code, **kwargs) -> None:
        """写入错误响应"""
        logger.debug(f"write_error: status_code={status_code}, kwargs={kwargs}")

        exc_info = kwargs.get('exc_info')
        if exc_info and isinstance(exc_info[1], TogoException):
            # 处理自定义异常
            exception_item: TogoException = exc_info[1]
            self.enhance['error_code'] = exception_item.error_code
            self.enhance['error_desc'] = exception_item.error_message
            status_code = 400
            self.set_status(400)

        # 所有错误都返回 JSON 格式
        self.set_header("Content-Type", "application/json")

        if status_code == 400:
            error_code = self.enhance.get('error_code')
            error_desc = self.enhance.get('error_desc')

            if error_code is None and exc_info and isinstance(exc_info[1], HTTPError):
                # 处理 Tornado HTTP 错误
                http_error: HTTPError = exc_info[1]
                error_desc = http_error.log_message

            ret = {
                "error_code": error_code,
                "error_desc": error_desc
            }
        else:
            # 其他状态码也返回 JSON，但不向客户端泄漏内部异常细节
            # （可能含文件路径、SQL、堆栈信息），统一返回通用提示。
            error_desc = "Internal Server Error"
            if exc_info:
                exc = exc_info[1]
                if isinstance(exc, HTTPError):
                    # Tornado HTTPError 的 log_message 可安全透出
                    error_desc = exc.log_message or error_desc
            ret = {
                "error_code": None,
                "error_desc": error_desc
            }
            logger.error(f"Unhandled exception: {exc_info}")

        ret_str = jsonUtil.json_dump(ret)
        self.write(ret_str)
