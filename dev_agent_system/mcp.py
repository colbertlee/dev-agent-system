"""MCP 风格工具注册与沙箱。"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class ToolSandbox:
    """MCP 工具沙箱：白名单 + 黑名单 + 路径限制 + 超时。"""

    BLACKLIST = re.compile(
        r"(rm\s+-rf\s*/|>\s*/dev/null\s*;|&&\s*rm\b|\|\s*sh\b|curl\s+.*\|.*sh|\|\s*bash|wget\s+-O-)",
        re.I,
    )
    ALLOWED_PREFIXES = ("python", "pytest", "git", "ls", "cat", "echo", "docker build")
    WORK_DIR = Path("workspace").resolve()

    _write_lock = asyncio.Lock()

    @classmethod
    def _safe_path(cls, relative_path: str) -> Path:
        target = (cls.WORK_DIR / relative_path).resolve()
        try:
            target.relative_to(cls.WORK_DIR)
        except ValueError as exc:
            raise ValueError("路径越界：禁止访问工作目录之外") from exc
        return target

    @classmethod
    def read_file(cls, path: str, base_dir: Optional[str] = None) -> Dict[str, Any]:
        work = Path(base_dir).resolve() if base_dir else cls.WORK_DIR
        target = (work / path).resolve()
        try:
            target.relative_to(work)
        except ValueError:
            return {"success": False, "error": "路径越界"}
        if not target.exists():
            return {"success": False, "error": "文件不存在"}
        try:
            return {"success": True, "content": target.read_text(encoding="utf-8")}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "error": str(e)}

    @classmethod
    async def write_file(
        cls, path: str, content: str, base_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        async with cls._write_lock:
            work = Path(base_dir).resolve() if base_dir else cls.WORK_DIR
            target = (work / path).resolve()
            try:
                target.relative_to(work)
            except ValueError:
                return {"success": False, "error": "路径越界"}
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                return {"success": True, "path": str(target)}
            except Exception as e:  # noqa: BLE001
                return {"success": False, "error": str(e)}

    @classmethod
    def run_command(cls, command: str, timeout: int = 5) -> Dict[str, Any]:
        if not command:
            return {"success": False, "error": "空命令"}
        if cls.BLACKLIST.search(command):
            return {"success": False, "error": "命令命中黑名单"}
        if not any(command.strip().startswith(prefix) for prefix in cls.ALLOWED_PREFIXES):
            return {"success": False, "error": f"仅允许以 {cls.ALLOWED_PREFIXES} 开头的命令"}
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cls.WORK_DIR,
            )
            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"命令执行超过 {timeout} 秒"}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "error": str(e)}


class MCPToolRegistry:
    """MCP 工具注册中心。"""

    def __init__(self):
        self._tools: Dict[str, Callable[..., Any]] = {
            "read_file": ToolSandbox.read_file,
            "write_file": ToolSandbox.write_file,
            "run_command": ToolSandbox.run_command,
        }

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        self._tools[name] = fn

    def call(self, name: str, **kwargs) -> Any:
        if name not in self._tools:
            return {"success": False, "error": f"未知工具: {name}"}
        fn = self._tools[name]
        try:
            if asyncio.iscoroutinefunction(fn):
                return asyncio.run(fn(**kwargs))
            return fn(**kwargs)
        except Exception as e:  # noqa: BLE001
            return {"success": False, "error": str(e)}

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": n, "doc": (fn.__doc__ or "")[:120]}
            for n, fn in self._tools.items()
        ]
