"""MCP 风格工具注册与沙箱。"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from dev_agent_system.security import PathValidator, SafetyScanner
from dev_agent_system.security_scanner import ContainerSandbox


class ToolSandbox:
    """MCP 工具沙箱：白名单 + 安全扫描 + 路径限制 + 超时。"""

    ALLOWED_PREFIXES = (
        "python", "pytest", "git", "ls", "cat", "echo", "docker build",
        "mvn", "gradle", "javac", "java", "go", "npm", "npx", "node",
    )
    WORK_DIR = Path("workspace").resolve()

    _write_lock = asyncio.Lock()

    @classmethod
    def read_file(cls, path: str, base_dir: Optional[str] = None) -> Dict[str, Any]:
        work = Path(base_dir).resolve() if base_dir else cls.WORK_DIR
        try:
            target = PathValidator.resolve(work, path)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
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
            try:
                target = PathValidator.resolve(work, path)
            except ValueError as exc:
                return {"success": False, "error": str(exc)}
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                return {"success": True, "path": str(target)}
            except Exception as e:  # noqa: BLE001
                return {"success": False, "error": str(e)}

    @classmethod
    def run_command(cls, command: str, timeout: int = 5, base_dir: Optional[str] = None) -> Dict[str, Any]:
        if not command:
            return {"success": False, "error": "空命令"}
        safe, issues = SafetyScanner.scan_command(command)
        if not safe:
            return {"success": False, "error": f"命令命中安全规则：{', '.join(issues)}"}

        inline_safe, inline_issues = SafetyScanner.inspect_command(command)
        if not inline_safe:
            return {"success": False, "error": f"命令内嵌代码风险：{', '.join(inline_issues)}"}

        if not any(command.strip().startswith(prefix) for prefix in cls.ALLOWED_PREFIXES):
            return {"success": False, "error": f"仅允许以 {cls.ALLOWED_PREFIXES} 开头的命令"}
        work = Path(base_dir).resolve() if base_dir else cls.WORK_DIR

        # 如果启用容器沙箱且 Docker 可用，优先在隔离容器中执行
        if Settings.use_container_sandbox() and ContainerSandbox.is_available():
            try:
                return ContainerSandbox.run(command, work, image=Settings.container_image(), timeout=timeout)
            except Exception as e:  # noqa: BLE001
                return {"success": False, "error": f"容器沙箱执行失败: {e}"}

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=work,
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


from dev_agent_system.config import Settings


ToolSandbox.WORK_DIR = Settings.workspace_dir()


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
        """同步入口：仅调用同步工具；异步工具应使用 ainvoke。"""
        if name not in self._tools:
            return {"success": False, "error": f"未知工具: {name}"}
        fn = self._tools[name]
        if asyncio.iscoroutinefunction(fn):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(fn(**kwargs))
            return {
                "success": False,
                "error": f"工具 {name} 是异步的，请在异步上下文中调用 ainvoke",
            }
        try:
            return fn(**kwargs)
        except Exception as e:  # noqa: BLE001
            return {"success": False, "error": str(e)}

    async def ainvoke(self, name: str, **kwargs) -> Any:
        """异步调用工具，同步工具在后台线程执行，避免阻塞事件循环。"""
        if name not in self._tools:
            return {"success": False, "error": f"未知工具: {name}"}
        fn = self._tools[name]
        try:
            if asyncio.iscoroutinefunction(fn):
                return await fn(**kwargs)
            # 同步工具（如 subprocess.run）在后台线程执行，避免阻塞 async 编排器
            return await asyncio.to_thread(fn, **kwargs)
        except Exception as e:  # noqa: BLE001
            return {"success": False, "error": str(e)}

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": n, "doc": (fn.__doc__ or "")[:120]}
            for n, fn in self._tools.items()
        ]
