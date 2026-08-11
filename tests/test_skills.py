"""SkillManager 单元测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from dev_agent_system.skills import SkillManager, SkillStore


def test_skill_store_empty(tmp_path: Path):
    store = SkillStore(base_dir=tmp_path / "skills")
    assert store.list() == []


def test_install_skill_from_dict(tmp_path: Path):
    manager = SkillManager(SkillStore(base_dir=tmp_path / "skills"))
    skill = manager.install(
        {
            "id": "add-tool",
            "name": "加法工具",
            "description": "返回两个数字的和",
            "prompt": "把输入的两个数字相加。",
            "code": "def run(a, b):\n    return {'success': True, 'result': a + b}\n",
        }
    )
    assert skill.id == "add-tool"
    assert skill.name == "加法工具"
    assert (skill.path / "SKILL.md").exists()
    assert (skill.path / "skill.py").exists()


def test_invoke_installed_skill(tmp_path: Path):
    manager = SkillManager(SkillStore(base_dir=tmp_path / "skills"))
    manager.install(
        {
            "id": "add-tool",
            "name": "加法工具",
            "code": "def run(a, b):\n    return {'success': True, 'result': a + b}\n",
        }
    )
    result = manager.invoke("add-tool", 1, 2)
    assert result["success"] is True
    assert result["result"] == 3


def test_invoke_missing_skill(tmp_path: Path):
    manager = SkillManager(SkillStore(base_dir=tmp_path / "skills"))
    result = manager.invoke("missing")
    assert result["success"] is False
    assert "不存在" in result["error"]


def test_uninstall_skill(tmp_path: Path):
    manager = SkillManager(SkillStore(base_dir=tmp_path / "skills"))
    manager.install({"id": "temp", "code": "def run(): pass"})
    assert manager.get("temp") is not None
    assert manager.uninstall("temp") is True
    assert manager.get("temp") is None
    assert manager.uninstall("temp") is False


def test_install_from_local_path(tmp_path: Path):
    src = tmp_path / "src_skill"
    src.mkdir()
    (src / "SKILL.md").write_text(
        "---\nid: local-skill\nname: 本地测试\n---\n这是一个本地 skill。\n",
        encoding="utf-8",
    )
    (src / "skill.py").write_text(
        "def run():\n    return {'success': True}\n", encoding="utf-8"
    )

    manager = SkillManager(SkillStore(base_dir=tmp_path / "skills"))
    skill = manager.install(src)
    assert skill.id == "local-skill"
    assert skill.invoke()["success"] is True


def test_register_to_mcp(tmp_path: Path):
    from dev_agent_system.mcp import MCPToolRegistry

    manager = SkillManager(SkillStore(base_dir=tmp_path / "skills"))
    manager.install(
        {
            "id": "greet",
            "name": "问候",
            "code": "def run(name='world'):\n    return {'success': True, 'message': f'Hello, {name}'}\n",
        }
    )
    registry = MCPToolRegistry()
    manager.register_to_mcp(registry)
    assert "skill_greet" in [t["name"] for t in registry.list_tools()]
    assert registry._tools["skill_greet"](name="dev")["message"] == "Hello, dev"
