"""安全沙箱对抗测试：验证常见绕过手段是否被拦截。"""
from __future__ import annotations

import pytest

from dev_agent_system.mcp import ToolSandbox
from dev_agent_system.security import PathValidator, SafetyScanner


def test_safety_scan_command_blocks_obfuscated_rm():
    """大小写/多余空格不应绕过 rm -rf 黑名单。"""
    safe, issues = SafetyScanner.scan_command("  Rm  -rf  /tmp/test")
    assert not safe


def test_safety_scan_command_detects_rm_in_python_c():
    """python -c 字符串中直接出现 rm -rf 应被命令层黑名单拦截。"""
    safe, issues = SafetyScanner.scan_command("python -c \"import os; os.system('rm -rf /')\"")
    assert not safe


def test_inspect_command_blocks_inline_os_system():
    """python -c 内嵌 os.system 属于内联代码 high 风险，应被 inspect_command 拦截。"""
    safe, issues = SafetyScanner.inspect_command("python -c \"import os; os.system('echo pwned')\"")
    assert not safe
    assert any("os.system" in i for i in issues)


def test_inspect_command_blocks_inline_eval():
    """python -c 内嵌 eval 应被拦截。"""
    safe, issues = SafetyScanner.inspect_command("python -c \"x=eval('1+1')\"")
    assert not safe


def test_inspect_command_allows_safe_python_print():
    """普通的 python -c 'print(...)' 应允许。"""
    safe, issues = SafetyScanner.inspect_command("python -c \"print('hello')\"")
    assert safe


def test_path_validator_blocks_encoded_traversal(tmp_path):
    base = tmp_path / "workspace"
    base.mkdir()
    # 使用多种路径拼接方式尝试目录穿越
    for rel in ("../etc/passwd", "foo/../../etc/passwd", "./../secret"):
        with pytest.raises(ValueError, match="路径越界"):
            PathValidator.resolve(base, rel)


def test_tool_sandbox_python_c_with_rm_blocked(tmp_path, monkeypatch):
    """通过 python -c 调用 rm 应被拦截，避免命令前缀白名单绕过。"""
    ToolSandbox.WORK_DIR = tmp_path
    result = ToolSandbox.run_command("python -c \"import os; os.system('rm -rf /tmp/test')\"")
    assert result["success"] is False
    # 既可能命中安全规则，也可能命中内联代码风险
    assert "安全" in result["error"] or "风险" in result["error"]
