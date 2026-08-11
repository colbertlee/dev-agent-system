"""轻量级指标收集器，支持 Prometheus 文本协议暴露。"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple, Union


DEFAULT_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    float("inf"),
)


@dataclass
class Counter:
    name: str
    description: str
    labelnames: Tuple[str, ...] = ()
    _values: Dict[Tuple[str, ...], float] = field(default_factory=dict)

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = self._key(**labels)
        self._values[key] = self._values.get(key, 0.0) + amount

    def _key(self, **labels: str) -> Tuple[str, ...]:
        return tuple(labels.get(k, "") for k in self.labelnames)

    def render(self) -> List[str]:
        lines = [f"# HELP {self.name} {self.description}", f"# TYPE {self.name} counter"]
        if not self._values:
            lines.append(f"{self.name} 0")
        for key, value in self._values.items():
            label_str = self._label_str(key)
            lines.append(f"{self.name}{label_str} {value}")
        return lines

    def _label_str(self, key: Tuple[str, ...]) -> str:
        if not self.labelnames:
            return ""
        pairs = ",".join(f'{k}="{v}"' for k, v in zip(self.labelnames, key))
        return "{" + pairs + "}"


@dataclass
class Gauge:
    name: str
    description: str
    labelnames: Tuple[str, ...] = ()
    _values: Dict[Tuple[str, ...], float] = field(default_factory=dict)

    def set(self, value: float, **labels: str) -> None:
        key = self._key(**labels)
        self._values[key] = value

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = self._key(**labels)
        self._values[key] = self._values.get(key, 0.0) + amount

    def dec(self, amount: float = 1.0, **labels: str) -> None:
        self.inc(-amount, **labels)

    def _key(self, **labels: str) -> Tuple[str, ...]:
        return tuple(labels.get(k, "") for k in self.labelnames)

    def render(self) -> List[str]:
        lines = [f"# HELP {self.name} {self.description}", f"# TYPE {self.name} gauge"]
        if not self._values:
            lines.append(f"{self.name} 0")
        for key, value in self._values.items():
            label_str = self._label_str(key)
            lines.append(f"{self.name}{label_str} {value}")
        return lines

    def _label_str(self, key: Tuple[str, ...]) -> str:
        if not self.labelnames:
            return ""
        pairs = ",".join(f'{k}="{v}"' for k, v in zip(self.labelnames, key))
        return "{" + pairs + "}"


@dataclass
class Histogram:
    name: str
    description: str
    buckets: Tuple[float, ...] = DEFAULT_BUCKETS
    labelnames: Tuple[str, ...] = ()
    _values: Dict[Tuple[str, ...], List[float]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def observe(self, value: float, **labels: str) -> None:
        key = self._key(**labels)
        self._values[key].append(value)

    def _key(self, **labels: str) -> Tuple[str, ...]:
        return tuple(labels.get(k, "") for k in self.labelnames)

    def render(self) -> List[str]:
        lines = [f"# HELP {self.name} {self.description}", f"# TYPE {self.name} histogram"]
        for key, values in self._values.items():
            total = sum(values)
            count = len(values)
            label_str = self._label_str(key)
            for bucket in self.buckets:
                le = "+Inf" if bucket == float("inf") else str(bucket)
                bucket_count = sum(1 for v in values if v <= bucket)
                lines.append(f"{self.name}_bucket{{le=\"{le}\"{self._extra_labels(key)}}} {bucket_count}")
            lines.append(f"{self.name}_sum{label_str} {total}")
            lines.append(f"{self.name}_count{label_str} {count}")
        if not self._values:
            for bucket in self.buckets:
                le = "+Inf" if bucket == float("inf") else str(bucket)
                lines.append(f"{self.name}_bucket{{le=\"{le}\"}} 0")
            lines.append(f"{self.name}_sum 0")
            lines.append(f"{self.name}_count 0")
        return lines

    def _label_str(self, key: Tuple[str, ...]) -> str:
        if not self.labelnames:
            return ""
        pairs = ",".join(f'{k}="{v}"' for k, v in zip(self.labelnames, key))
        return "{" + pairs + "}"

    def _extra_labels(self, key: Tuple[str, ...]) -> str:
        if not self.labelnames:
            return ""
        pairs = ",".join(f'{k}="{v}"' for k, v in zip(self.labelnames, key))
        return "," + pairs


class MetricsCollector:
    """内存指标收集器，线程安全，支持 Prometheus 文本渲染。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._metrics: Dict[str, MetricLike] = {}

    def counter(
        self, name: str, description: str, labelnames: Optional[List[str]] = None
    ) -> Counter:
        with self._lock:
            if name not in self._metrics:
                self._metrics[name] = Counter(
                    name=name,
                    description=description,
                    labelnames=tuple(labelnames or []),
                )
            return self._metrics[name]  # type: ignore[return-value]

    def gauge(
        self, name: str, description: str, labelnames: Optional[List[str]] = None
    ) -> Gauge:
        with self._lock:
            if name not in self._metrics:
                self._metrics[name] = Gauge(
                    name=name,
                    description=description,
                    labelnames=tuple(labelnames or []),
                )
            return self._metrics[name]  # type: ignore[return-value]

    def histogram(
        self,
        name: str,
        description: str,
        labelnames: Optional[List[str]] = None,
        buckets: Optional[Tuple[float, ...]] = None,
    ) -> Histogram:
        with self._lock:
            if name not in self._metrics:
                self._metrics[name] = Histogram(
                    name=name,
                    description=description,
                    buckets=buckets or DEFAULT_BUCKETS,
                    labelnames=tuple(labelnames or []),
                )
            return self._metrics[name]  # type: ignore[return-value]

    def render_prometheus(self) -> str:
        with self._lock:
            lines: List[str] = []
            for metric in self._metrics.values():
                lines.extend(metric.render())
                lines.append("")
        return "\n".join(lines)

    def time(self, histogram: Histogram, **labels: str) -> Callable[..., None]:
        """返回一个上下文管理器/装饰器，用于记录耗时。"""
        start = time.monotonic()

        def _done() -> None:
            histogram.observe(time.monotonic() - start, **labels)

        return _done


MetricLike = Union[Counter, Gauge, Histogram]


# 进程级默认收集器，便于跨模块复用
DEFAULT = MetricsCollector()
