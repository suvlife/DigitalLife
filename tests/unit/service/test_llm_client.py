import socket

import pytest
from litellm.types.utils import ModelResponse, ModelResponseStream

from util import safeHttpUtil
from util.llmApiUtil import OpenAIMessage, OpenAIRequest, OpenAIUsage, OpenaiApiRole
from util.llmApiUtil import client as llm_client


def test_cache_injection_points_cover_system_and_last_message():
    assert llm_client._CACHE_INJECTION_POINTS == [
        {"location": "message", "role": "system"},
        {"location": "message", "index": -1},
    ]



def test_openai_usage_normalizes_legacy_cache_fields_into_prompt_cache_usage():
    usage = OpenAIUsage.model_validate({
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
        "prompt_tokens_details": {
            "cached_tokens": 75,
            "cache_creation_tokens": 30,
        },
        "cache_creation_input_tokens": 30,
        "cache_read_input_tokens": 75,
    })

    assert usage.prompt_cache_usage is not None
    assert usage.prompt_cache_usage.cached_tokens == 75
    assert usage.prompt_cache_usage.cache_write_tokens == 30


def test_openai_usage_keeps_none_distinct_from_zero_for_cached_tokens():
    usage = OpenAIUsage.model_validate({
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
        "cache_creation_input_tokens": 30,
        "cache_read_input_tokens": 0,
    })

    assert usage.prompt_cache_usage is not None
    assert usage.prompt_cache_usage.cached_tokens == 0
    assert usage.prompt_cache_usage.cache_write_tokens == 30


def test_openai_usage_normalizes_anthropic_cache_read_tokens_into_cached_tokens():
    usage = OpenAIUsage.model_validate({
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
        "cache_creation_input_tokens": 30,
        "cache_read_input_tokens": 55,
    })

    assert usage.prompt_cache_usage is not None
    assert usage.prompt_cache_usage.cached_tokens == 55
    assert usage.prompt_cache_usage.cache_write_tokens == 30


def _request(*, stream: bool = False) -> OpenAIRequest:
    return OpenAIRequest(
        model="test-model",
        messages=[OpenAIMessage.text(OpenaiApiRole.USER, "hello")],
        stream=stream,
    )


@pytest.mark.asyncio
async def test_non_stream_inference_pins_validated_dns_and_closes_session(monkeypatch):
    calls = 0
    captured = {}

    def changing_dns(host, port, **kwargs):
        nonlocal calls
        calls += 1
        address = "93.184.216.34" if calls == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))]

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        session = kwargs["shared_session"]
        resolver = session.connector._resolver
        resolved = await resolver.resolve("llm.example", 443)
        assert [item["host"] for item in resolved] == ["93.184.216.34"]
        assert "client" not in kwargs  # OpenAI-compatible path consumes shared_session directly.
        return ModelResponse(
            model="test-model",
            choices=[{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        )

    monkeypatch.setattr(safeHttpUtil.socket, "getaddrinfo", changing_dns)
    monkeypatch.setattr(llm_client.litellm, "acompletion", fake_acompletion)

    response = await llm_client.send_request_non_stream(
        _request(), "https://llm.example/v1", "secret", custom_llm_provider="openai"
    )

    assert response.choices[0].message.content == "ok"
    assert calls == 1
    assert captured["base_url"] == "https://llm.example/v1"
    assert captured["shared_session"].closed is True


@pytest.mark.asyncio
async def test_stream_inference_closes_wrapper_and_pinned_session(monkeypatch):
    closed = False
    captured = {}
    chunk = ModelResponseStream(
        model="test-model",
        choices=[{"index": 0, "delta": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
    )

    class FakeStreamWrapper:
        def __aiter__(self):
            async def iterator():
                yield chunk
            return iterator()

        async def aclose(self):
            nonlocal closed
            closed = True

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return FakeStreamWrapper()

    monkeypatch.setattr(safeHttpUtil.socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))
    ])
    monkeypatch.setattr(llm_client, "CustomStreamWrapper", FakeStreamWrapper)
    monkeypatch.setattr(llm_client.litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr(
        llm_client.litellm,
        "stream_chunk_builder",
        lambda **kwargs: ModelResponse(
            model="test-model",
            choices=[{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        ),
    )

    response = await llm_client.send_request_stream(
        _request(stream=True), "https://llm.example/v1", "secret", custom_llm_provider="anthropic"
    )

    assert response.choices[0].message.content == "ok"
    assert closed is True
    assert captured["shared_session"].closed is True


def test_unknown_provider_fails_closed_before_litellm_call():
    with pytest.raises(ValueError, match="不支持安全固定 DNS"):
        llm_client._build_secure_litellm_client("https://llm.example/v1", "unsafe-custom-provider")


@pytest.mark.asyncio
async def test_normal_inference_rejects_redirect_before_private_target(monkeypatch):
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        session = kwargs["shared_session"]
        redirect_hook = session.trace_configs[0].on_request_redirect[0]
        # LiteLLM's aiohttp transport already sends allow_redirects=False. The
        # session hook is a second fail-closed boundary if that behavior changes.
        await redirect_hook(session, object(), object())
        raise AssertionError("private redirect must never be followed")

    monkeypatch.setattr(safeHttpUtil.socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))
    ])
    monkeypatch.setattr(llm_client.litellm, "acompletion", fake_acompletion)

    with pytest.raises(safeHttpUtil.UnsafeUrlError, match="redirect"):
        await llm_client.send_request_non_stream(
            _request(), "https://llm.example/v1", "secret", custom_llm_provider="deepseek"
        )
    assert captured["shared_session"].closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai", "deepseek", "anthropic", "gemini"])
async def test_supported_agent_providers_receive_secure_transport(monkeypatch, provider):
    monkeypatch.setattr(safeHttpUtil.socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))
    ])
    session, client = llm_client._build_secure_litellm_client("https://llm.example/v1", provider)
    try:
        if provider in {"openai", "deepseek"}:
            assert client is None
        else:
            assert client.client._transport.client is session
        assert session.connector._resolver._hostname == "llm.example"
    finally:
        await session.close()
