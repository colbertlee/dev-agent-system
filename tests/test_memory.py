"""Memory Agent 与上下文压缩测试。"""
import asyncio
import os
import time
import uuid

os.environ.setdefault("LLM_API_KEY", "")
os.environ.setdefault("MEMORY_BACKEND", "sqlite")

from dev_agent_system.memory import ContextCompressor, MemoryAgent


def test_short_memory():
    session = f"s1-{uuid.uuid4().hex[:8]}"
    m = MemoryAgent(base_dir="memory_store_test")
    m.remember("key1", "value1", session_id=session, layer="short", ttl=3600)
    rows = m.recall("", session_id=session, layer="short", top_k=3)
    assert len(rows) == 1
    assert rows[0]["value"] == "value1"
    m.close()


def test_working_memory_sqlite():
    session = f"s2-{uuid.uuid4().hex[:8]}"
    m = MemoryAgent(base_dir="memory_store_test")
    m.remember("design", {"modules": ["a"]}, session_id=session, layer="working", ttl=3600)
    rows = m.recall("modules", session_id=session, layer="working", top_k=3)
    assert len(rows) == 1
    assert rows[0]["value"]["modules"] == ["a"]
    m.close()


def test_recall_keyword_ranking():
    """query 命中关键词时，相关记忆的 score 应高于不相关的。"""
    session = f"kw-{uuid.uuid4().hex[:8]}"
    m = MemoryAgent(base_dir="memory_store_test")
    m.remember("payment", {"desc": "支付网关实现"}, session_id=session, layer="working")
    m.remember("user", {"desc": "用户画像逻辑"}, session_id=session, layer="working")
    m.remember("order", {"desc": "订单状态机"}, session_id=session, layer="working")

    rows = m.recall("支付", session_id=session, layer="working", top_k=3)
    assert len(rows) == 3
    # 与 query 最相关的是 payment
    assert rows[0]["key"] == "payment"
    # 所有结果都应带 0-1 的 score
    assert all(0.0 <= r["score"] <= 1.0 for r in rows)
    m.close()


def test_recall_empty_query_sorts_by_recency():
    """空 query 时按时效排序，最近写入的排最前。"""
    session = f"rec-{uuid.uuid4().hex[:8]}"
    m = MemoryAgent(base_dir="memory_store_test")
    m.remember("old", {"v": 1}, session_id=session, layer="working")
    time.sleep(0.01)
    m.remember("new", {"v": 2}, session_id=session, layer="working")
    rows = m.recall("", session_id=session, layer="working", top_k=2)
    assert rows[0]["key"] == "new"
    assert rows[1]["key"] == "old"
    m.close()


def test_ttl_expiration():
    """TTL 过期后不应被召回。"""
    session = f"ttl-{uuid.uuid4().hex[:8]}"
    m = MemoryAgent(base_dir="memory_store_test")
    m.remember("temp", {"v": 1}, session_id=session, layer="working", ttl=1)
    rows = m.recall("", session_id=session, layer="working", top_k=3)
    assert len(rows) == 1
    time.sleep(1.1)
    rows_after = m.recall("", session_id=session, layer="working", top_k=3)
    assert len(rows_after) == 0
    m.close()


def test_capacity_eviction(monkeypatch, tmp_path):
    """超过容量上限时，最旧的记忆被驱逐。"""
    monkeypatch.setenv("MEMORY_MAX_ENTRIES_PER_LAYER", "2")
    monkeypatch.setenv("MEMORY_BACKEND", "sqlite")
    m = MemoryAgent(base_dir=str(tmp_path / "memory_evict"))
    session = f"evict-{uuid.uuid4().hex[:8]}"
    m.remember("a", {"v": 1}, session_id=session, layer="working")
    time.sleep(0.01)
    m.remember("b", {"v": 2}, session_id=session, layer="working")
    time.sleep(0.01)
    m.remember("c", {"v": 3}, session_id=session, layer="working")
    rows = m.recall("", session_id=session, layer="working", top_k=10)
    assert len(rows) == 2
    keys = {r["key"] for r in rows}
    assert "a" not in keys
    assert "b" in keys
    assert "c" in keys
    m.close()


def test_short_memory_capacity_and_ttl():
    """短期记忆应遵守 TTL 与容量上限。"""
    m = MemoryAgent(base_dir="memory_store_test")
    session = f"short-{uuid.uuid4().hex[:8]}"
    m.remember("a", 1, session_id=session, layer="short")
    m.remember("b", 2, session_id=session, layer="short")
    rows = m.recall("", session_id=session, layer="short", top_k=10)
    assert len(rows) == 2
    m.remember("c", 3, session_id=session, layer="short", ttl=1)
    time.sleep(1.1)
    rows = m.recall("", session_id=session, layer="short", top_k=10)
    # a, b 仍在，c 已过期
    assert len(rows) == 2
    assert all(r["key"] in ("a", "b") for r in rows)
    m.close()


def test_async_memory_interfaces():
    """aremember/arecall 在事件循环中可用且行为与同步版一致。"""
    session = f"async-{uuid.uuid4().hex[:8]}"
    m = MemoryAgent(base_dir="memory_store_test")

    async def _run():
        await m.aremember("k1", "v1", session_id=session, layer="working")
        rows = await m.arecall("v1", session_id=session, layer="working", top_k=3)
        assert len(rows) == 1
        assert rows[0]["value"] == "v1"

    asyncio.run(_run())
    m.close()


def test_context_compressor():
    c = ContextCompressor(max_chars=20, reserve_head=5)
    text = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = c.compress(text)
    assert "省略" in out
    assert len(out) <= 60


def test_compress_messages():
    c = ContextCompressor()
    msgs = [{"i": i} for i in range(20)]
    assert len(c.compress_messages(msgs, max_messages=5)) == 5
