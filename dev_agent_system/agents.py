"""6 个业务 Agent + Memory Agent 的实现。

每个 Agent 现在都会把产物写入以 request_id 隔离的 workspace，并返回结构化结果。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from dev_agent_system.config import Settings
from dev_agent_system.llm import LLMClient
from dev_agent_system.memory import MemoryAgent
from dev_agent_system.mcp import MCPToolRegistry, ToolSandbox
from dev_agent_system.router import ModelRouter
from dev_agent_system.security import SafetyScanner, SecretRedactor
from dev_agent_system.telemetry import DEFAULT as DEFAULT_TELEMETRY, Telemetry
from dev_agent_system.schemas import AgentCard, AgentSkill


class BaseAgent:
    """所有业务 Agent 的基类。"""

    def __init__(
        self,
        name: str,
        role: str,
        system_prompt: str,
        model: Optional[str] = None,
        skills: Optional[List[str]] = None,
        telemetry: Optional[Telemetry] = None,
    ):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.model = model or Settings.agent_model(name.lower())
        self.skills = skills or [role]
        self.router = ModelRouter()
        self.llm = LLMClient(model=self.model)
        self.memory = MemoryAgent()
        self.tools = MCPToolRegistry()
        self.telemetry = telemetry or DEFAULT_TELEMETRY

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return str(state.get("input", ""))

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """子类重写：解析输出、调用 MCP 工具、写入产物。"""
        return {"raw": output}

    @staticmethod
    def _workspace(state: Dict[str, Any]) -> Path:
        """当前请求的工作目录。"""
        if state.get("workspace"):
            return Path(state["workspace"])
        request_id = state.get("request_id", "default")
        return ToolSandbox.WORK_DIR / str(request_id)

    async def _write_file(self, path: str, content: str, workspace: Path) -> Dict[str, Any]:
        return await self.tools.ainvoke("write_file", path=path, content=content, base_dir=str(workspace))

    async def _read_file(self, path: str, workspace: Path) -> Dict[str, Any]:
        return await self.tools.ainvoke("read_file", path=path, base_dir=str(workspace))

    async def _run_command(self, command: str, workspace: Path, timeout: int = 10) -> Dict[str, Any]:
        return await self.tools.ainvoke("run_command", command=command, timeout=timeout, base_dir=str(workspace))

    @staticmethod
    def _extract_json(text: str) -> Optional[Dict[str, Any]]:
        """从文本中提取第一个 JSON 对象或数组。"""
        match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _extract_code_blocks(text: str) -> List[Dict[str, str]]:
        """提取 ``` 代码块，支持前接 '# file: path' 等头部。"""
        blocks: List[Dict[str, str]] = []
        pattern = r"(?:^|\n)(?:[^\n`]*?(?:file|path|filename)[:\s]+([^\n]+))?\n?```(?:\w+)?\n(.*?)```"
        for m in re.finditer(pattern, text, re.DOTALL | re.I):
            path = (m.group(1) or "").strip().strip("`").strip()
            code = m.group(2)
            blocks.append({"path": path, "code": code})
        return blocks

    async def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        session = state.get("request_id", "default")
        workspace = self._workspace(state)
        workspace.mkdir(parents=True, exist_ok=True)
        state["workspace"] = str(workspace)

        memories = self.memory.recall(state.get("input", ""), session_id=session, layer="working", top_k=3)
        memory_text = "\n".join(str(m["value"]) for m in memories)
        prompt = self.build_prompt(state)
        full_prompt = f"相关记忆：\n{memory_text}\n\n{prompt}" if memory_text else prompt

        # 上下文压缩：超过阈值后保留头部和尾部
        if len(full_prompt) > Settings.context_compress_threshold():
            full_prompt = self.memory.compress_context(
                full_prompt, max_chars=Settings.context_window_limit()
            )

        # 敏感信息脱敏：进入 LLM 前与离开 LLM 后都进行 redaction
        full_prompt = SecretRedactor.redact(full_prompt)
        resolved_model, kwargs = self.router.resolve(self.name, full_prompt)

        with self.telemetry.span(
            f"agent.{self.name}.llm",
            {"agent": self.name, "model": resolved_model, "request_id": session},
        ):
            output = self.llm.chat(self.system_prompt, full_prompt, model=resolved_model, **kwargs)

        output = SecretRedactor.redact(output)
        self.memory.remember("last_output", output, session_id=session, layer="short", ttl=3600)

        # 近似 token 数与延迟统计
        self.telemetry.collector.counter(
            "llm_calls_total",
            "Total number of LLM calls",
            labelnames=["agent", "model"],
        ).inc(agent=self.name, model=resolved_model)
        self.telemetry.collector.histogram(
            "llm_prompt_tokens_approx",
            "Approximate prompt tokens",
            labelnames=["agent", "model"],
        ).observe(len(full_prompt) / 4, agent=self.name, model=resolved_model)
        self.telemetry.collector.histogram(
            "llm_output_tokens_approx",
            "Approximate output tokens",
            labelnames=["agent", "model"],
        ).observe(len(output) / 4, agent=self.name, model=resolved_model)

        result: Dict[str, Any] = {
            "agent": self.name,
            "role": self.role,
            "output": output,
            "workspace": str(workspace),
            "model": resolved_model,
            "llm_kwargs": kwargs,
        }
        extra = await self.postprocess(output, state)
        result.update(extra)
        return result

    def agent_card(self, url: str) -> AgentCard:
        return AgentCard(
            name=f"{self.name} Agent",
            url=url,
            skills=[AgentSkill(name=s) for s in self.skills],
            capabilities={"streaming": False, "autonomy": "L2", "modalities": ["text", "code"]},
        )


