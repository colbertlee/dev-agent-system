"""Evaluation & Metrics 模块单元测试。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from dev_agent_system.eval import EvaluationRunner, EvalReport, MetricCalculator


class FakeOrchestrator:
    """不依赖真实 LLM 的 Orchestrator 替身。"""

    def __init__(self, max_iterations: int = 3, fail_request_id: str | None = None):
        self.max_iterations = max_iterations
        self.fail_request_id = fail_request_id

    async def run(self, requirement: str, request_id: str = "eval-0") -> dict:
        if request_id == self.fail_request_id:
            raise RuntimeError("mock failure")

        from dev_agent_system.config import Settings

        workspace = Settings.workspace_dir() / request_id
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "main.py").write_text("print('hello')")
        (workspace / "test_main.py").write_text("def test_main(): pass")

        return {
            "request_id": request_id,
            "status": "completed",
            "iteration": 1,
            "reviewer": {"passed": True},
            "tester": {"coverage": 0.85, "report": "1 passed, 85%"},
            "artifacts": {
                "workspace": str(workspace),
                "review_passed": True,
            },
        }


def _write_dataset(tmp_path: Path, items: list) -> Path:
    path = tmp_path / "eval_dataset.json"
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return path


def test_metric_calculator_file_recall(tmp_path: Path):
    (tmp_path / "a.py").write_text("a")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.py").write_text("b")

    recall, found, missing = MetricCalculator.file_recall(tmp_path, ["a.py", "b.py", "c.py"])
    assert recall == 2 / 3
    assert set(found) == {"a.py", "b.py"}
    assert missing == ["c.py"]


def test_metric_calculator_coverage():
    assert MetricCalculator.coverage({"coverage": 0.73}) == 0.73
    assert MetricCalculator.coverage({"report": "1 passed, 73%"}) == 0.73
    assert MetricCalculator.coverage(None) == 0.0


def test_metric_calculator_review_passed():
    assert MetricCalculator.review_passed(None, {"review_passed": True}) is True
    assert MetricCalculator.review_passed({"passed": True}, {}) is True
    assert MetricCalculator.review_passed({"passed": False}, {"review_passed": True}) is True


def test_evaluation_runner(monkeypatch, tmp_path: Path):
    """验证 EvaluationRunner 能正确跑完数据集并计算指标。"""
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "workspace"))
    monkeypatch.setenv("EVAL_OUTPUT_DIR", str(tmp_path / "eval_out"))

    dataset = [
        {
            "description": "task one",
            "expected_files": ["main.py", "test_main.py"],
            "min_test_coverage": 0.8,
        },
        {
            "description": "task two",
            "expected_files": ["missing.py"],
            "min_test_coverage": 0.5,
        },
    ]
    dataset_path = _write_dataset(tmp_path, dataset)

    runner = EvaluationRunner(orchestrator_factory=lambda max_iter: FakeOrchestrator(max_iter))
    report = asyncio.run(runner.run(dataset_path, max_iterations=1))

    assert isinstance(report, EvalReport)
    assert report.total == 2
    assert report.completed == 2
    assert report.failed == 0
    assert report.errored == 0
    assert report.pass_rate == 1.0
    assert report.file_recall == 0.5
    assert report.coverage == 0.85
    assert report.coverage_pass_rate == 1.0

    # 输出目录应生成 JSON 报告
    output_files = list(runner.output_dir.glob("eval_report_*.json"))
    assert len(output_files) == 1
    saved = json.loads(output_files[0].read_text(encoding="utf-8"))
    assert saved["total"] == 2


def test_evaluation_runner_error_handling(monkeypatch, tmp_path: Path):
    """验证某个任务异常时，评估仍能继续并正确标记。"""
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "workspace"))
    monkeypatch.setenv("EVAL_OUTPUT_DIR", str(tmp_path / "eval_out"))

    dataset = [
        {"description": "ok", "expected_files": ["main.py"], "min_test_coverage": 0.0},
        {"description": "fail", "expected_files": [], "min_test_coverage": 0.0},
    ]
    dataset_path = _write_dataset(tmp_path, dataset)

    runner = EvaluationRunner(
        orchestrator_factory=lambda max_iter: FakeOrchestrator(max_iter, fail_request_id="eval-1")
    )
    report = asyncio.run(runner.run(dataset_path, max_iterations=1))

    assert report.total == 2
    assert report.completed == 1
    assert report.errored == 1
    assert report.pass_rate == 0.5
