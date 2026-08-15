"""A2A 协议互操作测试：验证独立 Agent 节点可通过 HTTP API 互相调用。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dev_agent_system.a2a_node import create_app
from dev_agent_system.agents import ArchitectAgent, CoderAgent
from dev_agent_system.llm import LLMClient


def _mock_chat(self, system: str, user: str, **kwargs) -> str:
    system_lower = system.lower()
    if "architect" in system_lower:
        return '{"modules": ["main"], "api_contract": {"add": "int -> int -> int"}, "tech_stack": "python", "mermaid": "", "notes": ""}'
    if "coder" in system_lower:
        return (
            '# file: main.py\n'
            '```python\n'
            'def add(a, b):\n'
            '    return a + b\n'
            '```\n'
            '```json\n'
            '{"status": "completed", "files_modified": ["main.py"], "test_result": "passed", "note": ""}\n'
            '```'
        )
    return "mock"


@pytest.fixture
def mock_llm(monkeypatch):
    monkeypatch.setattr(LLMClient, "chat", _mock_chat)


def test_architect_agent_card(mock_llm, monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "workspace"))
    agent = ArchitectAgent()
    app = create_app("architect", agent, 8081)
    client = TestClient(app)
    resp = client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    card = resp.json()
    assert card["name"] == "Architect Agent"
    assert len(card["skills"]) > 0


def test_coder_task_flow(mock_llm, monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "workspace"))
    agent = CoderAgent()
    app = create_app("coder", agent, 8082)
    client = TestClient(app)
    payload = {
        "description": "实现加法模块",
        "payload": {
            "architect": {
                "output": '{"modules": ["main"], "api_contract": {"add": "int -> int -> int"}}'
            }
        },
    }
    resp = client.post("/tasks", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert "main.py" in data["result"].get("files", [])


def test_a2a_health_endpoint(mock_llm, monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "workspace"))
    agent = ArchitectAgent()
    app = create_app("architect", agent, 8083)
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
