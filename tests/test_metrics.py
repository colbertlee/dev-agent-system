"""Metrics 模块单元测试。"""
from __future__ import annotations

from dev_agent_system.metrics import DEFAULT as DEFAULT_METRICS, MetricsCollector


def test_counter_increment():
    collector = MetricsCollector()
    counter = collector.counter("test_counter", "A test counter")
    counter.inc()
    counter.inc()
    assert counter._values[()] == 2.0


def test_counter_with_labels():
    collector = MetricsCollector()
    counter = collector.counter("test_counter", "A test counter", labelnames=["agent"])
    counter.inc(agent="coder")
    counter.inc(agent="coder")
    counter.inc(agent="tester")
    assert counter._values[("coder",)] == 2.0
    assert counter._values[("tester",)] == 1.0


def test_gauge_set_and_inc_dec():
    collector = MetricsCollector()
    gauge = collector.gauge("test_gauge", "A test gauge")
    gauge.set(10)
    gauge.inc(2)
    gauge.dec(3)
    assert gauge._values[()] == 9.0


def test_histogram_observe():
    collector = MetricsCollector()
    histogram = collector.histogram("test_histogram", "A test histogram")
    histogram.observe(0.05)
    histogram.observe(1.5)
    histogram.observe(5.5)
    values = histogram._values[()]
    assert len(values) == 3


def test_prometheus_render_contains_help_and_type():
    collector = MetricsCollector()
    counter = collector.counter("render_test", "desc for render")
    counter.inc()
    text = collector.render_prometheus()
    assert "# HELP render_test desc for render" in text
    assert "# TYPE render_test counter" in text
    assert "render_test 1.0" in text


def test_prometheus_histogram_render():
    collector = MetricsCollector()
    histogram = collector.histogram("latency", "latency in seconds")
    histogram.observe(0.05)
    text = collector.render_prometheus()
    assert "# TYPE latency histogram" in text
    assert "latency_bucket{le=\"0.05\"}" in text or "latency_bucket{le=\"0.05\"" in text
    assert "latency_sum" in text
    assert "latency_count" in text


def test_default_collector_is_singleton():
    c1 = DEFAULT_METRICS
    c2 = DEFAULT_METRICS
    assert c1 is c2
