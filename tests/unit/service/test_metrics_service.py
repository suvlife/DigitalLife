"""metricsService 轻量指标服务的单元测试。"""
from service import metricsService


def setup_function():
    metricsService.reset_for_testing()


def test_counter_increments():
    metricsService.inc_counter("http_requests_total")
    metricsService.inc_counter("http_requests_total", 4)
    m = metricsService.get_metrics()
    assert m["counters"]["http_requests_total"] == 5


def test_labeled_counter_by_dimension():
    metricsService.inc_labeled("http_requests_by_status", status_class="2xx")
    metricsService.inc_labeled("http_requests_by_status", status_class="2xx")
    metricsService.inc_labeled("http_requests_by_status", status_class="5xx")
    m = metricsService.get_metrics()
    series = m["labeled_counters"]["http_requests_by_status"]
    assert series["status_class=2xx"] == 2
    assert series["status_class=5xx"] == 1


def test_gauge_set_and_read():
    metricsService.set_gauge("active_rooms", 7)
    m = metricsService.get_metrics()
    assert m["gauges"]["active_rooms"] == 7


def test_uptime_present():
    m = metricsService.get_metrics()
    assert "uptime_seconds" in m
    assert m["uptime_seconds"] >= 0
