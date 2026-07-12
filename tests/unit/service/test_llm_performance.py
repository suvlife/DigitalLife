import asyncio

import pytest

from service.llmService import core
from util.configTypes import LlmServiceConfig


def _service(name: str, *, max_concurrency: int = 5, rpm: int = 0) -> LlmServiceConfig:
    return LlmServiceConfig(
        name=name,
        base_url=f"https://{name}.example/v1",
        api_key="test",
        type="openai-compatible",
        model="mock",
        max_concurrency=max_concurrency,
        requests_per_minute=rpm,
    )


def setup_function():
    core.reset_request_gates_for_testing()


@pytest.mark.asyncio
async def test_service_gates_are_isolated_and_configurable():
    service_a = _service("a", max_concurrency=1)
    service_b = _service("b", max_concurrency=2)
    gate_a = core._get_service_request_gate(service_a)
    gate_b = core._get_service_request_gate(service_b)

    assert gate_a is not gate_b
    assert gate_a.max_concurrency == 1
    assert gate_b.max_concurrency == 2
    assert core._get_service_request_gate(service_a) is gate_a


@pytest.mark.asyncio
async def test_same_service_respects_its_own_concurrency_limit():
    gate = core._get_service_request_gate(_service("limited", max_concurrency=2))
    active = 0
    peak = 0

    async def worker():
        nonlocal active, peak
        async with gate.slot():
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1

    await asyncio.gather(*(worker() for _ in range(6)))
    assert peak == 2


@pytest.mark.asyncio
async def test_different_services_do_not_block_each_other():
    gate_a = core._get_service_request_gate(_service("slow", max_concurrency=1))
    gate_b = core._get_service_request_gate(_service("fast", max_concurrency=1))
    entered_a = asyncio.Event()
    release_a = asyncio.Event()

    async def hold_a():
        async with gate_a.slot():
            entered_a.set()
            await release_a.wait()

    task = asyncio.create_task(hold_a())
    await entered_a.wait()
    async def enter_fast_gate() -> None:
        async with gate_b.slot():
            pass

    await asyncio.wait_for(enter_fast_gate(), timeout=0.1)
    release_a.set()
    await task


@pytest.mark.asyncio
async def test_sliding_window_rate_limiter_waits_after_capacity(monkeypatch):
    limiter = core.SlidingWindowRateLimiter(2)
    now = 100.0
    sleeps: list[float] = []

    monkeypatch.setattr(core.time, "monotonic", lambda: now)

    async def fake_sleep(delay: float) -> None:
        nonlocal now
        sleeps.append(delay)
        now += delay

    monkeypatch.setattr(core.asyncio, "sleep", fake_sleep)
    assert await limiter.acquire() == 0
    assert await limiter.acquire() == 0
    waited = await limiter.acquire()
    assert waited == pytest.approx(60.0)
    assert sleeps == [pytest.approx(60.0)]


def test_config_performance_defaults_and_validation():
    service = _service("defaults")
    assert service.max_concurrency == 5
    assert service.requests_per_minute == 0
    with pytest.raises(ValueError):
        _service("invalid", max_concurrency=0)
