"""最小版 Skill 管理器：支持发现、安装、卸载、调用与 MCP 注册。

一个 Skill 包结构：
    skills/<skill_id>/
        SKILL.md       # YAML frontmatter + 自由文本
        skill.py       # 可选，必须定义 run(*args, **kwargs) 函数

`SKILL.md` 示例：
    ---
    id: add-tool
    name: 加法工具
    description: 返回两个数字的和
    ---
    调用时把两个数字作为参数传入。
"""
from __future__ import annotations

import importlib.util
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, List, Optional, Union

from dev_agent_system.config import Settings


@dataclass
class Skill:
    """Skill 元数据。"""

    id: str
    name: str
    description: str
    prompt: str = ""
    path: Optional[Path] = None
    module: Optional[ModuleType] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def has_runner(self) -> bool:
        return self.module is not None and callable(getattr(self.module, "run", None))

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        """执行 Skill 的 run 函数，无代码时返回提示文本。"""
        if not self.has_runner():
            return {
                "success": False,
                "error": f"Skill '{self.id}' 没有可执行代码，请在 {self.path or 'N/A'} 中实现 run()",
            }
        try:
            return self.module.run(*args, **kwargs)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc)}


class SkillStore:
    """本地 Skill 仓库：扫描、加载、持久化。"""

    SKILL_FILENAME = "SKILL.md"
    CODE_FILENAME = "skill.py"

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir or Settings.skills_dir())
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._skills: Dict[str, Skill] = {}
        self.reload()

    def reload(self) -> None:
        """重新扫描 skills 目录。"""
        self._skills = {}
        if not self.base_dir.exists():
            return
        for path in self.base_dir.iterdir():
            if path.is_dir() and (path / self.SKILL_FILENAME).exists():
                skill = self._load_skill(path)
                if skill:
                    self._skills[skill.id] = skill

    def _load_skill(self, skill_dir: Path) -> Optional[Skill]:
        skill_file = skill_dir / self.SKILL_FILENAME
        try:
            raw = skill_file.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            return None

        meta: Dict[str, Any] = {}
        prompt = raw
        match = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.DOTALL)
        if match:
            try:
                import yaml
                meta = yaml.safe_load(match.group(1)) or {}
                prompt = match.group(2).strip()
            except Exception:  # noqa: BLE001
                pass

        skill_id = str(meta.get("id", skill_dir.name))
        name = str(meta.get("name", skill_id))
        description = str(meta.get("description", ""))

        module = None
        code_file = skill_dir / self.CODE_FILENAME
        if code_file.exists():
            module = self._load_module(skill_id, code_file)

        return Skill(
            id=skill_id,
            name=name,
            description=description,
            prompt=prompt,
            path=skill_dir,
            module=module,
            metadata=meta,
        )

    def _load_module(self, module_name: str, code_file: Path) -> Optional[ModuleType]:
        spec = importlib.util.spec_from_file_location(module_name, code_file)
        if not spec or not spec.loader:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def list(self) -> List[Skill]:
        return list(self._skills.values())

    def get(self, skill_id: str) -> Optional[Skill]:
        return self._skills.get(skill_id)

    def exists(self, skill_id: str) -> bool:
        return skill_id in self._skills

    def uninstall(self, skill_id: str) -> bool:
        if skill_id not in self._skills:
            return False
        skill_dir = self._skills[skill_id].path or self.base_dir / skill_id
        if skill_dir and skill_dir.exists():
            shutil.rmtree(skill_dir)
        del self._skills[skill_id]
        return True

    def install_path(self, source_dir: Union[str, Path]) -> Skill:
        """从本地目录安装 Skill。"""
        src = Path(source_dir).resolve()
        if not src.exists() or not src.is_dir():
            raise ValueError(f"Skill 路径不存在：{source_dir}")
        skill_file = src / self.SKILL_FILENAME
        if not skill_file.exists():
            raise ValueError(f"缺少 {self.SKILL_FILENAME}：{source_dir}")

        # 读取 id 决定目标目录
        raw = skill_file.read_text(encoding="utf-8")
        skill_id = src.name
        match = re.match(r"^---\n(.*?)\n---\n", raw, re.DOTALL)
        if match:
            try:
                import yaml

                meta = yaml.safe_load(match.group(1)) or {}
                skill_id = str(meta.get("id", skill_id))
            except Exception:  # noqa: BLE001
                pass

        target = self.base_dir / skill_id
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(src, target)
        self.reload()
        skill = self.get(skill_id)
        if not skill:
            raise RuntimeError(f"安装后仍无法加载 Skill：{skill_id}")
        return skill


