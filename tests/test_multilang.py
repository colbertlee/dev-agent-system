"""多语言工作流相关单元测试。"""
from __future__ import annotations

import asyncio

import pytest

from dev_agent_system.agents import CoderAgent, TesterAgent as QA_Agent


def test_coder_fallback_go(tmp_path):
    agent = CoderAgent()
    state = {
        "input": "开发一个 go 加法模块",
        "workspace": str(tmp_path),
        "language": "go",
    }

    async def _run():
        return await agent.postprocess("", state)

    result = asyncio.run(_run())
    assert result["status"] == "mock_fallback"
    assert (tmp_path / "main.go").exists()


def test_coder_fallback_java(tmp_path):
    agent = CoderAgent()
    state = {
        "input": "开发一个 java 加法模块",
        "workspace": str(tmp_path),
        "language": "java",
    }

    async def _run():
        return await agent.postprocess("", state)

    result = asyncio.run(_run())
    assert result["status"] == "mock_fallback"
    assert (tmp_path / "Main.java").exists()


def test_tester_writes_go_test(tmp_path):
    agent = QA_Agent()
    state = {
        "input": "go add",
        "workspace": str(tmp_path),
        "language": "go",
        "coder": {"files": ["main.go"]},
    }
    (tmp_path / "main.go").write_text("package main\n", encoding="utf-8")
    output = '# file: main_test.go\n```go\npackage main\n\nimport \"testing\"\n\nfunc TestAdd(t *testing.T) {}\n```'

    async def _run():
        return await agent.postprocess(output, state)

    result = asyncio.run(_run())
    assert "main_test.go" in result["files"]
    assert (tmp_path / "main_test.go").exists()


def test_tester_writes_typescript_test(tmp_path):
    agent = QA_Agent()
    state = {
        "input": "ts add",
        "workspace": str(tmp_path),
        "language": "typescript",
        "coder": {"files": ["main.ts"]},
    }
    (tmp_path / "main.ts").write_text("console.log(1);\n", encoding="utf-8")
    output = '# file: main.test.ts\n```typescript\nimport {} from \"./main\";\n```'

    async def _run():
        return await agent.postprocess(output, state)

    result = asyncio.run(_run())
    assert "main.test.ts" in result["files"]
    assert (tmp_path / "main.test.ts").exists()
