"""安全加固进阶相关单元测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from dev_agent_system.security_scanner import ContainerSandbox, SecretScanner


def test_secret_scanner_detects_api_key(tmp_path: Path):
    file = tmp_path / "config.py"
    file.write_text('api_key = "sk-abcdefghijklmnopqrstuvwxyz1234567890"\n', encoding="utf-8")
    findings = SecretScanner.scan_file(file)
    assert len(findings) >= 1
    assert any("API" in f["reason"] for f in findings)


def test_secret_scanner_clean_file(tmp_path: Path):
    file = tmp_path / "clean.py"
    file.write_text('print("hello world")\n', encoding="utf-8")
    findings = SecretScanner.scan_file(file)
    assert findings == []


def test_container_sandbox_command_building(tmp_path: Path):
    cmd = ContainerSandbox.build_command("pytest -q", tmp_path)
    assert "docker run --rm --network none" in cmd
    assert str(tmp_path.resolve()) in cmd
    assert "pytest -q" in cmd


def test_dependency_scanner_skips_missing_file(tmp_path: Path):
    from dev_agent_system.security_scanner import DependencyScanner

    missing = tmp_path / "missing.txt"
    findings = DependencyScanner.scan_requirements(missing)
    assert findings[0]["status"] == "skipped"
