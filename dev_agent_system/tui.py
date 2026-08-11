"""终端交互式 UI：用 rich 实时展示多 Agent 工作流进度。"""
from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict, Optional

from dev_agent_system.orchestrator import Orchestrator

try:
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    RICH_AVAILABLE = True
except ImportError:  # pragma: no cover
    RICH_AVAILABLE = False


class OrchestratorTUI:
    """基于 rich 的 Orchestrator 进度面板。"""

    def __init__(self, orchestrator: Optional[Orchestrator] = None):
        if not RICH_AVAILABLE:
            raise RuntimeError(
                "rich is required for TUI. Install it with: pip install rich"
            )
        self.orchestrator = orchestrator or Orchestrator()
        self.events: list = []
        self.request_id: str = ""
        self.current_agent: str = ""
        self.iteration: int = 0
        self.status: str = "submitted"
        self._live: Optional[Live] = None

    def _make_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main", ratio=2),
            Layout(name="footer", size=10),
        )
        layout["main"].split_row(
            Layout(name="agents"),
            Layout(name="metrics"),
        )
        return layout

    def _agent_table(self) -> Table:
        table = Table(title="Agent 执行状态", expand=True)
        table.add_column("Agent", style="cyan")
        table.add_column("状态", style="green")
        agents = [
            ("product_manager", "产品经理"),
            ("architect", "架构师"),
            ("dba", "DBA"),
            ("coder", "编码"),
            ("tester", "测试"),
            ("docs", "文档"),
            ("reviewer", "审查"),
            ("security", "安全"),
            ("devops", "DevOps"),
        ]
        completed_agents = set()
        for evt in self.events:
            if evt.startswith("agent.") and ".end" in evt:
                completed_agents.add(evt.split(":")[0].replace("agent.", "").replace(".end", ""))
        for key, label in agents:
            if self.current_agent == key:
                status = "🔥 运行中"
            elif key in completed_agents:
                status = "✅ 已完成"
            else:
                status = "⏳ 等待"
            table.add_row(label, status)
        return table

    def _metrics_table(self) -> Table:
        table = Table(title="工作流指标", expand=True)
        table.add_column("指标", style="cyan")
        table.add_column("值", style="yellow")
        table.add_row("Request ID", self.request_id or "-")
        table.add_row("迭代", str(self.iteration))
        table.add_row("状态", self.status)
        table.add_row("当前 Agent", self.current_agent or "-")
        return table

    def _log_panel(self) -> Panel:
        lines = self.events[-8:]
        return Panel("\n".join(lines) if lines else "等待开始...", title="最近事件")

    def _header(self) -> Panel:
        return Panel(
            Text("DevAgent System — 多 Agent 软件开发工作流", style="bold magenta"),
            style="bold white on blue",
        )

    def _render(self) -> Layout:
        layout = self._make_layout()
        layout["header"].update(self._header())
        layout["main"]["agents"].update(self._agent_table())
        layout["main"]["metrics"].update(self._metrics_table())
        layout["footer"].update(self._log_panel())
        return layout

    def _sync_from_tracker(self) -> None:
        record = self.orchestrator.tracker.get(self.request_id)
        if record is not None:
            self.current_agent = record.current_agent
            self.iteration = record.iteration
            self.status = record.status

    def _on_event(self, name: str, data: Any = "") -> None:
        self.events.append(f"{name}: {data}")

    async def _poll(self) -> None:
        while self.status not in ("completed", "failed", "skipped"):
            self._sync_from_tracker()
            if self._live:
                self._live.update(self._render())
            await asyncio.sleep(0.2)

    async def _run_workflow(self, requirement: str, request_id: Optional[str] = None) -> Dict[str, Any]:
        result = await self.orchestrator.run(requirement, request_id)
        self.request_id = result.get("request_id", self.request_id)
        self._sync_from_tracker()
        self._on_event("workflow.completed", result.get("status"))
        return result

    async def _run(self, requirement: str, request_id: Optional[str] = None) -> Dict[str, Any]:
        with Live(self._render(), refresh_per_second=4) as live:
            self._live = live
            try:
                return await asyncio.gather(
                    self._run_workflow(requirement, request_id),
                    self._poll(),
                )[0]
            finally:
                self._live = None

    def run(self, requirement: str, request_id: Optional[str] = None) -> Dict[str, Any]:
        return asyncio.run(self._run(requirement, request_id))


def main() -> None:
    if not RICH_AVAILABLE:
        print("rich is required. Install it with: pip install rich", file=sys.stderr)
        sys.exit(1)
    requirement = (
        " ".join(sys.argv[1:])
        if len(sys.argv) > 1
        else "开发一个支持 JWT 的用户登录模块"
    )
    tui = OrchestratorTUI()
    result = tui.run(requirement)
    print(
        f"\n工作流结束：{result.get('status')}，"
        f"产物目录：{result.get('artifacts', {}).get('workspace', 'N/A')}"
    )


if __name__ == "__main__":
    main()
