"""Dashboard 端点单元测试。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from dev_agent_system.server import app
from dev_agent_system.tracker import WorkflowTracker


client = TestClient(app)


def test_dashboard_html():
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "DevAgent System Dashboard" in response.text


def test_status_endpoint_empty():
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "workflows" in data
    assert isinstance(data["workflows"], list)


def test_status_detail_not_found():
    response = client.get("/api/status/non-existent")
    assert response.status_code == 404


def test_status_detail_with_record():
    tracker = WorkflowTracker()
    tracker.start("dash-req-1", "需求")
    tracker.update("dash-req-1", status="working", current_agent="coder")
    response = client.get("/api/status/dash-req-1")
    assert response.status_code == 200
    data = response.json()
    assert data["request_id"] == "dash-req-1"
    assert data["status"] == "working"
    assert data["current_agent"] == "coder"
