"""集成测试：使用 Mock LLM 跑通完整 DAG。"""
import asyncio
import os

# 强制使用 MOCK 模式，避免误调真实 API
os.environ.setdefault("LLM_API_KEY", "")

from dev_agent_system.llm import LLMClient
from dev_agent_system.orchestrator import Orchestrator


def test_orchestrator_end_to_end(monkeypatch):
    monkeypatch.setattr(
        LLMClient,
        "chat",
        lambda self, system, user: '{"passed": true, "severity": "low", "note": "mock"}',
    )

    async def _run():
        orch = Orchestrator(max_iterations=1)
        result = await orch.run("开发一个用户登录模块")
        return result

    result = asyncio.run(_run())
    assert result["status"] == "completed"
    assert "architect" in result
    assert "coder" in result
    assert "reviewer" in result


def test_sandbox_path_escape():
    from dev_agent_system.mcp import ToolSandbox
    result = ToolSandbox.read_file("../etc/passwd")
    assert result["success"] is False
    assert "越界" in result["error"]


def test_idempotency_guard():
    from dev_agent_system.orchestrator import IdempotencyGuard
    g = IdempotencyGuard()
    assert g.is_duplicate("req-1") is False
    assert g.is_duplicate("req-1") is True
