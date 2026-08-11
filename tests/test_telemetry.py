"""Telemetry 模块单元测试。"""
from __future__ import annotations

from dev_agent_system.metrics import MetricsCollector
from dev_agent_system.telemetry import Telemetry


def test_span_records_duration_and_status(caplog):
    collector = MetricsCollector()
    telemetry = Telemetry(collector=collector)
    with caplog.at_level("INFO", logger="dev_agent_system.telemetry"):
        with telemetry.span("test.span"):
            pass
    assert any("test.span" in record.message for record in caplog.records)
    spans = collector._metrics.get("spans_total")
    assert spans is not None
    assert sum(spans._values.values()) == 1.0


def test_span_error_status_on_exception(caplog):
    collector = MetricsCollector()
    telemetry = Telemetry(collector=collector)
    try:
        with telemetry.span("failing.span"):
            raise ValueError("boom")
    except ValueError:
        pass
    spans = collector._metrics["spans_total"]
    assert sum(spans._values.values()) == 1.0
    # 错误状态 bucket 应存在
    assert any("error" in str(key) for key in spans._values)


def test_record_event_increments_event_counter():
    collector = MetricsCollector()
    telemetry = Telemetry(collector=collector)
    telemetry.record_event("test_event", payload="x")
    events = collector._metrics["events_total"]
    assert events._values[("test_event",)] == 1.0


def test_nested_spans_parent_restored():
    telemetry = Telemetry()
    with telemetry.span("outer"):
        outer = telemetry.get_current_span()
        with telemetry.span("inner"):
            assert telemetry.get_current_span().name == "inner"
            assert telemetry.get_current_span().parent is outer
        assert telemetry.get_current_span() is outer
