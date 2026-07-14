"""SSRF-resistant HTTP client helpers for user-configured upstream services.

Each request hop is resolved exactly once, every resolved address must be public,
and aiohttp is given a resolver pinned to that validated address set. Redirects are
handled manually so every Location receives the same validation before connecting.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import socket
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urljoin, urlparse

import aiohttp
from aiohttp.abc import AbstractResolver
from aiohttp.abc import ResolveResult

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


def _parse_target(url: str, *, field_name: str = "URL") -> tuple[str, int]:
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
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
    if hostname.rstrip(".").lower() in _BLOCKED_HOSTS:
        raise UnsafeUrlError(f"{field_name} points to a local or metadata host")
    return hostname, port


def resolve_public_addresses(
    url: str, *, field_name: str = "URL", allow_test_loopback: bool = False
) -> tuple[str, int, tuple[str, ...]]:
    """Resolve one URL once and keep only globally routable addresses.

    A domain is accepted as long as it resolves to at least one global IP; only
    those global IPs are returned so the pinned resolver never reaches a private
    target. A purely private/loopback domain (no global IP) is still rejected.
    """
    hostname, port = _parse_target(url, field_name=field_name)
    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"{field_name} hostname could not be resolved") from exc
    addresses = tuple(dict.fromkeys(item[4][0].split("%", 1)[0] for item in infos))
    if not addresses:
        raise UnsafeUrlError(f"{field_name} hostname could not be resolved")
    test_mode = os.environ.get("TEAMAGENT_ENV") == "test" or bool(os.environ.get("PYTEST_CURRENT_TEST"))
    # 只要存在至少一个 global IP 即视为公网域名；返回集合只保留可用（global/测试回环）IP，
    # pinned resolver 只会连接这些 IP，实际请求不会打到内网；纯内网域名（无任何 global IP）仍被拒绝。
    # 此前要求"所有 IP 必须 global"会误杀同时解析出公网+保留/ULA 地址的合法域名（DNS 拦截、双栈等场景）。
    safe_addresses: list[str] = []
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise UnsafeUrlError(f"{field_name} resolved to an invalid address") from exc
        if ip.is_global or (allow_test_loopback and test_mode and ip.is_loopback):
            safe_addresses.append(address)
    if not safe_addresses:
        raise UnsafeUrlError(f"{field_name} points to a non-public address")
    return hostname, port, tuple(safe_addresses)


def assert_safe_http_url(url: str, *, field_name: str = "URL") -> None:
    resolve_public_addresses(url, field_name=field_name)


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


def create_pinned_client_session(
    url: str,
    *,
    timeout: aiohttp.ClientTimeout | float | None = None,
    field_name: str = "URL",
    allow_test_loopback: bool = False,
) -> aiohttp.ClientSession:
    """Create a one-origin session pinned to the URL's validated public IPs.

    The original hostname remains in request URLs, preserving HTTP Host, TLS SNI,
    and certificate hostname validation. The resolver refuses every other hostname
    and a trace hook rejects redirects even if a downstream client accidentally
    asks aiohttp to follow one. ``trust_env=False`` also prevents environment proxy
    settings from bypassing the pinned connector. Callers own and must close the
    returned session.
    """
    hostname, port, addresses = resolve_public_addresses(
        url, field_name=field_name, allow_test_loopback=allow_test_loopback
    )
    connector = aiohttp.TCPConnector(
        resolver=_PinnedResolver(hostname, port, addresses),
        use_dns_cache=False,
        ttl_dns_cache=0,
    )
    trace_config = aiohttp.TraceConfig()
    trace_config.on_request_redirect.append(_reject_redirect)
    if timeout is None:
        timeout_value: aiohttp.ClientTimeout = aiohttp.ClientTimeout(total=600)
    elif isinstance(timeout, (int, float)):
        timeout_value = aiohttp.ClientTimeout(total=float(timeout))
    else:
        timeout_value = timeout
    return aiohttp.ClientSession(
        timeout=timeout_value,
        connector=connector,
        trace_configs=[trace_config],
        trust_env=False,
    )


def _redirect_method(status: int, method: str) -> str:
    upper = method.upper()
    if status == 303 and upper != "HEAD":
        return "GET"
    if status in (301, 302) and upper == "POST":
        return "GET"
    return upper


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
        hostname, port, addresses = resolve_public_addresses(current_url, field_name=field_name)
        connector = aiohttp.TCPConnector(
            resolver=_PinnedResolver(hostname, port, addresses),
            use_dns_cache=False,
        )
        async with aiohttp.ClientSession(timeout=timeout_value, connector=connector) as session:
            async with session.request(
                current_method,
                current_url,
                headers=current_headers,
                json=current_json,
                data=current_data,
                allow_redirects=False,
                ssl=ssl,
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
