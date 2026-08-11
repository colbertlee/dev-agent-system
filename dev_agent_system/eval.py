"""评估与指标体系：基于 eval_dataset.json 跑 benchmark，产出多维度指标报告。"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from dev_agent_system.config import Settings
from dev_agent_system.orchestrator import Orchestrator


class EvalSample(BaseModel):
    """单个评估样本的结果与指标。"""

    description: str
    request_id: str
    status: str
    review_passed: bool = False
    file_recall: float = 0.0
    found_files: List[str] = Field(default_factory=list)
    missing_files: List[str] = Field(default_factory=list)
    coverage: float = 0.0
    coverage_passed: bool = False
    min_test_coverage: float = 0.0
    iterations: int = 0
    latency: float = 0.0
    expected_files: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class EvalReport(BaseModel):
    """评估聚合报告。"""

    timestamp: str
    dataset_path: str
    max_iterations: int
    total: int
    completed: int
    failed: int
    errored: int
    pass_rate: float = 0.0
    file_recall: float = 0.0
    file_recall_pass_rate: float = 0.0
    coverage: float = 0.0
    coverage_pass_rate: float = 0.0
    avg_iterations: float = 0.0
    avg_latency: float = 0.0
    samples: List[EvalSample] = Field(default_factory=list)


class MetricCalculator:
    """静态指标计算器，保持与 Orchestrator 解耦，便于单元测试。"""

    @staticmethod
    def file_recall(workspace: Path, expected_files: List[str]) -> Tuple[float, List[str], List[str]]:
        """计算期望文件召回率。"""
        found: List[str] = []
        missing: List[str] = []
        for name in expected_files:
            matches = list(workspace.rglob(name))
            if matches and any(m.is_file() for m in matches):
                found.append(name)
            else:
                missing.append(name)
        recall = len(found) / len(expected_files) if expected_files else 1.0
        return recall, found, missing

    @staticmethod
    def coverage(tester: Optional[Dict[str, Any]]) -> float:
        """从 Tester 结果或 pytest 输出中提取覆盖率（0~1）。"""
        if not tester:
            return 0.0
        cov = tester.get("coverage")
        if isinstance(cov, (int, float)):
            return float(cov)
        report = tester.get("report", "")
        m = re.search(r"(\d+)%", report)
        if m:
            return float(m.group(1)) / 100.0
        return 0.0

    @staticmethod
    def review_passed(reviewer: Optional[Dict[str, Any]], artifacts: Optional[Dict[str, Any]]) -> bool:
        """判断 Reviewer 是否通过，优先使用 artifacts 里的汇总字段。"""
        if artifacts and "review_passed" in artifacts:
            return bool(artifacts["review_passed"])
        if reviewer:
            return bool(reviewer.get("passed"))
        return False

    @staticmethod
    def aggregate(samples: List[EvalSample]) -> Dict[str, float]:
        """对样本列表做聚合统计。"""
        if not samples:
            return {}
        total = len(samples)
        completed = sum(1 for s in samples if s.status == "completed")
        failed = sum(1 for s in samples if s.status == "failed")
        errored = sum(1 for s in samples if s.status == "error")
        return {
            "pass_rate": sum(1 for s in samples if s.review_passed and s.status == "completed") / total,
            "file_recall": sum(s.file_recall for s in samples) / total,
            "file_recall_pass_rate": sum(1 for s in samples if s.file_recall >= 1.0) / total,
            "coverage": sum(s.coverage for s in samples) / total,
            "coverage_pass_rate": sum(1 for s in samples if s.coverage_passed) / total,
            "avg_iterations": sum(s.iterations for s in samples) / total,
            "avg_latency": sum(s.latency for s in samples) / total,
            "completed": completed,
            "failed": failed,
            "errored": errored,
        }


class EvaluationRunner:
    """评估运行器：加载数据集，逐个运行任务，计算并保存指标。"""

    def __init__(
        self,
        output_dir: Optional[Path] = None,
        max_workers: int = 1,
        orchestrator_factory: Optional[Callable[[int], Orchestrator]] = None,
    ):
        self.output_dir = Path(output_dir or Settings.eval_output_dir()).resolve()
        self.max_workers = max_workers
        self.orchestrator_factory = orchestrator_factory or (lambda max_iter: Orchestrator(max_iterations=max_iter))

    async def run(self, dataset_path: Path, max_iterations: int = 3) -> EvalReport:
        """运行整个数据集并返回聚合报告。"""
        dataset = self._load_dataset(dataset_path)
        samples: List[EvalSample] = []
        # 默认顺序执行，避免 SQLite checkpoint 并发锁；后续可按 max_workers 扩展
        for idx, item in enumerate(dataset):
            sample = await self._evaluate_one(idx, item, max_iterations)
            samples.append(sample)

        agg = MetricCalculator.aggregate(samples)
        report = EvalReport(
            timestamp=datetime.now().isoformat(),
            dataset_path=str(dataset_path),
            max_iterations=max_iterations,
            total=len(samples),
            completed=int(agg.get("completed", 0)),
            failed=int(agg.get("failed", 0)),
            errored=int(agg.get("errored", 0)),
            pass_rate=agg.get("pass_rate", 0.0),
            file_recall=agg.get("file_recall", 0.0),
            file_recall_pass_rate=agg.get("file_recall_pass_rate", 0.0),
            coverage=agg.get("coverage", 0.0),
            coverage_pass_rate=agg.get("coverage_pass_rate", 0.0),
            avg_iterations=agg.get("avg_iterations", 0.0),
            avg_latency=agg.get("avg_latency", 0.0),
            samples=samples,
        )
        self._save_report(report)
        return report

    def _load_dataset(self, dataset_path: Path) -> List[Dict[str, Any]]:
        with open(dataset_path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("Dataset must be a JSON list")
        return data

    async def _evaluate_one(self, idx: int, item: Dict[str, Any], max_iterations: int) -> EvalSample:
        description = item.get("description", "")
        request_id = item.get("request_id") or f"eval-{idx}"
        expected_files = item.get("expected_files", [])
        min_coverage = float(item.get("min_test_coverage", 0.0) or 0.0)
        start = time.perf_counter()
        try:
            orch = self.orchestrator_factory(max_iterations)
            result = await orch.run(description, request_id=request_id)
            status = result.get("status", "unknown")
            artifacts = result.get("artifacts", {}) or {}
            workspace = Path(
                artifacts.get("workspace") or (Settings.workspace_dir() / request_id)
            )
            reviewer = result.get("reviewer") or {}
            tester = result.get("tester") or {}
            recall, found, missing = MetricCalculator.file_recall(workspace, expected_files)
            coverage = MetricCalculator.coverage(tester)
            sample = EvalSample(
                description=description,
                request_id=request_id,
                status=status,
                review_passed=MetricCalculator.review_passed(reviewer, artifacts),
                file_recall=recall,
                found_files=found,
                missing_files=missing,
                coverage=coverage,
                coverage_passed=coverage >= min_coverage,
                min_test_coverage=min_coverage,
                iterations=result.get("iteration", 0),
                latency=time.perf_counter() - start,
                expected_files=expected_files,
            )
        except Exception as exc:  # noqa: BLE001
            sample = EvalSample(
                description=description,
                request_id=request_id,
                status="error",
                error=str(exc),
                min_test_coverage=min_coverage,
                latency=time.perf_counter() - start,
                expected_files=expected_files,
            )
        return sample

    def _save_report(self, report: EvalReport) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = self.output_dir / f"eval_report_{timestamp}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report.model_dump(), f, ensure_ascii=False, indent=2)
        md_path = self.output_dir / f"eval_report_{timestamp}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(self._markdown_summary(report))
        return json_path

    def _markdown_summary(self, report: EvalReport) -> str:
        lines = [
            f"# 评估报告 ({report.timestamp})",
            "",
            f"- 数据集：`{report.dataset_path}`",
            f"- 最大迭代次数：{report.max_iterations}",
            f"- 总任务数：{report.total}",
            f"- 完成 / 失败 / 异常：{report.completed} / {report.failed} / {report.errored}",
            "",
            "| 指标 | 数值 |",
            "|---|---|",
            f"| 通过率 | {report.pass_rate:.2%} |",
            f"| 平均文件召回率 | {report.file_recall:.2%} |",
            f"| 文件召回达标率 | {report.file_recall_pass_rate:.2%} |",
            f"| 平均测试覆盖率 | {report.coverage:.2%} |",
            f"| 覆盖率达标率 | {report.coverage_pass_rate:.2%} |",
            f"| 平均迭代次数 | {report.avg_iterations:.2f} |",
            f"| 平均耗时 | {report.avg_latency:.2f}s |",
            "",
            "## 各样本明细",
            "",
            "| 任务 | 状态 | 通过 | 文件召回 | 覆盖率 | 迭代 | 耗时 |",
            "|---|---|---|---|---|---|---|",
        ]
        for s in report.samples:
            lines.append(
                f"| {s.description[:40]}... | {s.status} | {s.review_passed} | {s.file_recall:.2%} | {s.coverage:.2%} | {s.iterations} | {s.latency:.2f}s |"
            )
        return "\n".join(lines)


class RegressionChecker:
    """与基准报告对比，检测指标回退。"""

    METRICS: List[str] = [
        "pass_rate",
        "file_recall",
        "file_recall_pass_rate",
        "coverage",
        "coverage_pass_rate",
    ]

    def __init__(self, tolerance: float = 0.05):
        self.tolerance = tolerance

    def load_baseline(self, path: Path) -> Optional[Dict[str, Any]]:
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def check(self, report: EvalReport, baseline: Optional[Dict[str, Any]]) -> List[str]:
        """返回所有指标回退的列表。baseline 为 None 时返回空列表。"""
        regressions: List[str] = []
        if not baseline:
            return regressions
        for key in self.METRICS:
            current = float(getattr(report, key, 0.0))
            prev = float(baseline.get(key, current))
            if current < prev - self.tolerance:
                regressions.append(
                    f"{key}: {prev:.4f} -> {current:.4f} (下降超过 {self.tolerance:.1%})"
                )
        return regressions

    def save_baseline(self, report: EvalReport, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        baseline = {key: round(float(getattr(report, key, 0.0)), 4) for key in self.METRICS}
        baseline["timestamp"] = report.timestamp
        with open(path, "w", encoding="utf-8") as f:
            json.dump(baseline, f, ensure_ascii=False, indent=2)


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="多 Agent 系统评估 benchmark")
    parser.add_argument("--dataset", default="tests/eval_dataset.json", help="评估数据集 JSON 路径")
    parser.add_argument("--output-dir", default=None, help="报告输出目录")
    parser.add_argument("--max-iter", type=int, default=3, help="每个任务最大迭代次数")
    parser.add_argument(
        "--max-workers",
        type=int,
        default=1,
        help="并发任务数（默认 1，避免 SQLite checkpoint 锁）",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="基准报告 JSON 路径（默认 output_dir/eval_baseline.json）",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="将本次结果保存为新的 baseline",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.05,
        help="允许指标下降的最大容忍度（默认 0.05 = 5%）",
    )
    return parser.parse_args(argv)


async def main_async(argv: Optional[List[str]] = None) -> EvalReport:
    args = _parse_args(argv)
    runner = EvaluationRunner(output_dir=args.output_dir, max_workers=args.max_workers)
    report = await runner.run(Path(args.dataset), max_iterations=args.max_iter)
    print(
        f"评估完成：total={report.total}, completed={report.completed}, "
        f"pass_rate={report.pass_rate:.2%}, file_recall={report.file_recall:.2%}, "
        f"coverage={report.coverage:.2%}"
    )
    print(f"报告已保存：{runner.output_dir}")

    baseline_path = args.baseline or (runner.output_dir / "eval_baseline.json")
    checker = RegressionChecker(tolerance=args.tolerance)

    if args.update_baseline:
        checker.save_baseline(report, baseline_path)
        print(f"已更新 baseline：{baseline_path}")
    else:
        baseline = checker.load_baseline(baseline_path)
        regressions = checker.check(report, baseline)
        if regressions:
            print("检测到指标回退：")
            for r in regressions:
                print(f"  - {r}")
            raise SystemExit(1)
        elif baseline:
            print("未检测到指标回退，基准通过。")

    return report


def main(argv: Optional[List[str]] = None) -> None:
    try:
        asyncio.run(main_async(argv))
    except SystemExit as exc:
        raise


if __name__ == "__main__":
    main()
