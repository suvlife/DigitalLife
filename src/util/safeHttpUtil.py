"""SSRF-resistant HTTP client helpers for user-configured upstream services.

Each request hop is resolved exactly once, every resolved address must be public,
and aiohttp is given a resolver pinned to that validated address set. Redirects are
handled manually so every Location receives the same validation before connecting.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import socket
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urljoin, urlparse

import aiohttp
from aiohttp.abc import AbstractResolver
from aiohttp.abc import ResolveResult

logger = logging.getLogger(__name__)

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_BLOCKED_HOSTS = frozenset({"localhost", "ip6-localhost", "ip6-loopback", "metadata.google.internal"})


class UnsafeUrlError(ValueError):
    """The requested URL can reach a non-public or otherwise forbidden target."""


class TooManyRedirectsError(UnsafeUrlError):
    """The upstream exceeded the explicit redirect limit or formed a loop."""


@dataclass(frozen=True)
class SafeHttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes
    url: str

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


def _parse_target(url: str, *, field_name: str = "URL", allow_private: bool = False) -> tuple[str, int]:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("http", "https"):
        raise UnsafeUrlError(f"{field_name} must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise UnsafeUrlError(f"{field_name} must not contain credentials")
    hostname = parsed.hostname
    if not hostname:
        raise UnsafeUrlError(f"{field_name} must contain a hostname")
    try:
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise UnsafeUrlError(f"{field_name} contains an invalid port") from exc
    # allow_private 时跳过 localhost 拦截，允许配置本地 LLM（Ollama 等）
    if not allow_private and hostname.rstrip(".").lower() in _BLOCKED_HOSTS:
        raise UnsafeUrlError(f"{field_name} points to a local or metadata host")
    return hostname, port


def _filter_safe_addresses(
    addresses: tuple[str, ...], *, field_name: str,
    allow_test_loopback: bool, allow_private: bool,
) -> tuple[str, ...]:
    """从解析结果中筛出可用地址（公网 / 测试回环 / 允许的私有地址）。

    只要存在至少一个 global IP 即视为公网域名；返回集合只保留可用 IP，
    pinned resolver 只会连接这些 IP，实际请求不会打到内网；纯内网域名
    （无任何 global IP）仍被拒绝。此函数纯内存计算，可在事件循环安全调用。
    """
    if not addresses:
        raise UnsafeUrlError(f"{field_name} hostname could not be resolved")
    test_mode = os.environ.get("TEAMAGENT_ENV") == "test" or bool(os.environ.get("PYTEST_CURRENT_TEST"))
    # 此前要求"所有 IP 必须 global"会误杀同时解析出公网+保留/ULA 地址的合法域名（DNS 拦截、双栈等场景）。
    safe_addresses: list[str] = []
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise UnsafeUrlError(f"{field_name} resolved to an invalid address") from exc
        if ip.is_global or (allow_test_loopback and test_mode and ip.is_loopback):
            safe_addresses.append(address)
        elif allow_private:
            # 允许私有/回环地址（用于本地 LLM 配置，如 Ollama）
            safe_addresses.append(address)
    if not safe_addresses:
        raise UnsafeUrlError(f"{field_name} points to a non-public address")
    return tuple(safe_addresses)


def resolve_public_addresses(
    url: str, *, field_name: str = "URL", allow_test_loopback: bool = False,
    allow_private: bool = False,
) -> tuple[str, int, tuple[str, ...]]:
    """Resolve one URL once and keep only globally routable addresses.

    A domain is accepted as long as it resolves to at least one global IP; only
    those global IPs are returned so the pinned resolver never reaches a private
    target. A purely private/loopback domain (no global IP) is still rejected.

    When ``allow_private`` is True, private/loopback addresses are also accepted.
    This is intended for LLM base_url configuration where users may point to
    local services (e.g. Ollama at http://localhost:11434/v1).

    注意：本函数含同步 ``socket.getaddrinfo``，会阻塞事件循环。异步上下文请用
    ``aresolve_public_addresses``。
    """
    hostname, port = _parse_target(url, field_name=field_name, allow_private=allow_private)
    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"{field_name} hostname could not be resolved") from exc
    addresses = tuple(dict.fromkeys(item[4][0].split("%", 1)[0] for item in infos))
    safe = _filter_safe_addresses(
        addresses, field_name=field_name,
        allow_test_loopback=allow_test_loopback, allow_private=allow_private,
    )
    return hostname, port, safe


async def aresolve_public_addresses(
    url: str, *, field_name: str = "URL", allow_test_loopback: bool = False,
    allow_private: bool = False,
) -> tuple[str, int, tuple[str, ...]]:
    """``resolve_public_addresses`` 的异步版本：DNS 解析移到事件循环的
    executor 线程，避免慢 DNS / 被劫持 DNS 冻结整个 Tornado 事件循环。

    每次 LLM 推理（含每次重试）都会经 SSRF 校验解析目标地址，同步
    ``socket.getaddrinfo`` 在 async 路径会阻塞所有并发 Agent 与 WebSocket。
    这里用 ``loop.getaddrinfo`` 异步化，结果与同步版完全一致。
    """
    hostname, port = _parse_target(url, field_name=field_name, allow_private=allow_private)
    loop = asyncio.get_running_loop()
    try:
        # 用 run_in_executor 显式调用模块级 socket.getaddrinfo（而非 loop.getaddrinfo），
        # 一是与同步版解析路径完全一致（同样签名、同样可被测试 mock），二是移到 executor
        # 线程避免慢/被劫持 DNS 阻塞事件循环。
        infos = await loop.run_in_executor(
            None, lambda: socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        )
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"{field_name} hostname could not be resolved") from exc
    addresses = tuple(dict.fromkeys(item[4][0].split("%", 1)[0] for item in infos))
    safe = _filter_safe_addresses(
        addresses, field_name=field_name,
        allow_test_loopback=allow_test_loopback, allow_private=allow_private,
    )
    return hostname, port, safe


def assert_safe_http_url(url: str, *, field_name: str = "URL", allow_private: bool = False) -> None:
    resolve_public_addresses(url, field_name=field_name, allow_private=allow_private)


class _PinnedResolver(AbstractResolver):
    def __init__(self, hostname: str, port: int, addresses: tuple[str, ...]) -> None:
        self._hostname = hostname.rstrip(".").lower()
        self._port = port
        self._addresses = addresses

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_UNSPEC) -> list[ResolveResult]:
        if host.rstrip(".").lower() != self._hostname or (port and port != self._port):
            raise OSError("resolver was asked for an unvalidated target")
        results: list[ResolveResult] = []
        for address in self._addresses:
            ip = ipaddress.ip_address(address)
            if family not in (socket.AF_UNSPEC, socket.AF_INET if ip.version == 4 else socket.AF_INET6):
                continue
            results.append({
                "hostname": host,
                "host": address,
                "port": self._port,
                "family": socket.AF_INET if ip.version == 4 else socket.AF_INET6,
                "proto": socket.IPPROTO_TCP,
                "flags": socket.AI_NUMERICHOST,
            })
        if not results:
            raise OSError("validated target has no address for requested family")
        return results

    async def close(self) -> None:
        return None



async def _reject_redirect(
    session: aiohttp.ClientSession,
    trace_config_ctx: Any,
    params: aiohttp.TraceRequestRedirectParams,
) -> None:
    """Fail closed if a caller accidentally enables redirects on a pinned session."""
    raise UnsafeUrlError("validated upstream attempted an HTTP redirect")


def _normalize_timeout(timeout: aiohttp.ClientTimeout | float | None, default_total: float) -> aiohttp.ClientTimeout:
    if timeout is None:
        return aiohttp.ClientTimeout(total=default_total)
    if isinstance(timeout, (int, float)):
        return aiohttp.ClientTimeout(total=float(timeout))
    return timeout


def _pinned_session_from_addresses(
    hostname: str, port: int, addresses: tuple[str, ...],
    timeout_value: aiohttp.ClientTimeout,
) -> aiohttp.ClientSession:
    """用已校验的地址构建 pinned aiohttp session（公网固定 + 重定向拦截 + trust_env=False）。"""
    connector = aiohttp.TCPConnector(
        resolver=_PinnedResolver(hostname, port, addresses),
        use_dns_cache=False,
        ttl_dns_cache=0,
    )
    trace_config = aiohttp.TraceConfig()
    trace_config.on_request_redirect.append(_reject_redirect)
    return aiohttp.ClientSession(
        timeout=timeout_value,
        connector=connector,
        trace_configs=[trace_config],
        trust_env=False,
    )


def _fallback_plain_session(timeout_value: aiohttp.ClientTimeout, field_name: str, url: str) -> aiohttp.ClientSession:
    """纯私网/代理假 IP 目标的降级普通会话（系统 DNS），并记录告警。"""
    logger.warning(
        "%s 本机 DNS 无法解析出公网地址，DNS pinning 降级为系统 DNS（本地 LLM / 代理 fake-IP）: %s",
        field_name, url,
    )
    connector = aiohttp.TCPConnector(use_dns_cache=False)
    return aiohttp.ClientSession(timeout=timeout_value, connector=connector)


def create_pinned_client_session(
    url: str,
    *,
    timeout: aiohttp.ClientTimeout | float | None = None,
    field_name: str = "URL",
    allow_test_loopback: bool = False,
    allow_private: bool = False,
) -> aiohttp.ClientSession:
    """Create a one-origin session pinned to the URL's validated public IPs.

    同步版本，含同步 ``socket.getaddrinfo``，会阻塞事件循环。异步上下文请用
    ``acreate_pinned_client_session``。其余语义两者一致：公网地址走 pinned，
    仅真私有（回环/RFC1918/代理假 IP）降级普通会话。
    """
    timeout_value = _normalize_timeout(timeout, default_total=600)

    if allow_private:
        try:
            resolved = resolve_public_addresses(
                url, field_name=field_name, allow_test_loopback=allow_test_loopback
            )
        except UnsafeUrlError:
            resolved = None
        if resolved is None:
            return _fallback_plain_session(timeout_value, field_name, url)
        hostname, port, addresses = resolved
    else:
        hostname, port, addresses = resolve_public_addresses(
            url, field_name=field_name, allow_test_loopback=allow_test_loopback
        )

    return _pinned_session_from_addresses(hostname, port, addresses, timeout_value)


async def acreate_pinned_client_session(
    url: str,
    *,
    timeout: aiohttp.ClientTimeout | float | None = None,
    field_name: str = "URL",
    allow_test_loopback: bool = False,
    allow_private: bool = False,
) -> aiohttp.ClientSession:
    """``create_pinned_client_session`` 的异步版本：DNS 解析移到 executor 线程，
    避免每次 LLM 推理（含重试）在事件循环里同步 getaddrinfo 阻塞所有并发任务。

    语义与同步版完全一致（公网 pinned / 真私有降级），仅解析方式异步化。
    """
    timeout_value = _normalize_timeout(timeout, default_total=600)

    if allow_private:
        try:
            resolved = await aresolve_public_addresses(
                url, field_name=field_name, allow_test_loopback=allow_test_loopback
            )
        except UnsafeUrlError:
            resolved = None
        if resolved is None:
            return _fallback_plain_session(timeout_value, field_name, url)
        hostname, port, addresses = resolved
    else:
        hostname, port, addresses = await aresolve_public_addresses(
            url, field_name=field_name, allow_test_loopback=allow_test_loopback
        )

    return _pinned_session_from_addresses(hostname, port, addresses, timeout_value)


def _redirect_method(status: int, method: str) -> str:
    upper = method.upper()
    if status == 303 and upper != "HEAD":
        return "GET"
    if status in (301, 302) and upper == "POST":
        return "GET"
    return upper


def _get_default_ssl_context() -> "ssl.SSLContext | None":
    """获取默认 SSL context，打包环境下用 certifi 证书包。

    PyInstaller 打包后系统 CA 证书路径可能断裂，aiohttp 默认的
    ssl=None 内部调用 create_default_context() 虽然会读 SSL_CERT_FILE
    环境变量，但某些环境下可能不稳定。此处显式创建 context 确保
    证书链完整。
    """
    import sys
    if not getattr(sys, "frozen", False):
        return None  # 非打包环境用系统默认
    try:
        import certifi
        import ssl as _ssl
        return _ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


async def request(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    json_body: Any = None,
    data: Any = None,
    timeout: aiohttp.ClientTimeout | float | None = None,
    max_redirects: int = 5,
    field_name: str = "URL",
    ssl: Any = None,
    max_bytes: int | None = None,
    allow_private: bool = False,
) -> SafeHttpResponse:
    """Perform a request with DNS pinning and manually validated redirects.

    When ``max_bytes`` is set, the response body is read incrementally and
    truncated at that limit so an oversized or slow-streaming upstream cannot
    exhaust memory (see audit finding H2). A truncated body still returns the
    partial content with the real status/headers.
    """
    current_url = url.strip()
    current_method = method.upper()
    current_json = json_body
    current_data = data
    current_headers = dict(headers or {})
    visited: set[str] = set()
    # aiohttp 要求 timeout 为 ClientTimeout；调用方可能传入数字秒数（如 web_fetch 的 timeout=30），
    # 统一归一化为 ClientTimeout，避免 "timeout parameter cannot be of <class 'int'>" 报错。
    if timeout is None:
        timeout_value: aiohttp.ClientTimeout = aiohttp.ClientTimeout(total=30)
    elif isinstance(timeout, (int, float)):
        timeout_value = aiohttp.ClientTimeout(total=float(timeout))
    else:
        timeout_value = timeout

    for hop in range(max_redirects + 1):
        if current_url in visited:
            raise TooManyRedirectsError(f"{field_name} redirect loop detected")
        visited.add(current_url)
        hostname, port, addresses = await aresolve_public_addresses(current_url, field_name=field_name, allow_private=allow_private)
        # allow_private=True 时跳过 DNS pinning，使用系统默认 DNS 解析。
        # 原因：用户可能使用代理软件（Surge/Clash），代理通过 DNS 劫持
        # 将域名解析到 198.18.x.x 虚假 IP 再透明转发。DNS pinning 会绑定
        # 到该虚假 IP 直连，绕过代理导致连接失败。
        if allow_private:
            connector = aiohttp.TCPConnector(use_dns_cache=False)
        else:
            connector = aiohttp.TCPConnector(
                resolver=_PinnedResolver(hostname, port, addresses),
                use_dns_cache=False,
            )
        # ssl=None 时在打包环境下用 certifi 证书包，确保 SSL 验证可用
        effective_ssl = ssl if ssl is not None else _get_default_ssl_context()
        async with aiohttp.ClientSession(timeout=timeout_value, connector=connector) as session:
            async with session.request(
                current_method,
                current_url,
                headers=current_headers,
                json=current_json,
                data=current_data,
                allow_redirects=False,
                ssl=effective_ssl,
            ) as response:
                if max_bytes is not None:
                    body = await response.content.read(max_bytes + 1)
                    if len(body) > max_bytes:
                        body = body[:max_bytes]
                else:
                    body = await response.read()
                response_headers = dict(response.headers)
                response_url = str(response.url)
                status = response.status

        if status not in _REDIRECT_STATUSES:
            return SafeHttpResponse(status=status, headers=response_headers, body=body, url=response_url)
        location = response_headers.get("Location") or response_headers.get("location")
        if not location:
            return SafeHttpResponse(status=status, headers=response_headers, body=body, url=response_url)
        if hop >= max_redirects:
            raise TooManyRedirectsError(f"{field_name} exceeded {max_redirects} redirects")

        next_url = urljoin(current_url, location)
        old = urlparse(current_url)
        new = urlparse(next_url)
        # Never forward credentials to another origin. Ghost/LLM redirects should
        # remain on the configured origin; rejecting is safer than silently losing auth.
        if (old.scheme.lower(), old.hostname, old.port) != (new.scheme.lower(), new.hostname, new.port):
            if any(key.lower() in {"authorization", "x-api-key"} for key in current_headers):
                raise UnsafeUrlError(f"{field_name} redirected credentials to a different origin")
        next_method = _redirect_method(status, current_method)
        if next_method == "GET" and current_method != "GET":
            current_json = None
            current_data = None
            current_headers.pop("Content-Type", None)
            current_headers.pop("content-type", None)
        current_method = next_method
        current_url = next_url

    raise TooManyRedirectsError(f"{field_name} exceeded {max_redirects} redirects")