class SkillManager:
    """Skill 管理器：安装、卸载、调用与向 MCP 注册。"""

    def __init__(self, store: Optional[SkillStore] = None):
        self.store = store or SkillStore()

    def list(self) -> List[Skill]:
        return self.store.list()

    def get(self, skill_id: str) -> Optional[Skill]:
        return self.store.get(skill_id)

    def install(
        self,
        source: Union[str, Path, Dict[str, Any]],
        overwrite: bool = True,
    ) -> Skill:
        """安装一个 Skill。

        source 可以是：
        - 本地目录路径（含 SKILL.md）
        - 字典：{id, name, description, prompt, code?}，自动生成 Skill 包
        """
        if isinstance(source, dict):
            return self._install_from_dict(source, overwrite=overwrite)
        return self.store.install_path(source)

    def _install_from_dict(self, data: Dict[str, Any], overwrite: bool) -> Skill:
        skill_id = data.get("id") or data.get("name", "unnamed")
        skill_id = re.sub(r"[^\w\-]+", "-", str(skill_id)).strip("-").lower() or "skill"
        target = self.store.base_dir / skill_id
        if target.exists():
            if not overwrite:
                raise FileExistsError(f"Skill '{skill_id}' 已存在")
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)

        meta = {
            "id": skill_id,
            "name": data.get("name", skill_id),
            "description": data.get("description", ""),
        }
        meta.update({k: v for k, v in data.items() if k not in ("id", "name", "description", "code", "prompt")})

        import yaml

        prompt = data.get("prompt", "")
        skill_md = f"---\n{yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)}---\n\n{prompt}\n"
        (target / self.store.SKILL_FILENAME).write_text(skill_md, encoding="utf-8")

        code = data.get("code", self._default_skill_code(skill_id))
        (target / self.store.CODE_FILENAME).write_text(code, encoding="utf-8")

        self.store.reload()
        skill = self.store.get(skill_id)
        if not skill:
            raise RuntimeError(f"安装后仍无法加载 Skill：{skill_id}")
        return skill

    @staticmethod
    def _default_skill_code(skill_id: str) -> str:
        return (
            f"\"\"\"Auto-generated skill: {skill_id}.\"\"\"\n"
            f"\n"
            f"def run(*args, **kwargs):\n"
            f"    \"\"\"实现你的 Skill 逻辑。\"\"\"\n"
            f"    return {{\"success\": True, \"message\": f\"'{skill_id}' executed\", \"args\": args, \"kwargs\": kwargs}}\n"
        )

    def uninstall(self, skill_id: str) -> bool:
        return self.store.uninstall(skill_id)

    def find(self, query: str, limit: int = 5) -> List[Skill]:
        """按 id/name/description 关键词匹配 Skill。"""
        query_lower = query.lower()
        scored: List[tuple] = []
        for skill in self.list():
            score = 0
            text = f"{skill.id} {skill.name} {skill.description}".lower()
            if query_lower in skill.id.lower():
                score += 3
            if query_lower in skill.name.lower():
                score += 2
            if query_lower in skill.description.lower():
                score += 1
            if query_lower in text:
                scored.append((score, skill))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for score, s in scored[:limit] if score > 0]

    def invoke(self, skill_id: str, *args: Any, **kwargs: Any) -> Any:
        skill = self.get(skill_id)
        if not skill:
            return {"success": False, "error": f"Skill '{skill_id}' 不存在"}
        return skill.invoke(*args, **kwargs)

    def register_to_mcp(self, registry: Any, prefix: str = "skill_") -> None:
        """把所有带 runner 的 Skill 注册为 MCP 工具。"""
        for skill in self.list():
            if not skill.has_runner():
                continue
            tool_name = f"{prefix}{skill.id}"

            def make_wrapper(s: Skill) -> Callable[..., Any]:
                def wrapper(*args: Any, **kwargs: Any) -> Any:
                    return s.invoke(*args, **kwargs)

                wrapper.__doc__ = f"{s.name}: {s.description}\n\n{s.prompt[:500]}"
                return wrapper

            registry.register(tool_name, make_wrapper(skill))


# 默认全局管理器
def get_default_manager() -> SkillManager:
    return SkillManager()
