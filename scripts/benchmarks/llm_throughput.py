#!/usr/bin/env python3
"""Mock LLM throughput benchmark for serial vs per-service concurrent execution."""
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from service.llmService.core import ServiceRequestGate  # noqa: E402


async def run_case(*, requests: int, latency: float, concurrency: int) -> dict[str, float]:
    gate = ServiceRequestGate(concurrency, 0)
    latencies: list[float] = []

    async def mock_request() -> None:
        started = time.perf_counter()
        async with gate.slot():
            await asyncio.sleep(latency)
        latencies.append(time.perf_counter() - started)

    started = time.perf_counter()
    await asyncio.gather(*(mock_request() for _ in range(requests)))
    elapsed = time.perf_counter() - started
    return {
        "elapsed": elapsed,
        "throughput": requests / elapsed,
        "mean_latency": statistics.mean(latencies),
        "p95_latency": sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)],
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--latency-ms", type=float, default=100)
    parser.add_argument("--concurrency", type=int, default=5)
    args = parser.parse_args()

    serial = await run_case(requests=args.requests, latency=args.latency_ms / 1000, concurrency=1)
    parallel = await run_case(requests=args.requests, latency=args.latency_ms / 1000, concurrency=args.concurrency)
    speedup = serial["elapsed"] / parallel["elapsed"]
    print(f"requests={args.requests} mock_latency_ms={args.latency_ms:.1f}")
    print(f"serial:   elapsed={serial['elapsed']:.3f}s throughput={serial['throughput']:.2f} req/s p95={serial['p95_latency']*1000:.1f}ms")
    print(f"parallel: elapsed={parallel['elapsed']:.3f}s throughput={parallel['throughput']:.2f} req/s p95={parallel['p95_latency']*1000:.1f}ms concurrency={args.concurrency}")
    print(f"speedup:  {speedup:.2f}x")


if __name__ == "__main__":
    asyncio.run(main())
