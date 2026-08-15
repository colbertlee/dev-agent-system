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
from typing import Any, Dict, List, Optional, Type

import yaml
from pydantic import BaseModel, ValidationError

from dev_agent_system.config import Settings
from dev_agent_system.llm import LLMClient
from dev_agent_system.memory import MemoryAgent
from dev_agent_system.mcp import MCPToolRegistry, ToolSandbox
from dev_agent_system.router import ModelRouter
from dev_agent_system.security import SafetyScanner, SecretRedactor
from dev_agent_system.telemetry import DEFAULT as DEFAULT_TELEMETRY, Telemetry
from dev_agent_system.templates import get_language, TEMPLATES
from dev_agent_system.skills import SkillManager
from dev_agent_system.schemas import (
    AgentCard,
    AgentFile,
    AgentOutput,
    AgentSkill,
    CoderReport,
    DesignOutput,
    DBAReport,
    PRDOutput,
    ReviewReport,
    TestReport,
)


class BaseAgent:
    """所有业务 Agent 的基类。"""

    json_output: bool = False
    report_schema: Optional[Type[BaseModel]] = None
    summary_budget: int = 1500
    max_repair_attempts: int = 1  # JSON/Pydantic 校验失败时自动修复的最大次数

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

        # 自动发现并注册已安装的 Skill 到 MCP 工具箱
        self._register_skills()

    def _register_skills(self) -> None:
        if not Settings.skills_enabled():
            return
        try:
            SkillManager().register_to_mcp(self.tools)
        except Exception:  # noqa: BLE001
            pass

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

    @staticmethod
    def _find_first_json_object(text: str) -> Optional[Any]:
        """从文本中定位第一个非空的 JSON 对象/数组。

        优先匹配 ```json ... ``` 代码块，再扫描内嵌的 JSON。
        """
        # 1) 显式 JSON 代码块
        for m in re.finditer(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL | re.I):
            block = m.group(1).strip()
            if not block:
                continue
            try:
                data = json.loads(block)
                if isinstance(data, (dict, list)) and data:
                    return data
            except json.JSONDecodeError:
                continue

        # 2) 用 JSONDecoder 扫描 { } / [ ]，跳过空的 {} / []
        decoder = json.JSONDecoder()
        idx = 0
        n = len(text)
        while idx < n:
            # 定位到下一个 { 或 [
            while idx < n and text[idx] not in "{[":
                idx += 1
            if idx >= n:
                return None
            try:
                data, end = decoder.raw_decode(text, idx)
                if isinstance(data, dict) and data:
                    return data
                if isinstance(data, list) and data:
                    return data
                idx += max(end, 1)
            except (json.JSONDecodeError, ValueError):
                idx += 1
        return None

    @staticmethod
    def _truncate_for_summary(
        value: Any,
        max_str: int = 400,
        max_list: int = 10,
        max_depth: int = 4,
        current_depth: int = 0,
    ) -> Any:
        """递归截断 dict/list/str，用于生成下游 Agent 可读的 summary。"""
        if current_depth > max_depth:
            return "..."
        if isinstance(value, str):
            if len(value) > max_str:
                return value[:max_str] + "... [truncated]"
            return value
        if isinstance(value, (list, tuple)):
            truncated = [BaseAgent._truncate_for_summary(v, max_str, max_list, max_depth, current_depth + 1) for v in value[:max_list]]
            if len(value) > max_list:
                truncated.append("...")
            return truncated
        if isinstance(value, dict):
            return {
                k: BaseAgent._truncate_for_summary(v, max_str, max_list, max_depth, current_depth + 1)
                for k, v in value.items()
            }
        return value

    def _summarize_result(self, result: Dict[str, Any]) -> str:
        """把 Agent 运行结果压缩成下游可传递的关键信息字符串。

        - 丢弃原始 LLM 输出（已解析到产物/文件和 report）
        - 递归截断长字符串/列表，避免 state 和 checkpoint 膨胀
        - 保证返回合法 JSON，便于下游直接解析
        """
        # 不向下游传递的元数据键
        excluded = {"output", "workspace", "model", "llm_kwargs", "agent", "role", "raw"}
        raw = {k: v for k, v in result.items() if k not in excluded and not k.startswith("_")}

        # 自适应截断：在保证合法 JSON 的前提下把 summary 压到 budget 内
        max_str, max_list = 400, 10
        while True:
            data = self._truncate_for_summary(raw, max_str=max_str, max_list=max_list)
            text = json.dumps(data, ensure_ascii=False, default=str)
            if len(text) <= self.summary_budget or max_str <= 50:
                break
            max_str = max(50, max_str // 2)
            max_list = max(3, max_list - 2)

        return text

    def _with_json_schema_prompt(self, prompt: str) -> str:
        """在 prompt 末尾追加 report_schema 对应的 JSON Schema，强化输出约束。"""
        if self.report_schema is None:
            return prompt + "\n\n你必须输出且仅输出一个合法 JSON 对象，不要包含解释文字。"
        try:
            schema = self.report_schema.model_json_schema()
        except Exception:  # noqa: BLE001
            return prompt + "\n\n你必须输出且仅输出一个合法 JSON 对象，不要包含解释文字。"
        return (
            prompt
            + "\n\n你必须输出且仅输出一个严格符合以下 JSON Schema 的单一 JSON 对象，"
            "不要包含任何解释文字或 Markdown 代码块包装：\n\n"
            f"```json\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n```"
        )

    @staticmethod
    def _parse_raw_json(text: Any) -> Optional[Any]:
        """从任意输入中提取 dict/list，不校验 schema（兼容旧版实现）。"""
        if text is None:
            return None
        if isinstance(text, (dict, list)):
            return text
        cleaned = str(text).strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`").strip()
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return BaseAgent._find_first_json_object(cleaned)

    async def _parse_json_output(
        self,
        text: Any,
        schema: Optional[Type[BaseModel]] = None,
    ) -> Optional[Dict[str, Any]]:
        """解析并可选做 Pydantic 校验；失败时尝试自我修复（最多 max_repair_attempts 次）。"""
        raw = text
        schema = schema or self.report_schema
        last_error = ""
        for attempt in range(self.max_repair_attempts + 1):
            data = BaseAgent._parse_raw_json(raw)
            if not isinstance(data, dict):
                if attempt == self.max_repair_attempts or not self.json_output:
                    return None
                last_error = "无法从文本中提取 JSON 对象"
                raw = await self.llm.achat(
                    self.system_prompt,
                    self._build_repair_prompt(str(text), last_error, schema),
                    json_mode=True,
                )
                continue
            if schema is None:
                return data
            try:
                return schema.model_validate(data).model_dump()
            except ValidationError as exc:
                if attempt == self.max_repair_attempts:
                    # 最后一次仍失败：如果 extra="ignore" 则返回原 dict；否则 None
                    return data
                last_error = str(exc)
                raw = await self.llm.achat(
                    self.system_prompt,
                    self._build_repair_prompt(str(text), last_error, schema),
                    json_mode=True,
                )
        return None

    def _build_repair_prompt(self, raw_output: str, error_message: str, schema: Optional[Type[BaseModel]]) -> str:
        schema_prompt = ""
        if schema is not None:
            try:
                schema_json = schema.model_json_schema()
                schema_prompt = f"\n必须严格符合的 JSON Schema：\n```json\n{json.dumps(schema_json, ensure_ascii=False, indent=2)}\n```\n"
            except Exception:  # noqa: BLE001
                pass
        return (
            "你之前生成的 JSON 输出无法通过校验，请重新生成。\n\n"
            f"原始输出：\n{raw_output}\n\n"
            f"错误信息：\n{error_message}\n"
            f"{schema_prompt}\n"
            "请只输出修复后的合法 JSON，不要解释。"
        )

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

        # 如果启用 json_mode 且绑定了 report_schema，把 JSON Schema 注入 prompt 强化约束
        if self.json_output:
            full_prompt = self._with_json_schema_prompt(full_prompt)

        resolved_model, kwargs = self.router.resolve(self.name, full_prompt)

        with self.telemetry.span(
            f"agent.{self.name}.llm",
            {"agent": self.name, "model": resolved_model, "request_id": session},
        ):
            output = await self.llm.achat(
                self.system_prompt,
                full_prompt,
                model=resolved_model,
                json_mode=self.json_output,
                **kwargs,
            )

        output = SecretRedactor.redact(output)

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

        # 生成关键信息摘要，替换原始 output，避免无效数据在 Agent 间传递
        result["output"] = self._summarize_result(result)
        # llm_kwargs 等内部元数据无需进入 LangGraph state
        result.pop("llm_kwargs", None)
        # 记忆层也存摘要，避免后续 recall 把原始大段输出塞进 prompt
        self.memory.remember("last_output", result["output"], session_id=session, layer="short", ttl=3600)

        return result

    def agent_card(self, url: str) -> AgentCard:
        return AgentCard(
            name=f"{self.name} Agent",
            url=url,
            skills=[AgentSkill(name=s) for s in self.skills],
            capabilities={"streaming": False, "autonomy": "L2", "modalities": ["text", "code"]},
        )


class ArchitectAgent(BaseAgent):
    json_output = True
    report_schema = DesignOutput
    summary_budget = 2000

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
        template = get_language(state)
        return (
            f"目标语言/技术栈：{template.display}\n"
            f"用户需求：{state.get('input', '')}\n"
            f"PRD：{prd[:1500] if prd else '无'}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            "请输出 JSON 格式架构设计：{modules, api_contract, tech_stack, mermaid, notes}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        design = await self._parse_json_output(output, self.report_schema)
        if design:
            await self._write_file("design.json", json.dumps(design, ensure_ascii=False, indent=2), workspace)
        return {"design_file": "design.json" if design else None, "parsed": design}


class CoderAgent(BaseAgent):
    json_output = True
    report_schema = CoderReport
    summary_budget = 1500

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
        template = get_language(state)
        json_example = (
            '{"files": [{"path": "main.%s", "code": "..."}], '
            '"report": {"status": "completed", "files_modified": [...], '
            '"test_result": "passed", "note": ""}}'
        ) % template.file_ext
        return (
            f"目标语言/技术栈：{template.display}\n"
            f"构建命令：{template.build_cmd or '无'}\n"
            f"测试命令：{template.test_cmd}\n"
            f"用户生成文件扩展名：.{template.file_ext}，测试文件扩展名：.{template.test_ext}\n"
            f"用户需求：{state.get('input', '')}\n"
            f"架构设计：{(state.get('architect') or {}).get('output', '')[:2000]}\n"
            f"数据库设计：{dba_output[:1500] if dba_output else '无'}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            f"请生成可运行代码。必须输出一个合法的 JSON 对象：\n{json_example}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        template = get_language(state)
        files: List[str] = []
        security_issues: List[Dict[str, Any]] = []

        # 优先解析结构化 JSON 输出（JSON Mode / response_format）
        structured = await self._parse_json_output(output, AgentOutput)
        report: Dict[str, Any] = {}
        if structured and "files" in structured and "report" in structured:
            for f in structured.get("files", []):
                path = f.get("path", "")
                code = f.get("code", "")
                if not path:
                    continue
                if not path.endswith(f".{template.file_ext}"):
                    path += f".{template.file_ext}"
                issues = SafetyScanner.scan_code(code)
                security_issues.extend(issues)
                res = await self._write_file(path, code, workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(structured.get("report"), self.report_schema) or structured.get("report", {})
        else:
            # 兼容历史/测试中的 Markdown 代码块 + JSON 报告
            blocks = self._extract_code_blocks(output)
            for idx, block in enumerate(blocks, start=1):
                path = block["path"]
                if not path:
                    path = f"module_{idx}.{template.file_ext}"
                if not path.endswith(f".{template.file_ext}"):
                    path += f".{template.file_ext}"
                issues = SafetyScanner.scan_code(block["code"])
                security_issues.extend(issues)
                res = await self._write_file(path, block["code"], workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(output, self.report_schema) or {}

        # MOCK 降级：没有真实 LLM 时写一段占位代码，方便 CLI/测试继续跑
        if not files and self.llm.is_mock():
            stub = self._fallback_code(state.get("input", ""), template)
            res = await self._write_file(template.main_file(), stub, workspace)
            if res.get("success"):
                files.append(template.main_file())
            report = {
                "status": "mock_fallback",
                "files_modified": files,
                "test_result": "unknown",
                "note": f"MOCK 模式生成的占位代码 ({template.display})",
            }

        return {
            "files": files,
            "status": report.get("status", "completed" if files else "needs_help"),
            "test_result": report.get("test_result", "unknown"),
            "note": report.get("note", ""),
            "security_issues": security_issues,
        }

    @staticmethod
    def _fallback_code(requirement: str, template: Any) -> str:
        safe = re.sub(r"[^\w\u4e00-\u9fff]+", "_", requirement)[:30].strip("_") or "agent"
        if template.name == "java":
            class_name = safe.capitalize()
            return (
                f"package com.devagent;\n\n"
                f"public class {class_name} {{\n"
                f"    public static void main(String[] args) {{\n"
                f"        System.out.println(\"Hello from {safe}\");\n"
                f"    }}\n"
                f"}}\n"
            )
        if template.name == "go":
            return (
                f"package main\n\n"
                f"import \"fmt\"\n\n"
                f"func main() {{\n"
                f"    fmt.Println(\"Hello from {safe}\")\n"
                f"}}\n"
            )
        if template.name == "typescript":
            return (
                f"console.log(\"Hello from {safe}\");\n"
            )
        return f'"""Generated from requirement: {requirement}"""\n\ndef main():\n    print("Hello from {safe}")\n\nif __name__ == "__main__":\n    main()\n'


class TesterAgent(BaseAgent):
    json_output = True
    report_schema = TestReport
    summary_budget = 1200

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
        template = get_language(state)
        code_files = (state.get("coder") or {}).get("files", [])
        code_snippets: List[str] = []
        for f in code_files[:3]:
            res = ToolSandbox.read_file(f, base_dir=workspace)  # 同步读取即可
            if res.get("success"):
                code_snippets.append(f"--- {f} ---\n{res['content'][:1500]}")
        json_example = (
            '{"files": [{"path": "test_%s", "code": "..."}], '
            '"report": {"passed": 0, "failed": 0, "coverage": 0.0, "report": ""}}'
        ) % template.file_ext
        return (
            f"目标语言：{template.display}\n"
            f"测试框架/命令：{template.test_cmd}\n"
            f"测试文件命名：*.{template.test_ext}\n"
            f"代码文件：{code_files}\n"
            f"{''.join(code_snippets)[:2500]}\n"
            f"工作目录：{workspace}\n"
            f"请生成对应语言的测试用例。必须输出一个合法的 JSON 对象：\n{json_example}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        template = get_language(state)
        files: List[str] = []

        # 优先解析结构化 JSON 输出
        structured = await self._parse_json_output(output, AgentOutput)
        report: Dict[str, Any] = {}
        if structured and "files" in structured and "report" in structured:
            for f in structured.get("files", []):
                path = f.get("path", "")
                code = f.get("code", "")
                if not path:
                    continue
                if not path.endswith(f".{template.test_ext}"):
                    path += f".{template.test_ext}"
                res = await self._write_file(path, code, workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(structured.get("report"), self.report_schema) or structured.get("report", {})
        else:
            # 兼容历史/测试中的 Markdown 代码块 + JSON 报告
            blocks = self._extract_code_blocks(output)
            for idx, block in enumerate(blocks, start=1):
                path = block["path"]
                if not path:
                    path = f"test_module_{idx}.{template.test_ext}"
                if not path.endswith(f".{template.test_ext}"):
                    path += f".{template.test_ext}"
                res = await self._write_file(path, block["code"], workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(output, self.report_schema) or {}

        if files:
            test_res = await self._run_command(f"{template.test_cmd} -q", workspace, timeout=15)
        else:
            test_res = {"success": False, "stdout": "", "stderr": "no tests generated"}

        passed = report.get("passed")
        failed = report.get("failed")
        if passed is None or failed is None:
            passed, failed = self._parse_test_summary(test_res.get("stdout", ""))

        return {
            "files": files,
            "passed": passed,
            "failed": failed,
            "coverage": report.get("coverage", 0.0),
            "report": (test_res.get("stdout", "") + "\n" + test_res.get("stderr", "")).strip(),
            "test_command_success": test_res.get("success", False),
        }

    @staticmethod
    def _parse_test_summary(stdout: str):
        m = re.search(r"(\d+)\s+passed", stdout)
        passed = int(m.group(1)) if m else 0
        m = re.search(r"(\d+)\s+failed", stdout)
        failed = int(m.group(1)) if m else 0
        return passed, failed


class ReviewerAgent(BaseAgent):
    json_output = True
    report_schema = ReviewReport
    summary_budget = 1200

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
        report = await self._parse_json_output(output, self.report_schema)
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
    summary_budget = 800

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
    summary_budget = 1000

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
    report_schema = PRDOutput
    summary_budget = 1200

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
        report = await self._parse_json_output(output, self.report_schema) or {}
        prd_file = "prd.md"
        # 如果结构化输出里有 prd_markdown，优先写入；否则把原始输出作为 PRD 正文
        prd_body = report.get("prd_markdown") or output
        await self._write_file(prd_file, prd_body, workspace)
        return {
            "prd_file": prd_file,
            "user_stories": report.get("user_stories", []),
            "acceptance_criteria": report.get("acceptance_criteria", []),
            "parsed": report,
        }


class SecurityAgent(BaseAgent):
    json_output = True
    report_schema = ReviewReport
    summary_budget = 1200

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
        report = await self._parse_json_output(output, self.report_schema)
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
    json_output = True
    report_schema = DBAReport
    summary_budget = 1500

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
            "请输出数据库 Schema 与迁移 SQL。必须输出一个合法的 JSON 对象：\n"
            "{\"files\": [{\"path\": \"schema.sql\", \"code\": \"...\"}, {\"path\": \"migrations/001_initial.sql\", \"code\": \"...\"}], "
            "\"report\": {\"tables\": [...], \"notes\": \"\"}}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        files: List[str] = []

        # 优先解析结构化 JSON 输出
        structured = await self._parse_json_output(output, AgentOutput)
        report: Dict[str, Any] = {}
        if structured and "files" in structured and "report" in structured:
            for f in structured.get("files", []):
                path = f.get("path", "")
                code = f.get("code", "")
                if not path:
                    continue
                if not path.endswith(".sql"):
                    path += ".sql"
                res = await self._write_file(path, code, workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(structured.get("report"), self.report_schema) or structured.get("report", {})
        else:
            # 兼容历史/测试中的 Markdown 代码块 + JSON 报告
            blocks = self._extract_code_blocks(output)
            for block in blocks:
                path = block["path"]
                if not path:
                    continue
                if not path.endswith(".sql"):
                    path += ".sql"
                res = await self._write_file(path, block["code"], workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(output, self.report_schema) or {}

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
