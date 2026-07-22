"""alertService 主动告警的单元测试（webhook 出口、节流、no-op）。"""
import pytest

from service import alertService


def setup_function():
    alertService.reset_for_testing()


def test_noop_when_disabled(monkeypatch):
    """未启用/未配置 webhook 时不发送、不报错。"""
    monkeypatch.setattr(alertService, "_get_alert_config", lambda: (None, False))
    # 不应抛异常
    alertService.alert_task_failed(1, 100, "boom")


def test_throttle_same_event_key(monkeypatch):
    """同类事件在节流窗口内只发送一次。"""
    monkeypatch.setattr(alertService, "_get_alert_config", lambda: ("https://hook.example/x", True))
    sent = []

    class _FakeLoop:
        def create_task(self, coro):
            sent.append(coro)
            coro.close()  # 避免未 await 警告
            class _T:
                def add_done_callback(self, cb): pass
            return _T()

    monkeypatch.setattr(alertService.asyncio, "get_running_loop", lambda: _FakeLoop())
    alertService.send_alert("task_failed", "t1")
    alertService.send_alert("task_failed", "t2")  # 应被节流
    assert len(sent) == 1


def test_different_event_keys_not_throttled(monkeypatch):
    """不同 event_key 各自独立，不互相节流。"""
    monkeypatch.setattr(alertService, "_get_alert_config", lambda: ("https://hook.example/x", True))
    sent = []

    class _FakeLoop:
        def create_task(self, coro):
            sent.append(coro)
            coro.close()
            class _T:
                def add_done_callback(self, cb): pass
            return _T()

    monkeypatch.setattr(alertService.asyncio, "get_running_loop", lambda: _FakeLoop())
    alertService.send_alert("task_failed", "t1")
    alertService.send_alert("llm_rate_limited", "t2")
    assert len(sent) == 2


def test_format_text_contains_fields():
    text = alertService._format_text("标题", {"agent_id": 3, "error": "x"})
    assert "标题" in text
    assert "agent_id: 3" in text
    assert "error: x" in text
