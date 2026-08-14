"""Human-in-the-Loop 审批状态管理。

支持 SQLite 持久化，以便 Orchestrator、Server、Resume 等独立实例共享审批状态。
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from dev_agent_system.config import Settings


class HumanApprovalStore:
    """基于 SQLite 的人工审批状态存储。"""

    _instance: Optional["HumanApprovalStore"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls, db_path: Optional[Path] = None) -> "HumanApprovalStore":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._db_path = db_path or Settings.approval_db()
                    cls._instance._init_db()
        return cls._instance

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS approvals (
                    request_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _upsert(self, request_id: str, status: str) -> None:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                """
                INSERT INTO approvals (request_id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(request_id) DO UPDATE SET
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (request_id, status, now, now),
            )
            conn.commit()

    def request_approval(self, request_id: str) -> None:
        """将 request_id 标记为等待审批。"""
        self._upsert(request_id, "pending")

    def approve(self, request_id: str) -> None:
        """批准指定 request_id。"""
        self._upsert(request_id, "approved")

    def reject(self, request_id: str) -> None:
        """拒绝指定 request_id。"""
        self._upsert(request_id, "rejected")

    def is_approved(self, request_id: str) -> bool:
        return self.get_status(request_id) == "approved"

    def get_status(self, request_id: str) -> str:
        with sqlite3.connect(str(self._db_path)) as conn:
            cur = conn.execute(
                "SELECT status FROM approvals WHERE request_id = ?",
                (request_id,),
            )
            row = cur.fetchone()
        return row[0] if row else "not_found"

    def list_pending(self) -> List[Dict[str, Any]]:
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT request_id, status, created_at, updated_at FROM approvals WHERE status = 'pending' ORDER BY created_at DESC"
            )
            return [dict(row) for row in cur.fetchall()]
