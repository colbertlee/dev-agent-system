"""DAG 编排器与迭代调度器（LangGraph StateGraph 实现）。"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from langgraph.graph import END, StateGraph

from dev_agent_system.agents import (
    ArchitectAgent,
    CoderAgent,
    DevOpsAgent,
    DocsAgent,
    MemoryAgentFacade,
    ReviewerAgent,
    TesterAgent,
)
from dev_agent_system.memory import MemoryAgent
from dev_agent_system.config import Settings
from dev_agent_system.types import GraphState


def _review_passed(review: Dict[str, Any]) -> bool:
    """从 Reviewer 结构化输出中判断是否通过。"""
    passed = review.get("passed")
    if isinstance(passed, bool):
        return passed
    if isinstance(passed, str):
        return passed.lower() == "true"
    output = str(review.get("output", "")).lower()
    return '"passed": true' in output


class IdempotencyGuard:
    """基于 request_id 的幂等请求去重。"""

    def __init__(self, max_size: int = 200):
        self._seen: set = set()
        self._max_size = max_size

    def is_duplicate(self, request_id: str) -> bool:
        if request_id in self._seen:
            return True
        self._seen.add(request_id)
        if len(self._seen) > self._max_size:
            self._seen.pop()
        return False


class Orchestrator:
    """LangGraph 状态图编排器：Architect → {Coder,Tester,Docs} 并行 → Reviewer → 条件迭代。"""

    def __init__(self, max_iterations: int = 10, enable_devops: bool = False):
        self.max_iterations = max_iterations
        self.enable_devops = enable_devops
        self.guard = IdempotencyGuard()
        self.memory = MemoryAgent()
        self.agents = {
            "architect": ArchitectAgent(),
            "coder": CoderAgent(),
            "tester": TesterAgent(),
            "docs": DocsAgent(),
            "reviewer": ReviewerAgent(),
            "devops": DevOpsAgent(),
            "memory": MemoryAgentFacade(),
        }

    async def run(self, requirement: str, request_id: Optional[str] = None) -> Dict[str, Any]:
        request_id = request_id or str(uuid.uuid4())
        if self.guard.is_duplicate(request_id):
            return {"request_id": request_id, "status": "skipped", "reason": "duplicate"}

        workspace = str(Settings.workspace_dir() / request_id)
        state: GraphState = {
            "request_id": request_id,
            "input": requirement,
            "workspace": workspace,
            "iteration": 0,
            "max_iterations": self.max_iterations,
            "status": "submitted",
            "history": [],
        }

        # 注入工作记忆
        state["memory"] = self.agents["memory"].run(state)

        # 构建 LangGraph StateGraph
        # 流程：Architect -> Coder -> {Tester, Docs} 并行 -> Reviewer -> 条件迭代
        workflow = StateGraph(GraphState)
        workflow.add_node("architect_node", self._architect_node)
        workflow.add_node("coder_node", self._coder_node)
        workflow.add_node("tester_docs_node", self._tester_docs_node)
        workflow.add_node("reviewer_node", self._reviewer_node)

        workflow.set_entry_point("architect_node")
        workflow.add_edge("architect_node", "coder_node")
        workflow.add_edge("coder_node", "tester_docs_node")
        workflow.add_edge("tester_docs_node", "reviewer_node")

        if self.enable_devops:
            workflow.add_node("devops_node", self._devops_node)
            workflow.add_conditional_edges(
                "reviewer_node",
                self._should_continue,
                {"continue": "architect_node", "end": "devops_node"},
            )
            workflow.add_edge("devops_node", END)
        else:
            workflow.add_conditional_edges(
                "reviewer_node",
                self._should_continue,
                {"continue": "architect_node", "end": END},
            )

        graph = workflow.compile()
        config = {"recursion_limit": max(50, self.max_iterations * 5 + 10)}
        final_state = await graph.ainvoke(state, config=config)
        final_state["finished_at"] = datetime.now().isoformat()
        final_state["artifacts"] = self._collect_artifacts(final_state)
        return final_state

    async def _architect_node(self, state: GraphState) -> GraphState:
        state["iteration"] = state.get("iteration", 0) + 1
        state["status"] = "working"
        state["architect"] = await self._run_agent("architect", state)
        return state

    async def _coder_node(self, state: GraphState) -> GraphState:
        state["coder"] = await self._run_agent("coder", state)
        return state

    async def _tester_docs_node(self, state: GraphState) -> GraphState:
        tester, docs = await asyncio.gather(
            self._run_agent("tester", state),
            self._run_agent("docs", state),
        )
        state["tester"] = tester
        state["docs"] = docs
        return state

    async def _reviewer_node(self, state: GraphState) -> GraphState:
        state["reviewer"] = await self._run_agent("reviewer", state)
        record = {
            "iteration": state.get("iteration", 0),
            "architect": state.get("architect"),
            "coder": state.get("coder"),
            "tester": state.get("tester"),
            "docs": state.get("docs"),
            "reviewer": state.get("reviewer"),
        }
        state["history"] = (state.get("history", []) + [record])[-5:]
        review = state.get("reviewer") or {}
        passed = _review_passed(review)
        # 在节点内设置状态（条件边函数不应修改状态）
        if passed:
            state["status"] = "completed"
        elif state.get("iteration", 0) >= self.max_iterations:
            state["status"] = "failed"
        else:
            state["status"] = "working"
        self.memory.remember(
            f"review_iter_{state.get('iteration', 0)}",
            review.get("output", ""),
            session_id=state.get("request_id", "default"),
            layer="working",
        )
        return state

    def _should_continue(self, state: GraphState) -> str:
        review = state.get("reviewer") or {}
        if _review_passed(review):
            return "end"
        if state.get("iteration", 0) >= self.max_iterations:
            return "end"
        return "continue"

    async def _devops_node(self, state: GraphState) -> GraphState:
        state["devops"] = await self._run_agent("devops", state)
        return state

    async def _run_agent(self, name: str, state: GraphState) -> Dict[str, Any]:
        agent = self.agents[name]
        if asyncio.iscoroutinefunction(agent.run):
            return await agent.run(state)
        return agent.run(state)

    @staticmethod
    def _collect_artifacts(state: GraphState) -> Dict[str, Any]:
        return {
            "workspace": state.get("workspace", ""),
            "design": (state.get("architect") or {}).get("output", ""),
            "design_file": (state.get("architect") or {}).get("design_file"),
            "code_files": (state.get("coder") or {}).get("files", []),
            "test_files": (state.get("tester") or {}).get("files", []),
            "doc_files": (state.get("docs") or {}).get("files", []),
            "review_report": (state.get("reviewer") or {}).get("report_file"),
            "review_passed": _review_passed(state.get("reviewer") or {}),
            "tests": (state.get("tester") or {}).get("output", ""),
            "docs": (state.get("docs") or {}).get("output", ""),
            "review": (state.get("reviewer") or {}).get("output", ""),
            "devops": (state.get("devops") or {}).get("output", "") if state.get("devops") else "",
        }
