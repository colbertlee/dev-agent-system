"""工作流全局状态追踪，供 TUI 与 Web Dashboard 消费。"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class WorkflowRecord:
    request_id: str
    input: str = ""
    status: str = "submitted"
    iteration: int = 0
    current_agent: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    artifacts: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class WorkflowTracker:
    """内存级工作流状态追踪器（单例）。"""

    _instance: Optional["WorkflowTracker"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "WorkflowTracker":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._records: Dict[str, WorkflowRecord] = {}
                    cls._instance._mutex = threading.Lock()
        return cls._instance

    def start(self, request_id: str, input_text: str = "") -> None:
        with self._mutex:
            self._records[request_id] = WorkflowRecord(
                request_id=request_id,
                input=input_text,
                status="submitted",
            )

    def update(self, request_id: str, **kwargs: Any) -> None:
        with self._mutex:
            record = self._records.get(request_id)
            if record is None:
                record = WorkflowRecord(request_id=request_id)
                self._records[request_id] = record
            for key, value in kwargs.items():
                if hasattr(record, key):
                    setattr(record, key, value)

    def finish(self, request_id: str, state: Dict[str, Any]) -> None:
        with self._mutex:
            record = self._records.get(request_id)
            if record is None:
                record = WorkflowRecord(request_id=request_id)
                self._records[request_id] = record
            record.status = state.get("status", "completed")
            record.iteration = state.get("iteration", record.iteration)
            record.finished_at = time.time()
            record.artifacts = state.get("artifacts") or record.artifacts
            record.current_agent = ""

    def get(self, request_id: str) -> Optional[WorkflowRecord]:
        with self._mutex:
            return self._records.get(request_id)

    def list(self, limit: int = 50) -> List[WorkflowRecord]:
        with self._mutex:
            records = list(self._records.values())
        records.sort(key=lambda r: r.started_at, reverse=True)
        return records[:limit]

    def snapshot(self, request_id: str) -> Dict[str, Any]:
        record = self.get(request_id)
        if record is None:
            return {}
        return {
            "request_id": record.request_id,
            "input": record.input,
            "status": record.status,
            "iteration": record.iteration,
            "current_agent": record.current_agent,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
            "elapsed_seconds": (
                (record.finished_at or time.time()) - record.started_at
            ),
            "artifacts": record.artifacts,
            "error": record.error,
        }

    def all_snapshots(self, limit: int = 50) -> List[Dict[str, Any]]:
        return [self.snapshot(r.request_id) for r in self.list(limit)]
