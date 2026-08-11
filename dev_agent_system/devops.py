"""DevOps 真实闭环：构建 Docker 镜像、启动容器、健康检查、清理。"""
from __future__ import annotations

import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional


class DevOpsRunner:
    """为工作产物构建并验证 Docker 镜像。

    默认 `dry_run=True`，不会真正调用 docker，仅生成部署报告。
    设置 `DEVOPS_DRY_RUN=false` 并确保本机已安装 Docker 后，才会执行真实构建与运行。
    """

    def __init__(
        self,
        image_prefix: str = "dev-agent",
        timeout: int = 120,
        dry_run: bool = True,
    ):
        self.image_prefix = image_prefix
        self.timeout = timeout
        self.dry_run = dry_run

    def run(self, request_id: str, workspace: Path) -> Dict[str, Any]:
        """执行 build -> run -> health -> cleanup 闭环，返回部署报告。"""
        image = self._image_name(request_id)
        container = f"{self.image_prefix}-{request_id}"
        report: Dict[str, Any] = {
            "image": image,
            "container": container,
            "dry_run": self.dry_run,
            "build": self._build(workspace, image),
            "run": None,
            "health": None,
            "cleanup": None,
        }

        if not report["build"]["success"]:
            report["deployed"] = False
            return report

        report["run"] = self._run_container(image, container)
        if report["run"]["success"]:
            report["health"] = self._health_check(container)
        report["cleanup"] = self._cleanup(container)

        report["deployed"] = (
            report["build"]["success"]
            and report["run"]["success"]
            and (report["health"] or {}).get("success", False)
        )
        return report

    def _image_name(self, request_id: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9.-]", "-", request_id).lower().strip("-")
        return f"{self.image_prefix}:{safe}"

    def _build(self, workspace: Path, image: str) -> Dict[str, Any]:
        if not (workspace / "Dockerfile").exists():
            return {
                "success": False,
                "error": "workspace 中缺少 Dockerfile，无法构建镜像",
            }
        return self._exec(["docker", "build", "-t", image, "."], cwd=workspace)

    def _run_container(self, image: str, container: str) -> Dict[str, Any]:
        return self._exec(
            ["docker", "run", "-d", "--name", container, image],
        )

    def _health_check(self, container: str, max_wait: int = 30) -> Dict[str, Any]:
        if self.dry_run:
            return {"success": True, "dry_run": True, "note": "dry-run 健康检查跳过"}
        # 先确认容器仍在运行
        ps = self._exec(["docker", "ps", "-q", "-f", f"name=^{container}$"])
        if not ps["success"] or not ps["stdout"].strip():
            return {"success": False, "error": "容器未在运行"}

        # 尝试获取 8000 端口映射
        port_res = self._exec(["docker", "port", container, "8000/tcp"])
        if port_res["success"] and port_res["stdout"].strip():
            lines = [line.strip() for line in port_res["stdout"].strip().splitlines() if line.strip()]
            if lines:
                m = re.search(r":(\d+)$", lines[0])
                if m:
                    return self._http_health(m.group(1), max_wait=max_wait)

        # 无 8000 端口映射时，认为容器处于运行状态即通过基础检查
        return {"success": True, "note": "容器运行中，无 8000 端口映射"}

    def _http_health(self, host_port: str, max_wait: int = 30) -> Dict[str, Any]:
        url = f"http://localhost:{host_port}/health"
        for _ in range(max_wait):
            try:
                with urllib.request.urlopen(url, timeout=2) as resp:
                    if resp.status == 200:
                        return {"success": True, "url": url}
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                pass
            time.sleep(1)
        return {"success": False, "error": f"健康检查超时：{url}"}

    def _cleanup(self, container: str) -> Dict[str, Any]:
        stop = self._exec(["docker", "stop", container], timeout=10)
        rm = self._exec(["docker", "rm", container], timeout=10)
        return {"success": stop["success"] and rm["success"], "stop": stop, "rm": rm}

    def _exec(
        self,
        cmd: List[str],
        cwd: Optional[Path] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        if self.dry_run:
            return {
                "success": True,
                "dry_run": True,
                "cmd": " ".join(cmd),
                "stdout": "",
                "stderr": "",
            }
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout or self.timeout,
                check=False,
            )
            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"命令执行超时：{' '.join(cmd)}"}
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc)}
