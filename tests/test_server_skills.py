"""Server Skill 市场端点测试。"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from dev_agent_system.server import app
from dev_agent_system.skills import SkillManager, SkillStore


@pytest.fixture
def client():
    return TestClient(app)


def test_list_skills_empty(client: TestClient, tmp_path, monkeypatch):
    monkeypatch.setenv("SKILLS_DIR", str(tmp_path / "skills"))
    response = client.get("/skills")
    assert response.status_code == 200
    assert response.json() == []


def test_get_skill_not_found(client: TestClient):
    response = client.get("/skills/non-existent")
    assert response.status_code == 404


def test_invoke_skill_not_found(client: TestClient):
    response = client.post("/skills/non-existent/invoke", json={})
    assert response.status_code == 200
    assert response.json()["result"]["success"] is False


def test_skill_endpoints_with_skill(client: TestClient, tmp_path, monkeypatch):
    skills_dir = tmp_path / "skills"
    monkeypatch.setenv("SKILLS_DIR", str(skills_dir))
    store = SkillStore(base_dir=skills_dir)
    manager = SkillManager(store)
    manager.install(
        {
            "id": "greet",
            "name": "问候",
            "description": "返回问候语",
            "code": "def run(name='world'):\n    return {'success': True, 'message': f'Hello, {name}'}\n",
        }
    )

    response = client.get("/skills")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "greet"

    response = client.get("/skills/greet")
    assert response.status_code == 200
    assert response.json()["id"] == "greet"

    response = client.post("/skills/greet/invoke", json={"name": "dev"})
    assert response.status_code == 200
    assert response.json()["result"]["message"] == "Hello, dev"
