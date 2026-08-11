"""可观测性：链路追踪、结构化日志与 OpenTelemetry 风格 Span。"""
from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional

from dev_agent_system.metrics import DEFAULT as DEFAULT_METRICS, MetricsCollector


# 当前活跃 Span 的上下文变量
current_span_var: contextvars.ContextVar[Optional["Span"]] = contextvars.ContextVar(
    "current_span", default=None
)


class Span:
    """OpenTelemetry 风格 Span，支持嵌套与事件记录。"""

    def __init__(
        self,
        tracer: "Telemetry",
        name: str,
        attributes: Optional[Dict[str, Any]] = None,
    ):
        self.tracer = tracer
        self.name = name
        self.span_id = uuid.uuid4().hex[:16]
        self.parent = current_span_var.get(None)
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.attributes = attributes or {}
        self.events: List[Dict[str, Any]] = []

    def __enter__(self) -> "Span":
        current_span_var.set(self)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.end(exc=exc_val)
        current_span_var.set(self.parent)

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def add_event(self, name: str, **attributes: Any) -> None:
        self.events.append(
            {"name": name, "timestamp": time.time(), "attributes": attributes}
        )

    def end(self, exc: Optional[BaseException] = None) -> None:
        if self.end_time is not None:
            return
        self.end_time = time.time()
        duration = self.end_time - self.start_time
        status = "error" if exc else "ok"

        # 同时写入指标
        self.tracer.collector.counter(
            "spans_total",
            "Total number of spans",
            labelnames=["name", "status"],
        ).inc(name=self.name, status=status)

        self.tracer.collector.histogram(
            "span_duration_seconds",
            "Span duration in seconds",
            labelnames=["name"],
        ).observe(duration, name=self.name)

        record = {
            "type": "span",
            "name": self.name,
            "span_id": self.span_id,
            "duration": round(duration, 4),
            "status": status,
            "attributes": self.attributes,
            "events": self.events,
            "timestamp": self.end_time,
        }
        self.tracer.logger.info(json.dumps(record, ensure_ascii=False))


class Telemetry:
    """统一可观测性入口：链路追踪 + 结构化日志 + 指标上报。"""

    def __init__(self, collector: Optional[MetricsCollector] = None) -> None:
        self.collector = collector or DEFAULT_METRICS
        self.logger = logging.getLogger("dev_agent_system.telemetry")
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            self.logger.addHandler(logging.NullHandler())

    def start_span(
        self, name: str, attributes: Optional[Dict[str, Any]] = None
    ) -> Span:
        return Span(self, name, attributes)

    @contextmanager
    def span(
        self, name: str, attributes: Optional[Dict[str, Any]] = None
    ) -> Generator[Span, None, None]:
        with self.start_span(name, attributes) as span:
            yield span

    def get_current_span(self) -> Optional[Span]:
        return current_span_var.get(None)

    def record_event(self, name: str, **attributes: Any) -> None:
        span = self.get_current_span()
        if span:
            span.add_event(name, **attributes)
        self.collector.counter(
            "events_total",
            "Total number of telemetry events",
            labelnames=["name"],
        ).inc(name=name)
        self.logger.info(
            json.dumps(
                {"type": "event", "name": name, "attributes": attributes},
                ensure_ascii=False,
            )
        )


# 进程级默认 Telemetry 实例
DEFAULT = Telemetry()
