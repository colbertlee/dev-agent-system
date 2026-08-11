"""新增角色 Agent（Product Manager / Security / DBA）单元测试。"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from dev_agent_system.agents import DBAAgent, ProductManagerAgent, SecurityAgent
from dev_agent_system.llm import LLMClient
from dev_agent_system.orchestrator import Orchestrator


def _mock_chat(self, system: str, user: str, **kwargs) -> str:
    system_lower = system.lower()
    if "product" in system_lower or "产品经理" in system:
        return (
            '# file: prd.md\n'
            '## PRD\n需求：加法模块\n\n'
            '```json\n'
            '{"user_stories": ["作为用户，我能输入两个数并得到和"], "acceptance_criteria": ["1+1=2"]}\n'
            '```'
        )
    if "architect" in system_lower:
        return '{"modules": ["main"], "api_contract": {"add": "int -> int -> int"}, "tech_stack": "python", "mermaid": "", "notes": ""}'
    if "coder" in system_lower:
        return (
            '# file: main.py\n'
            '```python\n'
            'def add(a, b):\n'
            '    return a + b\n'
            '\n'
            'if __name__ == "__main__":\n'
            '    print(add(1, 2))\n'
            '```\n'
            '```json\n'
            '{"status": "completed", "files_modified": ["main.py"], "test_result": "passed", "note": ""}\n'
            '```'
        )
    if "tester" in system_lower:
        return (
            '# file: test_main.py\n'
            '```python\n'
            'from main import add\n'
            '\n'
            'def test_add():\n'
            '    assert add(1, 2) == 3\n'
            '```\n'
            '```json\n'
            '{"passed": 1, "failed": 0, "coverage": 0.0, "report": "OK"}\n'
            '```'
        )
    if "reviewer" in system_lower:
        return '{"severity": "low", "passed": true, "issues": [], "suggestions": []}'
    if "security" in system_lower:
        return '{"severity": "low", "passed": true, "issues": [], "suggestions": []}'
    if "docs" in system_lower:
        return '# file: README.md\n# Test Project\n'
    if "dba" in system_lower:
        return (
            '# file: schema.sql\n'
            '```sql\n'
            'CREATE TABLE users (id INTEGER PRIMARY KEY);\n'
            '```\n'
            '```json\n'
            '{"tables": ["users"], "notes": ""}\n'
            '```'
        )
    if "devops" in system_lower:
        return 'DevOps summary'
    return "mock"


def test_product_manager_agent(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "workspace"))
    monkeypatch.setattr(LLMClient, "chat", _mock_chat)
    agent = ProductManagerAgent()
    result = asyncio.run(agent.run({"input": "开发一个加法模块", "request_id": "pm-1"}))
    assert "prd_file" in result
    assert result["prd_file"] == "prd.md"


def test_security_agent(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "workspace"))
    monkeypatch.setattr(LLMClient, "chat", _mock_chat)
    agent = SecurityAgent()
    state = {
        "input": "开发一个加法模块",
        "request_id": "sec-1",
        "workspace": str(tmp_path / "workspace" / "sec-1"),
        "coder": {"files": ["main.py"]},
        "tester": {"files": ["test_main.py"]},
        "architect": {"output": '{"modules": ["main"]}'},
    }
    result = asyncio.run(agent.run(state))
    assert "report_file" in result
    assert result.get("passed") is True


def test_dba_agent(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "workspace"))
    monkeypatch.setattr(LLMClient, "chat", _mock_chat)
    agent = DBAAgent()
    state = {
        "input": "开发一个用户系统",
        "request_id": "dba-1",
        "workspace": str(tmp_path / "workspace" / "dba-1"),
        "architect": {"output": '{"modules": ["users"]}'},
    }
    result = asyncio.run(agent.run(state))
    assert len(result.get("files", [])) > 0
    assert "schema.sql" in result["files"]


def test_orchestrator_with_new_agents(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "workspace"))
    monkeypatch.setenv("CHECKPOINT_ENABLED", "false")
    monkeypatch.setattr(LLMClient, "chat", _mock_chat)

    async def _run():
        orch = Orchestrator(
            max_iterations=1,
            enable_product_manager=True,
            enable_security=True,
            enable_dba=True,
        )
        result = await orch.run("开发一个加法模块", request_id="full-1")
        return result

    result = asyncio.run(_run())
    assert result["status"] == "completed"
    assert result["artifacts"]["prd_file"] == "prd.md"
    assert result["artifacts"]["schema_files"]
    assert result["artifacts"]["security_passed"] is True