class ArchitectAgent(BaseAgent):
    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Architect",
            "系统架构师",
            _load_prompt("architect"),
            model=model,
            skills=["system-design", "api-contract", "tech-stack"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        prd = (state.get("product_manager") or {}).get("output", "")
        return (
            f"用户需求：{state.get('input', '')}\n"
            f"PRD：{prd[:1500] if prd else '无'}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            "请输出 JSON 格式架构设计：{modules, api_contract, tech_stack, mermaid, notes}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        design = self._extract_json(output)
        if design:
            await self._write_file("design.json", json.dumps(design, ensure_ascii=False, indent=2), workspace)
        return {"design_file": "design.json" if design else None, "parsed": design}


class CoderAgent(BaseAgent):
    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Coder",
            "代码实现引擎",
            _load_prompt("coder"),
            model=model,
            skills=["code-implementation", "refactor", "python"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        dba_output = (state.get("dba") or {}).get("output", "")
        return (
            f"用户需求：{state.get('input', '')}\n"
            f"架构设计：{(state.get('architect') or {}).get('output', '')[:2000]}\n"
            f"数据库设计：{dba_output[:1500] if dba_output else '无'}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            "请生成可运行代码。每个代码块前用注释标明文件路径，例如 '# file: main.py'。\n"
            "最后输出 JSON 状态报告：{status, files_modified, test_result, note}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        blocks = self._extract_code_blocks(output)
        files: List[str] = []
        security_issues: List[Dict[str, Any]] = []
        for idx, block in enumerate(blocks, start=1):
            path = block["path"]
            if not path:
                path = f"module_{idx}.py"
            if not path.endswith(".py"):
                path += ".py"
            issues = SafetyScanner.scan_code(block["code"])
            security_issues.extend(issues)
            res = await self._write_file(path, block["code"], workspace)
            if res.get("success"):
                files.append(path)

        report = self._extract_json(output) or {}

        # MOCK 降级：没有真实 LLM 时写一段占位代码，方便 CLI/测试继续跑
        if not files and self.llm._client is None:
            stub = self._fallback_code(state.get("input", ""))
            res = await self._write_file("main.py", stub, workspace)
            if res.get("success"):
                files.append("main.py")
            report = {
                "status": "mock_fallback",
                "files_modified": files,
                "test_result": "unknown",
                "note": "MOCK 模式生成的占位代码",
            }

        return {
            "files": files,
            "status": report.get("status", "completed" if files else "needs_help"),
            "test_result": report.get("test_result", "unknown"),
            "note": report.get("note", ""),
            "security_issues": security_issues,
        }

    @staticmethod
    def _fallback_code(requirement: str) -> str:
        safe = re.sub(r"[^\w\u4e00-\u9fff]+", "_", requirement)[:30].strip("_") or "agent"
        return f'"""Generated from requirement: {requirement}"""\n\ndef main():\n    print("Hello from {safe}")\n\nif __name__ == "__main__":\n    main()\n'


class TesterAgent(BaseAgent):
    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Tester",
            "测试工程师",
            _load_prompt("tester"),
            model=model,
            skills=["test-generation", "pytest", "coverage"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        workspace = state.get("workspace", "")
        code_files = (state.get("coder") or {}).get("files", [])
        code_snippets: List[str] = []
        for f in code_files[:3]:
            res = ToolSandbox.read_file(f, base_dir=workspace)  # 同步读取即可
            if res.get("success"):
                code_snippets.append(f"--- {f} ---\n{res['content'][:1500]}")
        return (
            f"代码文件：{code_files}\n"
            f"{''.join(code_snippets)[:2500]}\n"
            f"工作目录：{workspace}\n"
            "请生成 pytest 测试用例。每个测试代码块前标明文件路径，如 '# file: test_main.py'。\n"
            "最后输出 JSON 测试报告：{passed, failed, coverage, report}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        blocks = self._extract_code_blocks(output)
        files: List[str] = []
        for idx, block in enumerate(blocks, start=1):
            path = block["path"]
            if not path:
                path = f"test_module_{idx}.py"
            if not path.startswith("test_"):
                path = "test_" + path
            res = await self._write_file(path, block["code"], workspace)
            if res.get("success"):
                files.append(path)

        if files:
            pytest_res = await self._run_command("pytest -q", workspace, timeout=15)
        else:
            pytest_res = {"success": False, "stdout": "", "stderr": "no tests generated"}

        report = self._extract_json(output) or {}
        passed = report.get("passed")
        failed = report.get("failed")
        if passed is None or failed is None:
            passed, failed = self._parse_pytest_summary(pytest_res.get("stdout", ""))

        return {
            "files": files,
            "passed": passed,
            "failed": failed,
            "coverage": report.get("coverage", 0.0),
            "report": (pytest_res.get("stdout", "") + "\n" + pytest_res.get("stderr", "")).strip(),
            "test_command_success": pytest_res.get("success", False),
        }

    @staticmethod
    def _parse_pytest_summary(stdout: str):
        m = re.search(r"(\d+)\s+passed", stdout)
        passed = int(m.group(1)) if m else 0
        m = re.search(r"(\d+)\s+failed", stdout)
        failed = int(m.group(1)) if m else 0
        return passed, failed


class ReviewerAgent(BaseAgent):
    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Reviewer",
            "代码审查",
            _load_prompt("reviewer"),
            model=model,
            skills=["code-review", "security", "performance"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"原始需求：{state.get('input', '')}\n"
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            f"测试报告：{(state.get('tester') or {}).get('report', '')[:1200]}\n"
            f"文档文件：{(state.get('docs') or {}).get('files', [])}\n"
            "请独立思考，从需求出发审查。输出 JSON：{severity, passed, issues, suggestions}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        report = self._extract_json(output)
        if not report:
            # 无法解析 JSON 时做最保守判断
            report = {
                "severity": "medium",
                "passed": False,
                "issues": ["Reviewer 输出无法解析为 JSON"],
                "suggestions": ["请检查 LLM 输出格式"],
            }
        review_file = "review_report.json"
        await self._write_file(review_file, json.dumps(report, ensure_ascii=False, indent=2), workspace)
        report["report_file"] = review_file
        return report


class DocsAgent(BaseAgent):
    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Docs",
            "文档工程师",
            _load_prompt("docs"),
            model=model,
            skills=["documentation", "readme", "api-doc"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"架构：{str((state.get('architect') or {}).get('output', ''))[:800]}\n"
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            "请生成 README.md 与 API.md。用代码块标明文件路径，如 '# file: README.md'。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        blocks = self._extract_code_blocks(output)
        files: List[str] = []
        for block in blocks:
            path = block["path"] or "README.md"
            if not path.endswith(".md"):
                path += ".md"
            res = await self._write_file(f"docs/{path}", block["code"], workspace)
            if res.get("success"):
                files.append(f"docs/{path}")
        if not files:
            await self._write_file("docs/README.md", output, workspace)
            files.append("docs/README.md")
        return {"files": files}


class DevOpsAgent(BaseAgent):
    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "DevOps",
            "部署运维",
            _load_prompt("devops"),
            model=model,
            skills=["docker", "ci-cd", "deployment"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            "请生成 Dockerfile、docker-compose.yml 与 CI/CD 配置摘要，并说明部署前需人工确认。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        blocks = self._extract_code_blocks(output)
        files: List[str] = []
        for block in blocks:
            path = block["path"]
            if not path:
                continue
            res = await self._write_file(path, block["code"], workspace)
            if res.get("success"):
                files.append(path)
        if not files:
            await self._write_file("deploy_summary.md", output, workspace)
            files.append("deploy_summary.md")
        return {"files": files, "needs_approval": True}


class ProductManagerAgent(BaseAgent):
    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "ProductManager",
            "产品经理",
            _load_prompt("product_manager"),
            model=model,
            skills=["requirement-analysis", "prd", "user-stories"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"用户需求：{state.get('input', '')}\n"
            "请把需求拆分为 PRD、用户故事和验收标准。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        report = self._extract_json(output) or {}
        prd_file = "prd.md"
        await self._write_file(prd_file, output, workspace)
        return {
            "prd_file": prd_file,
            "user_stories": report.get("user_stories", []),
            "acceptance_criteria": report.get("acceptance_criteria", []),
            "parsed": report,
        }


class SecurityAgent(BaseAgent):
    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Security",
            "安全审查",
            _load_prompt("security"),
            model=model,
            skills=["security-review", "vulnerability", "compliance"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"原始需求：{state.get('input', '')}\n"
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            f"测试文件：{(state.get('tester') or {}).get('files', [])}\n"
            f"架构设计：{(state.get('architect') or {}).get('output', '')[:1500]}\n"
            "请独立进行安全审查，输出 JSON {severity, passed, issues, suggestions}。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        report = self._extract_json(output)
        if not report:
            report = {
                "severity": "medium",
                "passed": False,
                "issues": ["Security Agent 输出无法解析为 JSON"],
                "suggestions": ["请检查 LLM 输出格式"],
            }
        report_file = "security_report.json"
        await self._write_file(report_file, json.dumps(report, ensure_ascii=False, indent=2), workspace)
        report["report_file"] = report_file
        return report


class DBAAgent(BaseAgent):
    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "DBA",
            "数据库架构",
            _load_prompt("dba"),
            model=model,
            skills=["database-design", "schema", "migration"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"原始需求：{state.get('input', '')}\n"
            f"架构设计：{(state.get('architect') or {}).get('output', '')[:2000]}\n"
            "请输出数据库 Schema 与迁移 SQL。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        blocks = self._extract_code_blocks(output)
        files: List[str] = []
        for block in blocks:
            path = block["path"]
            if not path:
                continue
            if not path.endswith(".sql"):
                path += ".sql"
            res = await self._write_file(path, block["code"], workspace)
            if res.get("success"):
                files.append(path)

        report = self._extract_json(output) or {}
        if not files:
            await self._write_file("schema.sql", output, workspace)
            files.append("schema.sql")

        return {
            "files": files,
            "tables": report.get("tables", []),
            "notes": report.get("notes", ""),
        }


class MemoryAgentFacade:
    """对外的 Memory Agent 接口，供 Orchestrator 调用。"""

    def __init__(self, base_dir: str = "memory_store"):
        self._impl = MemoryAgent(base_dir=base_dir)

    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        session = state.get("request_id", "default")
        query = state.get("input", "")
        memories = self._impl.recall(query, session_id=session, layer="working", top_k=5)
        summary = self._impl.summarize(state.get("history", []))
        return {"agent": "Memory", "role": "记忆", "memories": memories, "summary": summary}


def _load_prompt(agent_name: str) -> str:
    """从 prompts.yaml 加载 System Prompt；失败时返回内置提示。"""
    prompt_file = Path(__file__).with_name("prompts.yaml")
    try:
        with open(prompt_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get(agent_name, _FALLBACK_PROMPTS.get(agent_name, f"你是 {agent_name} Agent。"))
    except Exception:  # noqa: BLE001
        return _FALLBACK_PROMPTS.get(agent_name, f"你是 {agent_name} Agent。")


_FALLBACK_PROMPTS: Dict[str, str] = {
    "architect": "你是 Architect Agent，负责架构设计。禁止写实现代码。",
    "coder": "你是 Coder Agent，负责生成可运行代码。",
    "tester": "你是 Tester Agent，负责生成并执行测试。",
    "reviewer": "你是 Reviewer Agent，必须独立思考，不信任上游。",
    "docs": "你是 Docs Agent，负责同步文档。",
    "devops": "你是 DevOps Agent，负责 CI/CD 与部署。",
    "product_manager": "你是 Product Manager Agent，负责需求分析与 PRD。",
    "security": "你是 Security Agent，负责独立安全审查。",
    "dba": "你是 DBA Agent，负责数据库 Schema 与迁移。",
}
