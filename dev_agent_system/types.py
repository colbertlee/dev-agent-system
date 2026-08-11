"""A2A 协议与内部状态数据模型。"""
from __future__ import annotations

import typing
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class AgentSkill(BaseModel):
    name: str


class AgentCard(BaseModel):
    name: str
    url: str
    skills: List[AgentSkill]
    capabilities: Dict[str, Any] = Field(default_factory=dict)


class Task(BaseModel):
    description: str
    task_id: Optional[str] = None
    request_id: Optional[str] = None
    max_iterations: Optional[int] = None
    payload: Optional[Dict[str, Any]] = Field(default_factory=dict)


class TaskResponse(BaseModel):
    status: Literal["submitted", "working", "completed", "failed", "skipped"] = "submitted"
    task_id: str
    result: Optional[Any] = None


class JSONRPCRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    method: str
    params: Any
    id: str


class JSONRPCResponse(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    result: Any
    id: str


class CoderReport(BaseModel):
    status: Literal["completed", "needs_help"] = "completed"
    files_modified: List[str] = Field(default_factory=list)
    test_result: Literal["passed", "failed"] = "failed"
    note: Optional[str] = None


class ReviewReport(BaseModel):
    severity: Literal["low", "medium", "high"] = "low"
    passed: bool = False
    issues: List[Dict[str, Any]] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)


class TestReport(BaseModel):
    passed: int = 0
    failed: int = 0
    coverage: float = 0.0
    report: str = ""


class WorkflowState(BaseModel):
    request_id: str
    input: str
    iteration: int = 0
    max_iterations: int = 10
    status: Literal["submitted", "working", "completed", "failed"] = "submitted"
    architect: Optional[Dict[str, Any]] = None
    coder: Optional[Dict[str, Any]] = None
    tester: Optional[Dict[str, Any]] = None
    docs: Optional[Dict[str, Any]] = None
    reviewer: Optional[Dict[str, Any]] = None
    devops: Optional[Dict[str, Any]] = None
    artifacts: Dict[str, Any] = Field(default_factory=dict)


class GraphState(typing.TypedDict, total=False):
    """LangGraph 状态图使用的状态类型（TypedDict，便于字段部分更新）。"""

    request_id: str
    input: str
    workspace: str
    iteration: int
    max_iterations: int
    status: str
    architect: Optional[Dict[str, Any]]
    coder: Optional[Dict[str, Any]]
    tester: Optional[Dict[str, Any]]
    docs: Optional[Dict[str, Any]]
    reviewer: Optional[Dict[str, Any]]
    devops: Optional[Dict[str, Any]]
    memory: Optional[Dict[str, Any]]
    history: List[Dict[str, Any]]
    artifacts: Dict[str, Any]
    finished_at: Optional[str]
