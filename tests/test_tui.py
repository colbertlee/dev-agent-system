"""TUI 相关单元测试。"""
from __future__ import annotations

import pytest


def test_orchestrator_tracker_update():
    """Tracker 能被 Orchestrator 写入并读取。"""
    from dev_agent_system.tracker import WorkflowTracker

    tracker = WorkflowTracker()
    tracker.start("tui-req-1", "开发一个加法模块")
    tracker.update("tui-req-1", current_agent="coder", iteration=1, status="working")

    snapshot = tracker.snapshot("tui-req-1")
    assert snapshot["current_agent"] == "coder"
    assert snapshot["iteration"] == 1
    assert snapshot["status"] == "working"


def test_tui_class_available_when_rich_installed():
    """安装 rich 后可实例化 OrchestratorTUI。"""
    pytest.importorskip("rich", reason="rich is optional for TUI")
    from dev_agent_system.tui import OrchestratorTUI

    tui = OrchestratorTUI()
    assert tui.orchestrator is not None
