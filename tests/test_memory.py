"""Memory Agent 与上下文压缩测试。"""
import os
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
