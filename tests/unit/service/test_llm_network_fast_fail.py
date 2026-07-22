"""NETWORK_ERROR 快速失败链的单元测试（稳定性修复 #7）。

黑洞上游（连接建立但不响应）时，每个 attempt 都可能吃满读超时。若沿用默认
长重试链，单服务会卡住数十分钟才走 failover。修复后 NETWORK_ERROR 用短链
（最多 len(_NETWORK_ERROR_RETRY_DELAYS)+1 次尝试）快速判定服务不可用，
尽早切换兜底服务；而 RATE_LIMITED / SERVER_ERROR 仍保留完整长链。
"""
import pytest
from litellm.exceptions import APIConnectionError, InternalServerError

from service.llmService import core as llm_core


class _NoopGate:
    """绕过真实并发门/限流器的最小替身，slot() 直接 yield 零等待。"""

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def slot(self):
        yield 0.0, 0.0


def _metrics() -> llm_core.InferPerformanceMetrics:
    return llm_core.InferPerformanceMetrics()


def _conn_error(msg: str = "connection refused") -> APIConnectionError:
    return APIConnectionError(message=msg, llm_provider="openai", model="test-model")


def _server_error(msg: str = "upstream 500") -> InternalServerError:
    return InternalServerError(message=msg, llm_provider="openai", model="test-model")


@pytest.mark.asyncio
async def test_network_error_fails_fast_with_few_attempts(monkeypatch):
    """NETWORK_ERROR（连接错误/超时）应在短链后放弃，而非跑满默认长链。"""
    monkeypatch.setattr(llm_core, "_NETWORK_ERROR_RETRY_DELAYS", (0, 0))
    expected_max = len(llm_core._NETWORK_ERROR_RETRY_DELAYS) + 1

    calls = {"n": 0}

    async def _always_conn_error(*args, **kwargs):
        calls["n"] += 1
        raise _conn_error()

    with pytest.raises(APIConnectionError):
        await llm_core._send_with_retry(
            _always_conn_error, (), {"request_id": "r-net"},
            request_gate=_NoopGate(), metrics=_metrics(),
        )

    assert calls["n"] == expected_max
    # 快速失败链应显著短于默认长链
    assert calls["n"] < len(llm_core._INFER_RETRY_DELAYS_SECONDS) + 1


@pytest.mark.asyncio
async def test_server_error_keeps_full_retry_chain(monkeypatch):
    """SERVER_ERROR 不受快速失败影响，仍按默认长链重试。"""
    # 把退避全置 0，避免测试实际睡眠
    monkeypatch.setattr(llm_core, "_INFER_RETRY_DELAYS_SECONDS", tuple(0 for _ in llm_core._INFER_RETRY_DELAYS_SECONDS))
    expected_max = len(llm_core._INFER_RETRY_DELAYS_SECONDS) + 1

    calls = {"n": 0}

    async def _always_server_error(*args, **kwargs):
        calls["n"] += 1
        raise _server_error()

    with pytest.raises(InternalServerError):
        await llm_core._send_with_retry(
            _always_server_error, (), {"request_id": "r-srv"},
            request_gate=_NoopGate(), metrics=_metrics(),
        )

    assert calls["n"] == expected_max


@pytest.mark.asyncio
async def test_network_error_recovers_if_later_attempt_succeeds(monkeypatch):
    """快速失败链内若某次尝试成功，应正常返回结果。"""
    monkeypatch.setattr(llm_core, "_NETWORK_ERROR_RETRY_DELAYS", (0, 0))

    calls = {"n": 0}

    async def _flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            raise _conn_error("transient conn error")
        return "ok"

    result = await llm_core._send_with_retry(
        _flaky, (), {"request_id": "r-flaky"},
        request_gate=_NoopGate(), metrics=_metrics(),
    )
    assert result == "ok"
    assert calls["n"] == 2
