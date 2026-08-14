"""测试 Agent 间状态压缩与关键信息传递。"""
import json

import pytest

from dev_agent_system.agents import BaseAgent, CoderAgent


class DummyAgent(BaseAgent):
    summary_budget = 200

    def __init__(self):
        super().__init__("Dummy", "测试", "你是测试 Agent")


def test_summarize_excludes_internal_fields():
    agent = DummyAgent()
    result = {
        "agent": "Dummy",
        "role": "测试",
        "output": "raw llm output text",
        "workspace": "/tmp/ws",
        "model": "mock",
        "llm_kwargs": {"temperature": 0.7},
        "files": ["main.py"],
        "status": "completed",
        "parsed": {"notes": "ok"},
    }
    summary_text = agent._summarize_result(result)
    summary = json.loads(summary_text)
    assert "output" not in summary
    assert "workspace" not in summary
    assert "model" not in summary
    assert "llm_kwargs" not in summary
    assert summary["files"] == ["main.py"]
    assert summary["status"] == "completed"


def test_summarize_truncates_long_strings_and_lists():
    agent = DummyAgent()
    result = {
        "files": [f"file_{i}.py" for i in range(20)],
        "report": "x" * 1000,
    }
    text = agent._summarize_result(result)
    assert len(text) <= agent.summary_budget + 50
    assert ("..." in text)


def test_summarize_recursive_dict():
    agent = CoderAgent()
    result = {
        "files": ["main.py"],
        "security_issues": [{"type": "x", "detail": "y" * 500} for _ in range(5)],
        "status": "completed",
    }
    text = agent._summarize_result(result)
    summary = json.loads(text)
    assert summary["status"] == "completed"
    assert len(summary["security_issues"]) <= 11  # 10 + '...'
    assert "[truncated]" in summary["security_issues"][0]["detail"]


def test_truncate_for_summary_handles_nested_structures():
    value = {
        "a": "a" * 100,
        "b": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        "c": {"d": "d" * 100},
    }
    truncated = BaseAgent._truncate_for_summary(value, max_str=20, max_list=5, max_depth=3)
    assert truncated["a"].endswith("... [truncated]")
    assert len(truncated["b"]) == 6  # 5 + '...'
    assert truncated["c"]["d"].endswith("... [truncated]")
