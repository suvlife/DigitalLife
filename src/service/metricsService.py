"""轻量进程内指标（metrics）服务。

零外部依赖的计数器 / 仪表盘集合，供 /system/metrics.json 暴露与告警判定使用。
不引入 Prometheus 客户端，避免新增重型依赖；如需对接 Prometheus，可在该模块
之上再包一层文本导出。所有操作均为 O(1) 且线程安全（单进程 asyncio 单线程模型，
计数用普通 dict 即可）。
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict

_start_time = time.time()
_lock = threading.Lock()

# 计数器：单调递增（如 http_requests_total、llm_infer_total）
_counters: dict[str, float] = defaultdict(float)
# 仪表盘：瞬时值（如 active_rooms、db_ready）
_gauges: dict[str, float] = {}
# 按标签维度的计数器（如 http_requests_total{path=...,status=...}）
_labeled_counters: dict[str, dict[tuple, float]] = defaultdict(lambda: defaultdict(float))


def inc_counter(name: str, amount: float = 1.0) -> None:
    with _lock:
        _counters[name] += amount


def inc_labeled(name: str, amount: float = 1.0, **labels: str) -> None:
    key = tuple(sorted(labels.items()))
    with _lock:
        _labeled_counters[name][key] += amount


def set_gauge(name: str, value: float) -> None:
    with _lock:
        _gauges[name] = value


def get_metrics() -> dict:
    """导出当前全部指标（dict 形式，供 JSON 序列化）。"""
    with _lock:
        return {
            "uptime_seconds": round(time.time() - _start_time, 1),
            "counters": dict(_counters),
            "gauges": dict(_gauges),
            "labeled_counters": {
                name: {",".join(f"{k}={v}" for k, v in key): val for key, val in series.items()}
                for name, series in _labeled_counters.items()
            },
        }


def reset_for_testing() -> None:
    with _lock:
        _counters.clear()
        _gauges.clear()
        _labeled_counters.clear()
