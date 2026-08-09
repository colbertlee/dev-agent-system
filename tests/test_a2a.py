"""A2A 节点与客户端测试。"""
import os

os.environ.setdefault("LLM_API_KEY", "")

from fastapi.testclient import TestClient

from dev_agent_system.a2a_client import A2AClient
from dev_agent_system.a2a_node import create_app
from dev_agent_system.agents import ArchitectAgent


def test_agent_card_endpoint():
    agent = ArchitectAgent()
    app = create_app("architect", agent, 8081)
    client = TestClient(app)
    resp = client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Architect Agent"
    assert any(s["name"] == "system-design" for s in data["skills"])


def test_tasks_endpoint():
    agent = ArchitectAgent()
    app = create_app("architect", agent, 8081)
    client = TestClient(app)
    resp = client.post("/tasks", json={"description": "设计登录模块"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert "task_id" in data


def test_health_endpoint():
    agent = ArchitectAgent()
    app = create_app("architect", agent, 8081)
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_a2a_client_discover(monkeypatch):
    """用 monkeypatch 替换 httpx.Client.get 返回固定 Agent Card。"""
    import httpx

    fake_card = {
        "name": "Coder Agent",
        "url": "http://localhost:8082",
        "skills": [{"name": "code-implementation"}],
        "capabilities": {"streaming": False},
    }

    class FakeResponse:
        status_code = 200
        def json(self):
            return fake_card
        def raise_for_status(self):
            pass

    monkeypatch.setattr(
        httpx.Client,
        "get",
        lambda self, url, **kwargs: FakeResponse(),
    )

    client = A2AClient("http://localhost:8082")
    card = client.discover()
    assert card.name == "Coder Agent"
