"""真实 LLM 回归测试。

运行方式：
    LLM_API_KEY=xxx python -m pytest tests -q --live

默认不运行，避免消耗 API quota 与依赖外部服务。
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest

from dev_agent_system.agents import ArchitectAgent, CoderAgent
from dev_agent_system.orchestrator import Orchestrator


def _load_eval_cases() -> List[Dict[str, Any]]:
    dataset = Path(__file__).with_name("eval_dataset.json")
    if not dataset.exists():
        return []
    with dataset.open("r", encoding="utf-8") as f:
        return json.load(f)


EVAL_CASES = _load_eval_cases()


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("LLM_API_KEY"), reason="需要 LLM_API_KEY 环境变量")
@pytest.mark.parametrize("case", EVAL_CASES[:3])
async def test_architect_produces_modules(case, monkeypatch, tmp_path):
    """ Architect 在真实模型下能输出 modules、api_contract、tech_stack。 """
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "workspace"))
    agent = ArchitectAgent()
    state = {"input": case["description"], "request_id": f"live-arch-{case.get('id', '0')}"}
    result = await agent.run(state)
    report = result.get("report", {})
    assert report.get("modules")
    assert report.get("api_contract") is not None
    assert report.get("tech_stack")


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("LLM_API_KEY"), reason="需要 LLM_API_KEY 环境变量")
async def test_orchestrator_end_to_end(monkeypatch, tmp_path):
    """真实 LLM 下完整工作流能跑通一轮。"""
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "workspace"))
    monkeypatch.setenv("CHECKPOINT_ENABLED", "false")

    orch = Orchestrator(max_iterations=1)
    result = await orch.run("实现一个支持加减乘除的 Python 命令行计算器", request_id="live-orch-1")
    assert result.get("status") in ("completed", "awaiting_approval")
    assert result.get("iteration", 0) >= 1
