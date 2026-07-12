from __future__ import annotations

import socket

import pytest
from yarl import URL

from util import safeHttpUtil


class _Response:
    def __init__(self, status: int, url: str, *, headers=None, body=b"") -> None:
        self.status = status
        self.url = URL(url)
        self.headers = headers or {}
        self._body = body

    async def read(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _Session:
    responses: list[_Response] = []
    connectors = []
    requests = []

    def __init__(self, *, connector, **kwargs):
        self.connector = connector
        self.__class__.connectors.append(connector)

    def request(self, method, url, **kwargs):
        self.__class__.requests.append((method, url, kwargs))
        return self.__class__.responses.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


@pytest.fixture(autouse=True)
def _reset_session():
    _Session.responses = []
    _Session.connectors = []
    _Session.requests = []


def _public(*args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))]


@pytest.mark.asyncio
async def test_redirect_to_private_address_is_rejected_before_second_connection(monkeypatch):
    def resolve(host, port, **kwargs):
        address = "93.184.216.34" if host == "public.example" else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))]

    monkeypatch.setattr(safeHttpUtil.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(safeHttpUtil.aiohttp, "ClientSession", _Session)
    _Session.responses = [_Response(302, "https://public.example/start", headers={"Location": "https://private.example/admin"})]

    with pytest.raises(safeHttpUtil.UnsafeUrlError, match="non-public"):
        await safeHttpUtil.request("GET", "https://public.example/start")
    assert len(_Session.requests) == 1


@pytest.mark.asyncio
async def test_redirect_loop_is_rejected(monkeypatch):
    monkeypatch.setattr(safeHttpUtil.socket, "getaddrinfo", _public)
    monkeypatch.setattr(safeHttpUtil.aiohttp, "ClientSession", _Session)
    _Session.responses = [
        _Response(302, "https://public.example/a", headers={"Location": "/b"}),
        _Response(302, "https://public.example/b", headers={"Location": "/a"}),
    ]

    with pytest.raises(safeHttpUtil.TooManyRedirectsError, match="loop"):
        await safeHttpUtil.request("GET", "https://public.example/a")
    assert len(_Session.requests) == 2
    assert all(request[2]["allow_redirects"] is False for request in _Session.requests)


@pytest.mark.asyncio
async def test_dns_is_resolved_once_and_pinned_for_connection(monkeypatch):
    calls = 0

    def changing_dns(host, port, **kwargs):
        nonlocal calls
        calls += 1
        address = "93.184.216.34" if calls == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))]

    monkeypatch.setattr(safeHttpUtil.socket, "getaddrinfo", changing_dns)
    monkeypatch.setattr(safeHttpUtil.aiohttp, "ClientSession", _Session)
    _Session.responses = [_Response(200, "https://public.example/v1", body=b"ok")]

    response = await safeHttpUtil.request("GET", "https://public.example/v1")
    assert response.text == "ok"
    assert calls == 1
    resolver = _Session.connectors[0]._resolver
    pinned = await resolver.resolve("public.example", 443)
    assert [item["host"] for item in pinned] == ["93.184.216.34"]
    # URL hostname is retained, so aiohttp performs TLS SNI/certificate validation
    # for public.example while the connector reaches only the pinned IP.
    assert _Session.requests[0][1] == "https://public.example/v1"


@pytest.mark.asyncio
async def test_redirect_limit_is_enforced(monkeypatch):
    monkeypatch.setattr(safeHttpUtil.socket, "getaddrinfo", _public)
    monkeypatch.setattr(safeHttpUtil.aiohttp, "ClientSession", _Session)
    _Session.responses = [
        _Response(302, "https://public.example/0", headers={"Location": "/1"}),
        _Response(302, "https://public.example/1", headers={"Location": "/2"}),
    ]
    with pytest.raises(safeHttpUtil.TooManyRedirectsError, match="exceeded 1"):
        await safeHttpUtil.request("GET", "https://public.example/0", max_redirects=1)

@pytest.mark.asyncio
async def test_cross_origin_redirect_does_not_forward_authorization(monkeypatch):
    monkeypatch.setattr(safeHttpUtil.socket, "getaddrinfo", _public)
    monkeypatch.setattr(safeHttpUtil.aiohttp, "ClientSession", _Session)
    _Session.responses = [
        _Response(302, "https://public.example/start", headers={"Location": "https://other.example/next"}),
    ]
    with pytest.raises(safeHttpUtil.UnsafeUrlError, match="credentials"):
        await safeHttpUtil.request(
            "GET", "https://public.example/start", headers={"Authorization": "Bearer secret"}
        )
    assert len(_Session.requests) == 1


@pytest.mark.asyncio
async def test_pinned_session_rejects_redirect_before_following_private_location(monkeypatch):
    monkeypatch.setattr(safeHttpUtil.socket, "getaddrinfo", _public)
    session = safeHttpUtil.create_pinned_client_session("https://public.example/v1")
    try:
        hook = session.trace_configs[0].on_request_redirect[0]
        with pytest.raises(safeHttpUtil.UnsafeUrlError, match="redirect"):
            await hook(session, object(), object())
        resolver = session.connector._resolver
        with pytest.raises(OSError, match="unvalidated"):
            await resolver.resolve("127.0.0.1", 443)
    finally:
        await session.close()
