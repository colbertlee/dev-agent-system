"""Memory Agent：三层记忆（短期/工作/长期）与上下文压缩。

主要改进：
- 统一召回语义：SQLite/Redis/Chroma 都支持 query，按「关键词 + 时效 + 语义」混合打分，
  不再因后端不同而在「最近 N 条」和「语义最相关」之间行为突变。
- 生命周期治理：TTL 过期清理、容量上限驱逐、写后即时整理。
- 并发安全：SQLite 后端使用 threading 锁 + WAL；MemoryAgent 提供 aremember/arecall，
  在 async 编排器中通过 asyncio.to_thread + asyncio.Lock 避免阻塞和竞争。
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple

from dev_agent_system.config import Settings


def _value_to_text(value: Any) -> str:
    """把任意 value 转成可搜索的文本。"""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        return str(value)


def _tokenize(text: str) -> List[str]:
    """简单分词：保留字母数字词，并把非 ASCII 字符单独切分（用于中文等）。"""
    text = (text or "").lower()
    tokens: List[str] = re.findall(r"[a-z0-9]+", text)
    tokens.extend(ch for ch in text if ord(ch) > 127 and not ch.isspace())
    return tokens


def _keyword_score(query: str, key: str, value: Any) -> float:
    """基于 query 与 key/value 文本的命中情况计算 0-1 的关键词分。"""
    query = (query or "").strip()
    if not query:
        return 1.0
    terms = set(_tokenize(query))
    if not terms:
        return 1.0
    text = _value_to_text(value)
    full_text = f"{key} {text}".lower()
    matched = sum(1 for term in terms if term in full_text)
    tf = sum(full_text.count(term) for term in terms)
    idf_part = matched / len(terms)
    tf_part = min(1.0, tf / (len(terms) * 3 + 1))
    return min(1.0, idf_part * 0.7 + tf_part * 0.3)


def _recency_score(created_at: float, now: Optional[float] = None) -> float:
    """时效分：越近越高，24 小时大约衰减到 0.37。"""
    now = now or time.time()
    hours = (now - created_at) / 3600.0
    return math.exp(-hours / 24.0)


def _combine_scores(
    keyword: float,
    recency: float,
    semantic: float = 0.0,
    has_semantic: bool = False,
) -> float:
    """混合召回打分。有语义时三者加权；无语义时关键词+时效。"""
    if has_semantic:
        return 0.4 * semantic + 0.35 * keyword + 0.25 * recency
    return 0.6 * keyword + 0.4 * recency


def _score_candidate(
    query: str,
    key: str,
    value: Any,
    created_at: float,
    semantic: float = 0.0,
    has_semantic: bool = False,
) -> float:
    """对单个候选记忆打分。"""
    query = (query or "").strip()
    if not query:
        return _recency_score(created_at)
    kw = _keyword_score(query, key, value)
    rec = _recency_score(created_at)
    return _combine_scores(kw, rec, semantic, has_semantic)


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
        max_candidates: int = 100,
    ) -> List[Dict[str, Any]]:
        ...

    def delete_expired(
        self,
        session_id: Optional[str] = None,
        layer: Optional[str] = None,
    ) -> int:
        """删除过期记忆，返回删除数量。"""
        ...

    def evict_oldest(
        self,
        session_id: str,
        layer: str,
        max_entries: int,
    ) -> int:
        """按最旧优先驱逐，保留最多 max_entries 条，返回删除数量。"""
        ...

    def close(self) -> None:
        ...


class SQLiteMemoryBackend:
    """SQLite 降级实现：支持关键词/时效混合召回、TTL、容量驱逐、线程安全。"""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(
            str(self.base_dir / "memory.db"),
            check_same_thread=False,
            timeout=10.0,
        )
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=5000")
        self._init_tables()

    def _init_tables(self) -> None:
        with self._lock:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS memory ("
                "id TEXT PRIMARY KEY, session_id TEXT, layer TEXT, key TEXT, "
                "value TEXT, created_at REAL, expires_at REAL)"
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_layer_session ON memory(layer, session_id)"
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_created_at ON memory(created_at)"
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
        with self._lock:
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
        max_candidates: int = 100,
    ) -> List[Dict[str, Any]]:
        now = time.time()
        with self._lock:
            cursor = self._db.execute(
                "SELECT key, value, created_at FROM memory WHERE session_id=? AND layer=? "
                "AND (expires_at=0 OR expires_at>?) ORDER BY created_at DESC LIMIT ?",
                (session_id, layer, now, max(max_candidates, top_k * 3)),
            )
            candidates = []
            for key, raw_value, created_at in cursor.fetchall():
                try:
                    value = json.loads(raw_value)
                except json.JSONDecodeError:
                    value = raw_value
                candidates.append({"key": key, "value": value, "created_at": created_at})

        scored = [
            {
                "key": c["key"],
                "value": c["value"],
                "score": _score_candidate(query, c["key"], c["value"], c["created_at"]),
            }
            for c in candidates
        ]
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def delete_expired(
        self,
        session_id: Optional[str] = None,
        layer: Optional[str] = None,
    ) -> int:
        now = time.time()
        where = ["expires_at>0", "expires_at<=?"]
        params: List[Any] = [now]
        if session_id:
            where.append("session_id=?")
            params.append(session_id)
        if layer:
            where.append("layer=?")
            params.append(layer)
        with self._lock:
            cursor = self._db.execute(
                f"DELETE FROM memory WHERE {' AND '.join(where)}",
                params,
            )
            self._db.commit()
            return cursor.rowcount

    def evict_oldest(
        self,
        session_id: str,
        layer: str,
        max_entries: int,
    ) -> int:
        with self._lock:
            count_row = self._db.execute(
                "SELECT COUNT(*) FROM memory WHERE session_id=? AND layer=?",
                (session_id, layer),
            ).fetchone()
            total = count_row[0] if count_row else 0
            if total <= max_entries:
                return 0
            to_delete = total - max_entries
            self._db.execute(
                "DELETE FROM memory WHERE id IN ("
                "SELECT id FROM memory WHERE session_id=? AND layer=? "
                "ORDER BY created_at ASC LIMIT ?)",
                (session_id, layer, to_delete),
            )
            self._db.commit()
            return to_delete

    def close(self) -> None:
        with self._lock:
            self._db.close()


class RedisMemoryBackend:
    """Redis 后端（可选，未安装时降级）。"""

    def __init__(self, url: Optional[str] = None):
        import redis
        self._client = redis.from_url(url or os.getenv("REDIS_URL", "redis://localhost:6379/0"))

    def _key(self, session_id: str, layer: str, key: str) -> str:
        return f"dev_agent:{layer}:{session_id}:{key}"

    def _encode(self, value: Any, created_at: float, expires_at: float) -> str:
        return json.dumps(
            {"_value": value, "_created_at": created_at, "_expires_at": expires_at},
            ensure_ascii=False,
        )

    def _decode(self, data: str) -> Tuple[Any, float, float]:
        try:
            parsed = json.loads(data)
            if isinstance(parsed, dict) and "_value" in parsed:
                return (
                    parsed["_value"],
                    parsed.get("_created_at") or time.time(),
                    parsed.get("_expires_at") or 0.0,
                )
        except json.JSONDecodeError:
            pass
        return data, time.time(), 0.0

    def remember(
        self,
        key: str,
        value: Any,
        session_id: str,
        layer: str,
        ttl: Optional[int] = None,
    ) -> None:
        full_key = self._key(session_id, layer, key)
        now = time.time()
        expires = now + ttl if ttl else 0
        raw = self._encode(value, now, expires)
        if ttl:
            self._client.setex(full_key, ttl, raw)
        else:
            self._client.set(full_key, raw)

    def recall(
        self,
        query: str,
        session_id: str,
        layer: str,
        top_k: int = 3,
        max_candidates: int = 100,
    ) -> List[Dict[str, Any]]:
        now = time.time()
        pattern = f"dev_agent:{layer}:{session_id}:*"
        keys = list(self._client.scan_iter(match=pattern, count=max_candidates))
        candidates = []
        expired_keys = []
        for key in keys[:max_candidates]:
            raw = self._client.get(key)
            if raw is None:
                continue
            decoded = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            value, created_at, expires_at = self._decode(decoded)
            if expires_at > 0 and expires_at <= now:
                expired_keys.append(key)
                continue
            key_str = key.decode("utf-8") if isinstance(key, bytes) else key
            candidates.append({"key": key_str, "value": value, "created_at": created_at})

        if expired_keys:
            self._client.delete(*expired_keys)

        scored = [
            {
                "key": c["key"],
                "value": c["value"],
                "score": _score_candidate(query, c["key"], c["value"], c["created_at"]),
            }
            for c in candidates
        ]
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def delete_expired(
        self,
        session_id: Optional[str] = None,
        layer: Optional[str] = None,
    ) -> int:
        now = time.time()
        pattern = f"dev_agent:{layer or '*'}:{session_id or '*'}:*"
        count = 0
        for key in self._client.scan_iter(match=pattern):
            raw = self._client.get(key)
            if raw is None:
                continue
            decoded = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            _, _, expires_at = self._decode(decoded)
            if expires_at > 0 and expires_at <= now:
                self._client.delete(key)
                count += 1
        return count

    def evict_oldest(
        self,
        session_id: str,
        layer: str,
        max_entries: int,
    ) -> int:
        pattern = f"dev_agent:{layer}:{session_id}:*"
        entries = []
        for key in self._client.scan_iter(match=pattern):
            raw = self._client.get(key)
            if raw is None:
                continue
            decoded = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            _, created_at, _ = self._decode(decoded)
            entries.append((key, created_at))
        if len(entries) <= max_entries:
            return 0
        entries.sort(key=lambda x: x[1])
        to_delete = [k for k, _ in entries[: len(entries) - max_entries]]
        if to_delete:
            self._client.delete(*to_delete)
        return len(to_delete)

    def close(self) -> None:
        pass


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
        now = time.time()
        doc_id = f"{layer}:{session_id}:{key}"
        self._collection.upsert(
            ids=[doc_id],
            documents=[json.dumps(value, ensure_ascii=False)],
            metadatas=[{
                "session_id": session_id,
                "layer": layer,
                "key": key,
                "created_at": now,
                "expires_at": now + ttl if ttl else 0,
            }],
        )

    def recall(
        self,
        query: str,
        session_id: str,
        layer: str,
        top_k: int = 3,
        max_candidates: int = 100,
    ) -> List[Dict[str, Any]]:
        now = time.time()
        # Chroma 的 where 语法较严格，先按 session/layer 查询，再在 Python 层过滤 TTL。
        # 为了召回率，拉取比 top_k 多一些的候选。
        results = self._collection.query(
            query_texts=[query or ""],
            n_results=min(max_candidates * 2, max(50, top_k * 5)),
            where={"session_id": session_id, "layer": layer},
        )
        candidates = []
        for doc_id, doc, meta, dist in zip(
            results["ids"][0], results["documents"][0], results["metadatas"][0], results["distances"][0]
        ):
            expires_at = meta.get("expires_at") or 0
            if expires_at > 0 and expires_at <= now:
                continue
            try:
                value = json.loads(doc)
            except json.JSONDecodeError:
                value = doc
            created_at = meta.get("created_at") or time.time()
            # Chroma distance 越低越相似，映射到 0-1 的语义分
            semantic = 1.0 / (1.0 + float(dist))
            candidates.append({
                "key": meta.get("key", doc_id),
                "value": value,
                "created_at": created_at,
                "semantic": semantic,
            })

        scored = [
            {
                "key": c["key"],
                "value": c["value"],
                "score": _score_candidate(
                    query, c["key"], c["value"], c["created_at"], c["semantic"], has_semantic=True
                ),
            }
            for c in candidates
        ]
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def delete_expired(
        self,
        session_id: Optional[str] = None,
        layer: Optional[str] = None,
    ) -> int:
        now = time.time()
        where: Dict[str, Any] = {"expires_at": {"$gt": 0, "$lte": now}}
        if session_id:
            where["session_id"] = session_id
        if layer:
            where["layer"] = layer
        try:
            data = self._collection.get(where=where)
            ids = data.get("ids", [])
            if ids:
                self._collection.delete(ids=ids)
            return len(ids)
        except Exception:  # noqa: BLE001
            # Chroma 版本差异可能导致 where 语法不兼容，降级为全量扫描
            return self._delete_expired_by_scan(session_id, layer, now)

    def _delete_expired_by_scan(
        self,
        session_id: Optional[str],
        layer: Optional[str],
        now: float,
    ) -> int:
        where = {"session_id": session_id, "layer": layer} if session_id and layer else {}
        try:
            data = self._collection.get(where=where) if where else self._collection.get()
        except Exception:  # noqa: BLE001
            return 0
        ids_to_delete = []
        metas = data.get("metadatas", [])
        ids = data.get("ids", [])
        for doc_id, meta in zip(ids, metas):
            expires_at = (meta or {}).get("expires_at") or 0
            if expires_at > 0 and expires_at <= now:
                ids_to_delete.append(doc_id)
        if ids_to_delete:
            self._collection.delete(ids=ids_to_delete)
        return len(ids_to_delete)

    def evict_oldest(
        self,
        session_id: str,
        layer: str,
        max_entries: int,
    ) -> int:
        try:
            data = self._collection.get(where={"session_id": session_id, "layer": layer})
        except Exception:  # noqa: BLE001
            return 0
        metas = data.get("metadatas", [])
        ids = data.get("ids", [])
        if len(ids) <= max_entries:
            return 0
        indexed = sorted(
            zip(ids, metas),
            key=lambda x: (x[1] or {}).get("created_at", 0),
        )
        to_delete = [doc_id for doc_id, _ in indexed[: len(indexed) - max_entries]]
        if to_delete:
            self._collection.delete(ids=to_delete)
        return len(to_delete)

    def close(self) -> None:
        pass


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

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = Path(base_dir or Settings.memory_dir())
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._short: Dict[str, Dict[str, Any]] = {}
        self._backend = _create_backend(self.base_dir)
        # 在同步上下文中创建 asyncio.Lock 可能失败（无事件循环），
        # 因此延迟初始化，首次 aremember/arecall 时再创建。
        self._lock: Optional[asyncio.Lock] = None
        try:
            self._lock = asyncio.Lock()
        except RuntimeError:
            pass
        self._max_entries = Settings.memory_max_entries_per_layer()
        self._max_candidates = Settings.memory_max_candidates()
        self._short_max = Settings.memory_short_max_entries()

    def _cleanup_short(self, session_id: str) -> None:
        """清理短期记忆中的过期项，并按容量上限移除最旧项。"""
        now = time.time()
        session = self._short.get(session_id, {})
        expired = [k for k, v in session.items() if v.get("expires_at") is not None and v["expires_at"] <= now]
        for k in expired:
            session.pop(k, None)
        # Python 3.7+ dict 保持插入顺序，最旧的在前面
        while len(session) > self._short_max:
            session.pop(next(iter(session)), None)

    def remember(
        self,
        key: str,
        value: Any,
        session_id: str = "default",
        layer: str = "short",
        ttl: Optional[int] = None,
    ) -> None:
        if layer == "short":
            session = self._short.setdefault(session_id, {})
            session[key] = {
                "value": value,
                "expires_at": time.time() + ttl if ttl else None,
                "created_at": time.time(),
            }
            self._cleanup_short(session_id)
            return
        self._backend.remember(key, value, session_id, layer, ttl)
        self._backend.delete_expired(session_id, layer)
        self._backend.evict_oldest(session_id, layer, self._max_entries)

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def aremember(
        self,
        key: str,
        value: Any,
        session_id: str = "default",
        layer: str = "short",
        ttl: Optional[int] = None,
    ) -> None:
        """remember 的异步安全封装，在后台线程执行并加 asyncio 锁。"""
        async with self._get_lock():
            return await asyncio.to_thread(
                self.remember, key, value, session_id, layer, ttl
            )

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
            candidates = []
            for key, item in session.items():
                expires_at = item.get("expires_at")
                if expires_at is not None and expires_at <= now:
                    continue
                candidates.append({
                    "key": key,
                    "value": item["value"],
                    "created_at": item.get("created_at", now),
                })
            scored = [
                {
                    "key": c["key"],
                    "value": c["value"],
                    "score": _score_candidate(query, c["key"], c["value"], c["created_at"]),
                }
                for c in candidates
            ]
            scored.sort(key=lambda x: x["score"], reverse=True)
            return scored[:top_k]
        return self._backend.recall(query, session_id, layer, top_k, max_candidates=self._max_candidates)

    async def arecall(
        self,
        query: str,
        session_id: str = "default",
        layer: str = "working",
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """recall 的异步安全封装，避免在 async 编排器中阻塞事件循环。"""
        async with self._get_lock():
            return await asyncio.to_thread(self.recall, query, session_id, layer, top_k)

    def summarize(self, history: List[Dict[str, Any]]) -> str:
        if not history:
            return ""
        parts = [f"- {h.get('agent','?')}: {str(h.get('output',''))[:120]}..." for h in history[-5:]]
        return "\n".join(parts)

    async def asummarize(self, history: List[Dict[str, Any]]) -> str:
        return self.summarize(history)

    def compress_context(self, text: str, max_chars: int = 8000) -> str:
        return ContextCompressor(max_chars=max_chars).compress(text)

    async def acompress_context(self, text: str, max_chars: int = 8000) -> str:
        return self.compress_context(text, max_chars)

    def delete_expired(
        self,
        session_id: Optional[str] = None,
        layer: Optional[str] = None,
    ) -> int:
        if layer == "short":
            count = 0
            now = time.time()
            for session in self._short.values():
                expired = [k for k, v in session.items() if v.get("expires_at") and v["expires_at"] <= now]
                for k in expired:
                    session.pop(k, None)
                    count += 1
            return count
        return self._backend.delete_expired(session_id, layer)

    async def adelete_expired(
        self,
        session_id: Optional[str] = None,
        layer: Optional[str] = None,
    ) -> int:
        async with self._get_lock():
            return await asyncio.to_thread(self.delete_expired, session_id, layer)

    def close(self) -> None:
        if hasattr(self._backend, "close"):
            self._backend.close()


# 保持旧接口兼容（注意：MemoryAgentFacade 实际在 agents.py 中供 Orchestrator 使用）
MemoryAgentFacade = MemoryAgent
