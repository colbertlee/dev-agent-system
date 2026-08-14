"""DAG 编排器与迭代调度器（LangGraph StateGraph 实现）。"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from langgraph.graph import END, StateGraph

from dev_agent_system.agents import (
    ArchitectAgent,
    CoderAgent,
    DBAAgent,
    DevOpsAgent,
    DocsAgent,
    MemoryAgentFacade,
    ProductManagerAgent,
    ReviewerAgent,
    SecurityAgent,
    TesterAgent,
)
from dev_agent_system.checkpoint import make_checkpointer
from dev_agent_system.config import Settings
from dev_agent_system.devops import DevOpsRunner
from dev_agent_system.human_approval import HumanApprovalStore
from dev_agent_system.memory import MemoryAgent
from dev_agent_system.telemetry import DEFAULT as DEFAULT_TELEMETRY, Telemetry
from dev_agent_system.schemas import GraphState
from dev_agent_system.tracker import WorkflowTracker


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
    """LangGraph 状态图编排器：Architect → Coder → {Tester, Docs} 并行 → Reviewer → 条件迭代。"""

    def __init__(
        self,
        max_iterations: int = 10,
        enable_devops: bool = False,
        devops_runner: Optional[Any] = None,
        enable_product_manager: bool = False,
        enable_security: bool = False,
        enable_dba: bool = False,
        telemetry: Optional[Telemetry] = None,
        tracker: Optional[WorkflowTracker] = None,
    ):
        self.max_iterations = max_iterations
        self.enable_devops = enable_devops
        self.devops_runner = devops_runner
        self.enable_product_manager = enable_product_manager
        self.enable_security = enable_security
        self.enable_dba = enable_dba
        self.telemetry = telemetry or DEFAULT_TELEMETRY
        self.tracker = tracker or WorkflowTracker()
        self.guard = IdempotencyGuard()
        self.memory = MemoryAgent()
        self.checkpointer = make_checkpointer()
        self.approval_store = HumanApprovalStore()
        self.agents = {
            "architect": ArchitectAgent(),
            "coder": CoderAgent(),
            "tester": TesterAgent(),
            "docs": DocsAgent(),
            "reviewer": ReviewerAgent(),
            "devops": DevOpsAgent(),
            "product_manager": ProductManagerAgent(),
            "security": SecurityAgent(),
            "dba": DBAAgent(),
            "memory": MemoryAgentFacade(),
        }

    def _build_state(
        self,
        requirement: str,
        request_id: Optional[str] = None,
        language: Optional[str] = "python",
    ) -> GraphState:
        request_id = request_id or str(uuid.uuid4())
        workspace = str(Settings.workspace_dir() / request_id)
        return {
            "request_id": request_id,
            "input": requirement,
            "language": language or "python",
            "workspace": workspace,
            "iteration": 0,
            "max_iterations": self.max_iterations,
            "status": "submitted",
            "history": [],
        }

    def _build_graph(self) -> StateGraph:
        """构建并返回编译后的 LangGraph。"""
        workflow = StateGraph(GraphState)

        if self.enable_product_manager:
            workflow.add_node("product_manager_node", self._product_manager_node)
            workflow.add_node("architect_node", self._architect_node)
            workflow.set_entry_point("product_manager_node")
            workflow.add_edge("product_manager_node", "architect_node")
        else:
            workflow.set_entry_point("architect_node")
            workflow.add_node("architect_node", self._architect_node)

        workflow.add_node("coder_node", self._coder_node)
        workflow.add_node("tester_docs_node", self._tester_docs_node)
        workflow.add_node("reviewer_node", self._reviewer_node)

        if self.enable_dba:
            workflow.add_node("dba_node", self._dba_node)
            workflow.add_edge("architect_node", "dba_node")
            workflow.add_edge("dba_node", "coder_node")
        else:
            workflow.add_edge("architect_node", "coder_node")

        workflow.add_edge("coder_node", "tester_docs_node")
        workflow.add_edge("tester_docs_node", "reviewer_node")

        # 确定条件边的挂载点
        if self.enable_security:
            workflow.add_node("security_node", self._security_node)
            workflow.add_edge("reviewer_node", "security_node")
            conditional_source = "security_node"
        else:
            conditional_source = "reviewer_node"

        if self.enable_devops:
            workflow.add_node("devops_node", self._devops_node)
            workflow.add_conditional_edges(
                conditional_source,
                self._should_continue,
                {"continue": "architect_node", "end": "devops_node"},
            )
            workflow.add_edge("devops_node", END)
        else:
            workflow.add_conditional_edges(
                conditional_source,
                self._should_continue,
                {"continue": "architect_node", "end": END},
            )

        return workflow.compile(checkpointer=self.checkpointer)

    def _thread_config(self, request_id: str) -> Dict[str, Any]:
        return {
            "configurable": {"thread_id": request_id},
            "recursion_limit": max(50, self.max_iterations * 5 + 10),
        }

    async def run(
        self,
        requirement: str,
        request_id: Optional[str] = None,
        language: Optional[str] = "python",
    ) -> Dict[str, Any]:
        state = self._build_state(requirement, request_id, language=language)
        if self.guard.is_duplicate(state["request_id"]):
            return {"request_id": state["request_id"], "status": "skipped", "reason": "duplicate"}

        self.tracker.start(state["request_id"], requirement)
        with self.telemetry.span("orchestrator.run", {"request_id": state["request_id"]}):
            # 注入工作记忆
            state["memory"] = self.agents["memory"].run(state)

            graph = self._build_graph()
            config = self._thread_config(state["request_id"])
            final_state = await graph.ainvoke(state, config)
            final_state["finished_at"] = datetime.now().isoformat()
            final_state["artifacts"] = self._collect_artifacts(final_state)
            self.telemetry.record_event(
                "workflow.completed",
                request_id=state["request_id"],
                status=final_state.get("status", "unknown"),
                iterations=str(final_state.get("iteration", 0)),
            )
            self._record_workflow_metrics(final_state)
            self.tracker.finish(state["request_id"], final_state)
            return final_state

    async def resume(self, request_id: str) -> Dict[str, Any]:
        """从 SQLite checkpoint 恢复并继续执行工作流。"""
        self.tracker.update(request_id, status="resumed")
        with self.telemetry.span("orchestrator.resume", {"request_id": request_id}):
            graph = self._build_graph()
            config = self._thread_config(request_id)
            snapshot = await graph.aget_state(config)
            if snapshot is None or not snapshot.next:
                # 任务已完成或不存在未执行任务，直接取最新状态
                final_state = dict(snapshot.values) if snapshot else {}
            else:
                final_state = await graph.ainvoke(None, config)
                if final_state is None:
                    snapshot = await graph.aget_state(config)
                    final_state = dict(snapshot.values) if snapshot else {}
            final_state["finished_at"] = datetime.now().isoformat()
            final_state["artifacts"] = self._collect_artifacts(final_state)
            self._record_workflow_metrics(final_state)
            self.tracker.finish(request_id, final_state)
            return final_state

    async def approve_devops(self, request_id: str, approve: bool = True) -> Dict[str, Any]:
        """审批并继续执行 DevOps 部署节点。

        适用于 workflow 在 _devops_node 因缺少人工审批而进入 awaiting_approval 状态后，
        由管理员通过 API 调用继续。
        """
        if approve:
            self.approval_store.approve(request_id)
        else:
            self.approval_store.reject(request_id)
            final_state = {"request_id": request_id, "status": "rejected", "devops": {"approved": False}}
            self.tracker.finish(request_id, final_state)
            return final_state

        graph = self._build_graph()
        config = self._thread_config(request_id)
        snapshot = await graph.aget_state(config)
        if snapshot is None:
            return {"request_id": request_id, "status": "not_found", "error": "checkpoint not found"}

        state = dict(snapshot.values)
        state["status"] = "working"
        final_state = await self._devops_node(state)
        final_state["finished_at"] = datetime.now().isoformat()
        final_state["artifacts"] = self._collect_artifacts(final_state)
        self._record_workflow_metrics(final_state)
        self.tracker.finish(request_id, final_state)
        return final_state

    def get_approval_status(self, request_id: str) -> str:
        return self.approval_store.get_status(request_id)

    def list_checkpoints(self, request_id: str) -> List[Dict[str, Any]]:
        """返回指定 request_id 的历史 checkpoint 列表。"""
        config: Dict[str, Any] = {"configurable": {"thread_id": request_id}}
        return [
            {
                "checkpoint_id": tuple_item.config["configurable"].get("checkpoint_id"),
                "metadata": tuple_item.metadata,
            }
            for tuple_item in self.checkpointer.list(config)
        ]

    async def run_stream(
        self,
        requirement: str,
        request_id: Optional[str] = None,
        language: Optional[str] = "python",
    ) -> AsyncIterator[str]:
        """流式执行编排，SSE 格式输出每个节点的事件。"""
        state = self._build_state(requirement, request_id, language=language)
        if self.guard.is_duplicate(state["request_id"]):
            yield f"data: {json.dumps({'event': 'duplicate', 'request_id': state['request_id']}, ensure_ascii=False)}\n\n"
            return

        state["memory"] = self.agents["memory"].run(state)
        graph = self._build_graph()
        config = self._thread_config(state["request_id"])

        yield f"data: {json.dumps({'event': 'start', 'request_id': state['request_id'], 'workspace': state['workspace']}, ensure_ascii=False)}\n\n"

        # LangGraph 0.2.0 支持 astream_events，失败则降级到普通 ainvoke
        try:
            async for event in graph.astream_events(state, config, version="v1"):
                kind = event.get("event")
                name = event.get("name", "")
                if kind in ("on_node_start", "on_node_end"):
                    payload = {
                        "event": kind,
                        "node": name,
                        "request_id": state["request_id"],
                    }
                    if kind == "on_node_end" and "data" in event and "state" in event["data"]:
                        node_state = event["data"]["state"]
                        payload["iteration"] = node_state.get("iteration", 0)
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            # 降级：直接执行并输出结果
            final_state = await graph.ainvoke(state, config=config)
            yield f"data: {json.dumps({'event': 'fallback', 'error': str(exc), 'status': final_state.get('status')}, ensure_ascii=False)}\n\n"
            final_state["finished_at"] = datetime.now().isoformat()
            final_state["artifacts"] = self._collect_artifacts(final_state)
            yield f"data: {json.dumps({'event': 'final', 'request_id': state['request_id'], **final_state}, ensure_ascii=False)}\n\n"
            return

        final_state = await graph.ainvoke(state, config=config)
        final_state["finished_at"] = datetime.now().isoformat()
        final_state["artifacts"] = self._collect_artifacts(final_state)
        yield f"data: {json.dumps({'event': 'final', 'status': final_state.get('status'), 'request_id': state['request_id'], 'workspace': state['workspace']}, ensure_ascii=False)}\n\n"

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
        if not _review_passed(review):
            if state.get("iteration", 0) >= self.max_iterations:
                return "end"
            return "continue"

        # reviewer 通过后，若启用 Security Agent，还需通过安全审查
        if self.enable_security:
            security = state.get("security") or {}
            if not _review_passed(security):
                if state.get("iteration", 0) >= self.max_iterations:
                    return "end"
                return "continue"

        return "end"

    async def _product_manager_node(self, state: GraphState) -> GraphState:
        state["product_manager"] = await self._run_agent("product_manager", state)
        return state

    async def _dba_node(self, state: GraphState) -> GraphState:
        state["dba"] = await self._run_agent("dba", state)
        return state

    async def _security_node(self, state: GraphState) -> GraphState:
        state["security"] = await self._run_agent("security", state)
        return state

    async def _devops_node(self, state: GraphState) -> GraphState:
        devops_result = await self._run_agent("devops", state)
        request_id = state.get("request_id", "default")
        runner = self.devops_runner or DevOpsRunner(
            dry_run=Settings.devops_dry_run(),
            timeout=Settings.devops_timeout(),
        )
        workspace = Path(state.get("workspace", Settings.workspace_dir() / request_id))

        # 仅在需要真实执行时触发人工审批
        dry_run = getattr(runner, "dry_run", Settings.devops_dry_run())
        if not dry_run and Settings.human_approval_required() and not self.approval_store.is_approved(request_id):
            self.approval_store.request_approval(request_id)
            devops_result["needs_approval"] = True
            devops_result["approved"] = False
            devops_result["deployment"] = {
                "deployed": False,
                "status": "awaiting_approval",
                "note": "等待人工审批后才能执行真实部署",
            }
            state["status"] = "awaiting_approval"
            state["devops"] = devops_result
            return state

        deployment = await asyncio.to_thread(runner.run, request_id, workspace)
        devops_result["deployment"] = deployment
        devops_result["needs_approval"] = False
        devops_result["approved"] = True
        state["devops"] = devops_result
        return state

    async def _run_agent(self, name: str, state: GraphState) -> Dict[str, Any]:
        agent = self.agents[name]
        request_id = state.get("request_id", "")
        self.tracker.update(
            request_id,
            current_agent=name,
            iteration=state.get("iteration", 0),
            status="working",
        )
        with self.telemetry.span(f"agent.{name}", {"agent": name, "request_id": request_id}):
            if asyncio.iscoroutinefunction(agent.run):
                result = await agent.run(state)
            else:
                result = agent.run(state)
            status = "error" if result and not result.get("success", True) else "ok"
            self.telemetry.collector.counter(
                "agent_runs_total",
                "Total number of agent runs",
                labelnames=["agent", "status"],
            ).inc(agent=name, status=status)
            return result

    def _record_workflow_metrics(self, state: GraphState) -> None:
        request_id = state.get("request_id", "")
        iterations = state.get("iteration", 0)
        status = state.get("status", "unknown")
        review = state.get("reviewer") or {}
        review_passed = _review_passed(review)

        self.telemetry.collector.gauge("workflow_iterations", "Workflow iteration count").set(
            iterations, request_id=request_id
        )
        self.telemetry.collector.counter(
            "workflow_total",
            "Total number of workflow runs",
            labelnames=["status"],
        ).inc(status=status)
        self.telemetry.collector.counter(
            "review_decisions_total",
            "Total number of review decisions",
            labelnames=["passed"],
        ).inc(passed=str(review_passed).lower())

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
            "product_manager": (state.get("product_manager") or {}).get("output", "") if state.get("product_manager") else "",
            "prd_file": (state.get("product_manager") or {}).get("prd_file"),
            "security_report": (state.get("security") or {}).get("report_file"),
            "security_passed": _review_passed(state.get("security") or {}),
            "schema_files": (state.get("dba") or {}).get("files", []),
        }
