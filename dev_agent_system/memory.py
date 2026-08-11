"""Memory Agent：三层记忆（短期/工作/长期）与上下文压缩。

支持多种后端：
- short：内存字典
- working/long：Redis（可选） > ChromaDB（可选） > SQLite 降级
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol


class ContextCompressor:
    """基于字符数的简单上下文压缩：保留头部与尾部，中间省略。"""

    def __init__(self, max_chars: int = 8000, reserve_head: int = 2000):
        self.max_chars = max_chars
        self.reserve_head = reserve_head

    def compress(self, text: str) -> str:
        if len(text) <= self.max_chars:
            return text
        head = text[: self.reserve_head]
        tail = text[-(self.max_chars - self.reserve_head) :]
        return (
            head
            + "\n\n... [上下文压缩：中间内容已省略] ...\n\n"
            + tail
        )

    def compress_messages(self, messages: List[Dict[str, Any]], max_messages: int = 10) -> List[Dict[str, Any]]:
        """保留最近 max_messages 条记忆。"""
        return messages[-max_messages:]


class MemoryBackend(Protocol):
    """记忆后端协议。"""

    def remember(
        self,
        key: str,
        value: Any,
        session_id: str,
        layer: str,
        ttl: Optional[int] = None,
    ) -> None:
        ...

    def recall(
        self,
        query: str,
        session_id: str,
        layer: str,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        ...


class SQLiteMemoryBackend:
    """SQLite 降级实现。"""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
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
        session_id: str,
        layer: str,
        ttl: Optional[int] = None,
    ) -> None:
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
        session_id: str,
        layer: str,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        now = time.time()
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

    def close(self) -> None:
        self._db.close()


class RedisMemoryBackend:
    """Redis 后端（可选，未安装时降级）。"""

    def __init__(self, url: Optional[str] = None):
        import redis
        self._client = redis.from_url(url or os.getenv("REDIS_URL", "redis://localhost:6379/0"))

    def _key(self, session_id: str, layer: str, key: str) -> str:
        return f"dev_agent:{layer}:{session_id}:{key}"

    def remember(
        self,
        key: str,
        value: Any,
        session_id: str,
        layer: str,
        ttl: Optional[int] = None,
    ) -> None:
        full_key = self._key(session_id, layer, key)
        self._client.set(full_key, json.dumps(value, ensure_ascii=False), ex=ttl)

    def recall(
        self,
        query: str,
        session_id: str,
        layer: str,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        pattern = f"dev_agent:{layer}:{session_id}:*"
        keys = self._client.scan_iter(match=pattern, count=top_k * 10)
        rows = []
        for key in keys:
            value = self._client.get(key)
            if value is None:
                continue
            decoded = value.decode("utf-8") if isinstance(value, bytes) else value
            try:
                rows.append({"key": key.decode("utf-8") if isinstance(key, bytes) else key, "value": json.loads(decoded), "score": 1.0})
            except json.JSONDecodeError:
                rows.append({"key": key.decode("utf-8") if isinstance(key, bytes) else key, "value": decoded, "score": 1.0})
            if len(rows) >= top_k:
                break
        return rows


class ChromaMemoryBackend:
    """ChromaDB 后端（可选，未安装时降级），用于语义检索长期记忆。"""

    def __init__(self, base_dir: Path):
        import chromadb
        client = chromadb.PersistentClient(path=str(base_dir / "chroma_data"))
        self._collection = client.get_or_create_collection("memory")

    def remember(
        self,
        key: str,
        value: Any,
        session_id: str,
        layer: str,
        ttl: Optional[int] = None,
    ) -> None:
        doc_id = f"{layer}:{session_id}:{key}"
        self._collection.upsert(
            ids=[doc_id],
            documents=[json.dumps(value, ensure_ascii=False)],
            metadatas=[{"session_id": session_id, "layer": layer, "key": key, "expires_at": time.time() + ttl if ttl else 0}],
        )

    def recall(
        self,
        query: str,
        session_id: str,
        layer: str,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        results = self._collection.query(
            query_texts=[query],
            n_results=top_k,
            where={"session_id": session_id, "layer": layer},
        )
        rows = []
        for doc_id, doc, meta, dist in zip(
            results["ids"][0], results["documents"][0], results["metadatas"][0], results["distances"][0]
        ):
            try:
                value = json.loads(doc)
            except json.JSONDecodeError:
                value = doc
            rows.append({"key": meta.get("key", doc_id), "value": value, "score": 1.0 - dist})
        return rows


def _create_backend(base_dir: Path) -> MemoryBackend:
    backend = os.getenv("MEMORY_BACKEND", "sqlite").lower()
    if backend == "redis":
        try:
            return RedisMemoryBackend()
        except Exception as exc:  # noqa: BLE001
            print(f"[Memory] Redis 不可用，降级到 SQLite: {exc}")
            return SQLiteMemoryBackend(base_dir)
    if backend == "chroma":
        try:
            return ChromaMemoryBackend(base_dir)
        except Exception as exc:  # noqa: BLE001
            print(f"[Memory] ChromaDB 不可用，降级到 SQLite: {exc}")
            return SQLiteMemoryBackend(base_dir)
    return SQLiteMemoryBackend(base_dir)


class MemoryAgent:
    """统一记忆入口：短期记忆存内存，工作/长期记忆存后端。"""

    def __init__(self, base_dir: str = "memory_store"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._short: Dict[str, Dict[str, Any]] = {}
        self._backend = _create_backend(self.base_dir)

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
        self._backend.remember(key, value, session_id, layer, ttl)

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
        return self._backend.recall(query, session_id, layer, top_k)

    def summarize(self, history: List[Dict[str, Any]]) -> str:
        if not history:
            return ""
        parts = [f"- {h.get('agent','?')}: {str(h.get('output',''))[:120]}..." for h in history[-5:]]
        return "\n".join(parts)

    def compress_context(self, text: str, max_chars: int = 8000) -> str:
        return ContextCompressor(max_chars=max_chars).compress(text)

    def close(self) -> None:
        if hasattr(self._backend, "close"):
            self._backend.close()


# 保持旧接口兼容
MemoryAgentFacade = MemoryAgent
