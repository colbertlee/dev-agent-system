"""
软件开发多 Agent 协作系统 —— 框架一最小可运行骨架
=====================================================
设计依据：
- 6 个核心角色：Architect / Coder / Tester / Reviewer / Docs / DevOps
- 编排：DAG（Architect → {Coder, Tester, Docs} 并行 → Reviewer）
- 通信：A2A Agent Card（/.well-known/agent.json）
- 工具：MCP 风格工具注册 + 安全沙箱
运行方式：
    python multi_agent_dev.py "做一个支持 JWT 的用户登录模块"
环境：
    可选配置 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL；未配置时返回 MOCK 输出。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class LLMClient:
    """轻量级 LLM 调用客户端，兼容 OpenAI 风格接口。"""

    def __init__(self, model: Optional[str] = None):
        self.model = model or os.getenv("LLM_MODEL", "deepseek-chat")
        self._client = None
        self._init_openai()

    def _init_openai(self) -> None:
        try:
            from openai import OpenAI
        except ImportError:
            return
        api_key = os.getenv("LLM_API_KEY")
        base_url = os.getenv("LLM_BASE_URL")
        if api_key:
            self._client = OpenAI(api_key=api_key, base_url=base_url)

    def chat(self, system: str, user: str) -> str:
        if self._client is None:
            return (
                f"[MOCK] {self.model} 未调用（缺少 LLM_API_KEY 或 openai 包未安装）。\n"
                f"系统提示摘要：{system[:60]}...\n输入摘要：{user[:120]}..."
            )
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return resp.choices[0].message.content or ""
        except Exception as e:  # noqa: BLE001
            return f"[LLM ERROR] {e}"


class BaseAgent:
    """所有业务 Agent 的抽象基类。"""

    def __init__(self, name: str, role: str, system_prompt: str, model: Optional[str] = None):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.llm = LLMClient(model=model)

    async def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        prompt = self._build_prompt(state)
        output = await asyncio.to_thread(self.llm.chat, self.system_prompt, prompt)
        return {"agent": self.name, "role": self.role, "output": output}

    def _build_prompt(self, state: Dict[str, Any]) -> str:
        return str(state.get("input", ""))

    def agent_card(self, url: str, skills: List[str]) -> Dict[str, Any]:
        """A2A 风格的 Agent Card（用于服务发现）。"""
        return {
            "name": f"{self.name} Agent",
            "url": url,
            "skills": [{"name": s} for s in skills],
            "capabilities": {"streaming": False, "autonomy": "L2"},
        }


class ArchitectAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            "Architect",
            "系统架构师",
            "你是 Architect Agent，负责把用户需求转化为系统架构设计。输出应包含：1) 关键模块；2) API 契约；3) 技术选型及原因。",
        )

    def _build_prompt(self, state: Dict[str, Any]) -> str:
        return f"用户需求：{state.get('input', '')}\n请给出结构化的架构设计。"


class CoderAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            "Coder",
            "代码实现引擎",
            "你是 Coder Agent，根据架构设计生成可运行代码。优先使用 Python，输出到代码块。",
        )

    def _build_prompt(self, state: Dict[str, Any]) -> str:
        return f"架构设计：{state.get('architect', {}).get('output', '')}\n请生成对应实现代码。"


class TesterAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            "Tester",
            "测试生成",
            "你是 Tester Agent，为生成的代码编写 pytest 单元测试，覆盖正常和异常路径。",
        )

    def _build_prompt(self, state: Dict[str, Any]) -> str:
        return f"代码：{state.get('coder', {}).get('output', '')}\n请生成 pytest 测试用例。"


class DocsAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            "Docs",
            "文档生成",
            "你是 Docs Agent，根据架构和代码生成 API 文档与 README 摘要。",
        )

    def _build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"架构：{state.get('architect', {}).get('output', '')[:800]}\n"
            f"代码：{state.get('coder', {}).get('output', '')[:800]}\n"
            "请生成中文 README 和 API 文档摘要。"
        )


class ReviewerAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            "Reviewer",
            "代码审查",
            "你是 Reviewer Agent，从需求出发独立审查代码、测试和文档，指出潜在 bug、安全和规范问题。",
        )

    def _build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"原始需求：{state.get('input', '')}\n"
            f"代码：{state.get('coder', {}).get('output', '')[:1200]}\n"
            f"测试：{state.get('tester', {}).get('output', '')[:800]}\n"
            f"文档：{state.get('docs', {}).get('output', '')[:800]}\n"
            "请输出审查意见及修改建议。"
        )


class DevOpsAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            "DevOps",
            "部署运维",
            "你是 DevOps Agent，生成 Dockerfile、CI/CD 与部署脚本。",
        )

    def _build_prompt(self, state: Dict[str, Any]) -> str:
        return f"代码：{state.get('coder', {}).get('output', '')[:1000]}\n请生成 Dockerfile 和 CI 配置。"


class ToolSandbox:
    """MCP 风格工具沙箱：只允许白名单命令，禁止危险操作。"""

    BLACKLIST = re.compile(r"(rm\s+-rf|>\s*/dev/null|&&\s*rm|curl\s+\||wget\s+-O-)", re.I)
    ALLOWED_PREFIXES = ("python", "pytest", "git", "ls", "cat", "echo")

    @staticmethod
    def run_command(command: str, timeout: int = 5) -> Dict[str, Any]:
        if ToolSandbox.BLACKLIST.search(command):
            return {"success": False, "error": "命令命中黑名单，已被拦截"}
        if not command.startswith(ToolSandbox.ALLOWED_PREFIXES):
            return {"success": False, "error": f"只允许以 {ToolSandbox.ALLOWED_PREFIXES} 开头的命令"}
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=Path.cwd(),
            )
            return {"success": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "error": str(e)}

    @staticmethod
    def write_file(relative_path: str, content: str, base_dir: str = "output") -> Dict[str, Any]:
        target = Path(base_dir) / relative_path
        target.resolve().relative_to(Path(base_dir).resolve())  # 防止目录穿越
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"success": True, "path": str(target)}

    @staticmethod
    def read_file(relative_path: str, base_dir: str = "output") -> Dict[str, Any]:
        target = Path(base_dir) / relative_path
        target.resolve().relative_to(Path(base_dir).resolve())
        if not target.exists():
            return {"success": False, "error": "文件不存在"}
        return {"success": True, "content": target.read_text(encoding="utf-8")}


class Orchestrator:
    """DAG 编排器：Architect → {Coder, Tester, Docs} 并行 → Reviewer。"""

    def __init__(self):
        self.agents: Dict[str, BaseAgent] = {
            "architect": ArchitectAgent(),
            "coder": CoderAgent(),
            "tester": TesterAgent(),
            "docs": DocsAgent(),
            "reviewer": ReviewerAgent(),
            "devops": DevOpsAgent(),
        }
        self.sandbox = ToolSandbox()

    async def run(self, requirement: str, devops: bool = False) -> Dict[str, Any]:
        state: Dict[str, Any] = {
            "input": requirement,
            "started_at": datetime.now().isoformat(),
        }

        # 1. Architect 串行
        state["architect"] = await self.agents["architect"].run(state)

        # 2. Coder / Tester / Docs 并行
        coder_task = self.agents["coder"].run(state)
        tester_task = self.agents["tester"].run(state)
        docs_task = self.agents["docs"].run(state)
        coder, tester, docs = await asyncio.gather(coder_task, tester_task, docs_task)
        state["coder"] = coder
        state["tester"] = tester
        state["docs"] = docs

        # 3. Reviewer 聚合审查
        state["reviewer"] = await self.agents["reviewer"].run(state)

        # 4. DevOps 可选
        if devops:
            state["devops"] = await self.agents["devops"].run(state)

        state["finished_at"] = datetime.now().isoformat()
        return state

    def agent_cards(self) -> Dict[str, Any]:
        return {
            name: agent.agent_card(url=f"http://localhost:8000/{name}", skills=[agent.role])
            for name, agent in self.agents.items()
        }


async def main():
    parser = argparse.ArgumentParser(description="软件开发多 Agent 协作系统（框架一实现）")
    parser.add_argument(
        "requirement",
        nargs="?",
        default="开发一个用户登录模块：支持注册、登录、JWT 校验。",
        help="输入需求描述",
    )
    parser.add_argument("--devops", action="store_true", help="同时运行 DevOps Agent")
    args = parser.parse_args()

    orchestrator = Orchestrator()
    result = await orchestrator.run(args.requirement, devops=args.devops)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
