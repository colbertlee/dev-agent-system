"""评估与 benchmark 相关单元测试。"""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from dev_agent_system.eval import (
    EvalReport,
    EvalSample,
    EvaluationRunner,
    MetricCalculator,
    RegressionChecker,
)


def test_file_recall(tmp_path: Path):
    (tmp_path / "main.py").write_text("x")
    (tmp_path / "sub").mkdir(parents=True)
    (tmp_path / "sub" / "test_main.py").write_text("y")

    recall, found, missing = MetricCalculator.file_recall(
        tmp_path, ["main.py", "test_main.py", "missing.txt"]
    )
    assert recall == 2 / 3
    assert "main.py" in found
    assert "test_main.py" in found
    assert "missing.txt" in missing


def test_coverage_extraction():
    assert MetricCalculator.coverage({"coverage": 0.85}) == 0.85
    assert MetricCalculator.coverage({"report": "总覆盖率 67%"}) == 0.67
    assert MetricCalculator.coverage(None) == 0.0


def test_review_passed():
    assert MetricCalculator.review_passed({"passed": True}, None) is True
    assert MetricCalculator.review_passed(None, {"review_passed": True}) is True
    assert MetricCalculator.review_passed({"passed": "true"}, None) is True
    assert MetricCalculator.review_passed({"passed": False}, None) is False


def test_aggregate():
    samples = [
        EvalSample(
            description="a",
            request_id="r1",
            status="completed",
            review_passed=True,
            file_recall=1.0,
            coverage=0.8,
            coverage_passed=True,
            iterations=2,
            latency=1.0,
        ),
        EvalSample(
            description="b",
            request_id="r2",
            status="failed",
            review_passed=False,
            file_recall=0.5,
            coverage=0.3,
            coverage_passed=False,
            iterations=3,
            latency=2.0,
        ),
    ]
    agg = MetricCalculator.aggregate(samples)
    assert agg["completed"] == 1
    assert agg["failed"] == 1
    assert agg["pass_rate"] == 0.5
    assert agg["file_recall"] == 0.75
    assert agg["avg_iterations"] == 2.5


def test_regression_checker_detects_drop():
    report = EvalReport(
        timestamp="2026-08-11T00:00:00",
        dataset_path="tests/eval_dataset.json",
        max_iterations=3,
        total=2,
        completed=2,
        failed=0,
        errored=0,
        pass_rate=0.6,
        file_recall=0.8,
        file_recall_pass_rate=0.5,
        coverage=0.7,
        coverage_pass_rate=0.5,
        avg_iterations=2.0,
        avg_latency=1.0,
    )
    baseline = {
        "pass_rate": 0.9,
        "file_recall": 0.9,
        "coverage": 0.9,
        "file_recall_pass_rate": 0.9,
        "coverage_pass_rate": 0.9,
    }
    checker = RegressionChecker(tolerance=0.05)
    regressions = checker.check(report, baseline)
    assert len(regressions) == 5  # 所有指标均下降超过 5%


def test_regression_checker_no_baseline():
    report = EvalReport(
        timestamp="2026-08-11T00:00:00",
        dataset_path="tests/eval_dataset.json",
        max_iterations=3,
        total=1,
        completed=1,
        failed=0,
        errored=0,
        pass_rate=1.0,
    )
    checker = RegressionChecker()
    assert checker.check(report, None) == []


def test_regression_baseline_save_and_load(tmp_path: Path):
    report = EvalReport(
        timestamp="2026-08-11T00:00:00",
        dataset_path="tests/eval_dataset.json",
        max_iterations=3,
        total=1,
        completed=1,
        failed=0,
        errored=0,
        pass_rate=1.0,
        file_recall=1.0,
        file_recall_pass_rate=1.0,
        coverage=1.0,
        coverage_pass_rate=1.0,
        avg_iterations=1.0,
        avg_latency=1.0,
    )
    baseline_path = tmp_path / "baseline.json"
    checker = RegressionChecker()
    checker.save_baseline(report, baseline_path)
    loaded = checker.load_baseline(baseline_path)
    assert loaded["pass_rate"] == 1.0
    assert checker.check(report, loaded) == []


def test_evaluation_runner_load_dataset(tmp_path: Path):
    dataset = [
        {"description": "d1", "expected_files": ["main.py"]},
        {"description": "d2", "expected_files": ["main.py", "test_main.py"]},
    ]
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(dataset), encoding="utf-8")

    runner = EvaluationRunner()
    loaded = runner._load_dataset(path)
    assert len(loaded) == 2
    assert loaded[0]["description"] == "d1"


def test_evaluation_runner_mock_orchestrator():
    """用 mock orchestrator 验证 EvaluationRunner 的端到端指标计算。"""
    import tempfile

    async def _run():
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            workspace = tmp_path / "eval-mock"
            workspace.mkdir()
            (workspace / "main.py").write_text("x")
            (workspace / "test_main.py").write_text("y")

            dataset = [
                {
                    "description": "测试任务",
                    "request_id": "eval-mock",
                    "expected_files": ["main.py", "test_main.py"],
                    "min_test_coverage": 0.6,
                }
            ]
            dataset_path = tmp_path / "dataset.json"
            dataset_path.write_text(json.dumps(dataset), encoding="utf-8")

            def factory(max_iter: int):
                class FakeOrchestrator:
                    async def run(self, description, request_id=None, language="python"):
                        return {
                            "request_id": request_id,
                            "status": "completed",
                            "iteration": 2,
                            "artifacts": {"workspace": str(workspace)},
                            "reviewer": {"passed": True},
                            "tester": {"coverage": 0.75},
                        }

                return FakeOrchestrator()

            runner = EvaluationRunner(
                output_dir=tmp_path / "reports",
                orchestrator_factory=factory,
            )
            report = await runner.run(dataset_path, max_iterations=1)
            assert report.total == 1
            assert report.pass_rate == 1.0
            assert report.file_recall == 1.0
            assert report.coverage == 0.75

    asyncio.run(_run())
