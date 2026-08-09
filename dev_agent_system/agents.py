"""6 个业务 Agent + Memory Agent 的实现。"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from dev_agent_system.config import Settings
from dev_agent_system.llm import LLMClient
from dev_agent_system.memory import MemoryAgent
from dev_agent_system.mcp import MCPToolRegistry
from dev_agent_system.types import AgentCard, AgentSkill


class BaseAgent:
    """所有业务 Agent 的基类。"""

    def __init__(
        self,
        name: str,
        role: str,
        system_prompt: str,
        model: Optional[str] = None,
        skills: Optional[List[str]] = None,
    ):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.model = model or Settings.agent_model(name.lower())
        self.skills = skills or [role]
        self.llm = LLMClient(model=self.model)
        self.memory = MemoryAgent()
        self.tools = MCPToolRegistry()

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return str(state.get("input", ""))

    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        session = state.get("request_id", "default")
        memories = self.memory.recall(state.get("input", ""), session_id=session, layer="working", top_k=3)
        memory_text = "\n".join(str(m["value"]) for m in memories)
        prompt = self.build_prompt(state)
        full_prompt = f"相关记忆：\n{memory_text}\n\n{prompt}" if memory_text else prompt
        output = self.llm.chat(self.system_prompt, full_prompt)
        self.memory.remember("last_output", output, session_id=session, layer="short", ttl=3600)
        return {"agent": self.name, "role": self.role, "output": output}

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
        return (
            f"用户需求：{state.get('input', '')}\n"
            "请输出 JSON 格式架构设计：{\"modules\", \"api_contract\", \"tech_stack\", \"mermaid\", \"notes\"}"
        )


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
        return (
            f"架构设计：{(state.get('architect') or {}).get('output', '')}\n"
            "请生成可运行代码，并在最后输出 JSON 状态报告："
            "{\"status\": \"completed|needs_help\", \"files_modified\": [], \"test_result\": \"passed|failed\", \"note\": \"\"}"
        )


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
        return (
            f"代码：{(state.get('coder') or {}).get('output', '')[:2000]}\n"
            f"API 契约：{str((state.get('architect') or {}).get('output', ''))[:800]}\n"
            "请生成 pytest 测试用例与测试报告 JSON：{\"passed\", \"failed\", \"coverage\", \"report\"}"
        )


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
            f"代码：{(state.get('coder') or {}).get('output', '')[:2000]}\n"
            f"测试：{(state.get('tester') or {}).get('output', '')[:1200]}\n"
            f"文档：{(state.get('docs') or {}).get('output', '')[:800]}\n"
            "请独立思考，从需求出发审查。输出 JSON："
            "{\"severity\": \"low|medium|high\", \"passed\": bool, \"issues\": [], \"suggestions\": []}"
        )


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
            f"代码：{(state.get('coder') or {}).get('output', '')[:1000]}\n"
            "请生成 README + API 文档摘要，不要修改代码。"
        )


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
            f"代码：{(state.get('coder') or {}).get('output', '')[:1200]}\n"
            "请生成 Dockerfile 与 CI/CD 配置摘要，并说明部署前需人工确认。"
        )


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
}
