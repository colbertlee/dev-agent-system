"""DevOps 真实闭环单元测试。"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from dev_agent_system.devops import DevOpsRunner
from dev_agent_system.llm import LLMClient
from dev_agent_system.orchestrator import Orchestrator


def test_devops_runner_image_name_sanitizes():
    runner = DevOpsRunner()
    assert runner._image_name("req_1") == "dev-agent:req-1"
    assert runner._image_name("req 1!") == "dev-agent:req-1"


def test_devops_runner_dry_run_with_dockerfile(tmp_path: Path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "Dockerfile").write_text("FROM python:3.11-slim\n", encoding="utf-8")

    runner = DevOpsRunner(dry_run=True)
    report = runner.run("req-1", workspace)

    assert report["dry_run"] is True
    assert report["deployed"] is True
    assert report["build"]["success"] is True
    assert report["run"]["success"] is True
    assert report["health"]["success"] is True
    assert report["cleanup"]["success"] is True


def test_devops_runner_no_dockerfile(tmp_path: Path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    runner = DevOpsRunner(dry_run=False)
    report = runner.run("req-2", workspace)

    assert report["deployed"] is False
    assert report["build"]["success"] is False
    assert "缺少 Dockerfile" in report["build"]["error"]


def _mock_chat(self, system: str, user: str, **kwargs) -> str:
    system_lower = system.lower()
    if "architect" in system_lower:
        return '{"modules": ["main"], "api_contract": {}, "tech_stack": "python", "mermaid": "", "notes": ""}'
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
    if "tester" in system_lower:
        return (
            '# file: test_main.py\n'
            '```python\n'
            'from main import add\n\n'
            'def test_add():\n'
            '    assert add(1, 2) == 3\n'
            '```\n'
            '```json\n'
            '{"passed": 1, "failed": 0, "coverage": 0.0, "report": "OK"}\n'
            '```'
        )
    if "reviewer" in system_lower:
        return '{"severity": "low", "passed": true, "issues": [], "suggestions": []}'
    if "docs" in system_lower:
        return '# file: README.md\n# Test Project\n'
    if "devops" in system_lower:
        return (
            '# file: Dockerfile\n'
            '```dockerfile\n'
            'FROM python:3.11-slim\n'
            'WORKDIR /app\n'
            'COPY . .\n'
            'CMD ["python", "main.py"]\n'
            '```\n'
            '```json\n'
            '{"status": "completed", "files_modified": ["Dockerfile"], "test_result": "passed", "note": ""}\n'
            '```'
        )
    return "mock"


class FakeDevOpsRunner:
    def __init__(self, deployed: bool = True):
        self.deployed = deployed

    def run(self, request_id: str, workspace: Path) -> dict:
        return {
            "deployed": self.deployed,
            "dry_run": True,
            "image": f"fake:{request_id}",
            "build": {"success": True},
            "run": {"success": True},
            "health": {"success": self.deployed},
            "cleanup": {"success": True},
        }


def test_orchestrator_devops_dry_run(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(LLMClient, "chat", _mock_chat)
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "workspace"))

    async def _run():
        runner = FakeDevOpsRunner(deployed=True)
        orch = Orchestrator(max_iterations=1, enable_devops=True, devops_runner=runner)
        result = await orch.run("开发一个加法模块", request_id="devops-req-1")
        return result

    result = asyncio.run(_run())
    assert result["status"] == "completed"
    assert result["devops"]["deployment"]["deployed"] is True
    workspace = Path(result["artifacts"]["workspace"])
    assert (workspace / "Dockerfile").exists()
