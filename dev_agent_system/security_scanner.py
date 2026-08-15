"""安全加固进阶：依赖漏洞扫描、Secret 扫描、容器沙箱。"""
from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class SecretScanner:
    """在工作区文件与文本中扫描高置信度 Secret 模式。"""

    PATTERNS: List[Tuple[str, str]] = [
        (r"sk-[a-zA-Z0-9]{20,}", "OpenAI/Anthropic API Key"),
        (r"ghp_[a-zA-Z0-9]{36}", "GitHub Personal Access Token"),
        (r"glpat-[a-zA-Z0-9-]{20}", "GitLab Personal Access Token"),
        (r"AKIA[0-9A-Z]{16}", "AWS Access Key ID"),
        (r"[0-9a-zA-Z/+]{40}", "AWS Secret Access Key (heuristic)"),
        (r"private[_-]?key\s*[:=]\s*['\"]?-----BEGIN", "Private Key"),
        (r"password\s*[:=]\s*['\"][^'\"]{8,}['\"]", "Hard-coded password"),
        (r"api[_-]?key\s*[:=]\s*['\"][a-zA-Z0-9_\-]{16,}['\"]", "Generic API key"),
    ]

    @classmethod
    def scan_text(cls, text: str, source: str = "<text>") -> List[Dict[str, Any]]:
        findings: List[Dict[str, Any]] = []
        for pattern, reason in cls.PATTERNS:
            for m in re.finditer(pattern, text, re.I):
                snippet = text[max(0, m.start() - 10) : min(len(text), m.end() + 10)]
                findings.append(
                    {
                        "source": source,
                        "reason": reason,
                        "line": text[: m.start()].count("\n") + 1,
                        "snippet": snippet,
                    }
                )
        return findings

    @classmethod
    def scan_file(cls, path: Path) -> List[Dict[str, Any]]:
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            return []
        return cls.scan_text(text, source=str(path))

    @classmethod
    def scan_workspace(cls, workspace: Path) -> List[Dict[str, Any]]:
        findings: List[Dict[str, Any]] = []
        for p in workspace.rglob("*"):
            if p.is_file() and p.stat().st_size < 1024 * 1024:  # 忽略超过 1MB 文件
                findings.extend(cls.scan_file(p))
        return findings


class DependencyScanner:
    """依赖漏洞扫描：优先 safety，回退 pip-audit，都未安装则返回提示。"""

    @staticmethod
    def _has_tool(name: str) -> bool:
        try:
            subprocess.run([name, "--version"], capture_output=True, check=False, timeout=5)
            return True
        except Exception:  # noqa: BLE001
            return False

    @classmethod
    def scan_requirements(cls, requirements_path: Path) -> List[Dict[str, Any]]:
        findings: List[Dict[str, Any]] = []
        if not requirements_path.exists():
            findings.append(
                {
                    "tool": "dependency_scanner",
                    "status": "skipped",
                    "reason": f"{requirements_path} 不存在",
                }
            )
            return findings

        if cls._has_tool("safety"):
            return cls._run_safety(requirements_path)
        if cls._has_tool("pip-audit"):
            return cls._run_pip_audit(requirements_path)

        return [
            {
                "tool": "dependency_scanner",
                "status": "skipped",
                "reason": "未安装 safety 或 pip-audit，跳过依赖漏洞扫描",
            }
        ]

    @classmethod
    def _run_safety(cls, path: Path) -> List[Dict[str, Any]]:
        try:
            result = subprocess.run(
                ["safety", "check", "-r", str(path), "--json"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            return [
                {
                    "tool": "safety",
                    "status": "completed",
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            ]
        except subprocess.TimeoutExpired:
            return [{"tool": "safety", "status": "timeout"}]
        except Exception as exc:  # noqa: BLE001
            return [{"tool": "safety", "status": "error", "reason": str(exc)}]

    @classmethod
    def _run_pip_audit(cls, path: Path) -> List[Dict[str, Any]]:
        try:
            result = subprocess.run(
                ["pip-audit", "-r", str(path), "--format=json"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            return [
                {
                    "tool": "pip-audit",
                    "status": "completed",
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            ]
        except subprocess.TimeoutExpired:
            return [{"tool": "pip-audit", "status": "timeout"}]
        except Exception as exc:  # noqa: BLE001
            return [{"tool": "pip-audit", "status": "error", "reason": str(exc)}]


class ContainerSandbox:
    """容器沙箱：把命令放到 Docker 容器内执行，进一步隔离 Agent 生成的代码。"""

    @classmethod
    def is_available(cls) -> bool:
        try:
            result = subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return result.returncode == 0
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def build_command(
        command: str,
        workspace: Path,
        image: str = "python:3.11-slim",
        workdir: str = "/workspace",
    ) -> str:
        """把原始命令包装成 docker run 命令。"""
        quoted = shlex.quote(command)
        return (
            f'docker run --rm --network none '
            f'-v "{workspace.resolve()}:{workdir}" '
            f'-w {workdir} {image} bash -c {quoted}'
        )

    @classmethod
    def run(
        cls,
        command: str,
        workspace: Path,
        image: str = "python:3.11-slim",
        timeout: int = 30,
    ) -> Dict[str, Any]:
        docker_cmd = cls.build_command(command, workspace, image=image)
        try:
            result = subprocess.run(
                docker_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "command": docker_cmd,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"容器执行超过 {timeout} 秒"}
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc)}


class SecurityPipeline:
    """高阶安全流水线：Secret 扫描 + 依赖漏洞扫描 + 容器沙箱执行。"""

    def __init__(self, workspace: Path, requirements_path: Optional[Path] = None):
        self.workspace = Path(workspace)
        self.requirements_path = requirements_path

    def run(self, command: Optional[str] = None, use_container: bool = False) -> Dict[str, Any]:
        findings: List[Dict[str, Any]] = []
        findings.extend(SecretScanner.scan_workspace(self.workspace))

        dep_findings: List[Dict[str, Any]] = []
        if self.requirements_path:
            dep_findings = DependencyScanner.scan_requirements(self.requirements_path)

        result: Dict[str, Any] = {
            "secret_findings": findings,
            "dependency_findings": dep_findings,
            "command_result": None,
        }

        if command:
            if use_container:
                result["command_result"] = ContainerSandbox.run(command, self.workspace)
            else:
                from dev_agent_system.mcp import ToolSandbox

                result["command_result"] = ToolSandbox.run_command(command, base_dir=str(self.workspace))

        result["safe"] = not findings and (
            not dep_findings or all(f.get("status") == "skipped" for f in dep_findings)
        )
        return result
