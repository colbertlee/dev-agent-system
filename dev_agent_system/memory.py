"""Memory Agent：三层记忆（短期/工作/长期）的降级实现。"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


class MemoryAgent:
    """管理短期（内存）、工作（ChromaDB 降级为 SQLite）和长期记忆。"""

    def __init__(self, base_dir: str = "memory_store"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._short: Dict[str, Dict[str, Any]] = {}
        self._db = sqlite3.connect(str(self.base_dir / "memory.db"), check_same_thread=False)
        self._init_tables()

    def _init_tables(self) -> None:
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS memory ("
            "id TEXT PRIMARY KEY, session_id TEXT, layer TEXT, key TEXT, "
            "value TEXT, created_at REAL, expires_at REAL)"
        )
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_layer_session ON memory(layer, session_id)"
        )
        self._db.commit()

    def remember(
        self,
        key: str,
        value: Any,
        session_id: str = "default",
        layer: str = "short",
        ttl: Optional[int] = None,
    ) -> None:
        if layer == "short":
            self._short.setdefault(session_id, {})[key] = {
                "value": value,
                "expires_at": time.time() + ttl if ttl else None,
            }
            return
        now = time.time()
        expires = now + ttl if ttl else 0
        self._db.execute(
            "REPLACE INTO memory (id, session_id, layer, key, value, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), session_id, layer, key, json.dumps(value, ensure_ascii=False), now, expires),
        )
        self._db.commit()

    def recall(
        self,
        query: str,
        session_id: str = "default",
        layer: str = "working",
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        now = time.time()
        if layer == "short":
            session = self._short.get(session_id, {})
            return [
                {"key": k, "value": v["value"], "score": 1.0}
                for k, v in session.items()
                if v.get("expires_at") is None or v["expires_at"] > now
            ][:top_k]
        cursor = self._db.execute(
            "SELECT key, value FROM memory WHERE session_id=? AND layer=? "
            "AND (expires_at=0 OR expires_at>?) ORDER BY created_at DESC LIMIT ?",
            (session_id, layer, now, top_k),
        )
        rows = []
        for key, value in cursor.fetchall():
            try:
                rows.append({"key": key, "value": json.loads(value), "score": 1.0})
            except json.JSONDecodeError:
                rows.append({"key": key, "value": value, "score": 1.0})
        return rows

    def summarize(self, history: List[Dict[str, Any]]) -> str:
        if not history:
            return ""
        parts = [f"- {h.get('agent','?')}: {str(h.get('output',''))[:120]}..." for h in history[-5:]]
        return "\n".join(parts)

    def close(self) -> None:
        self._db.close()
