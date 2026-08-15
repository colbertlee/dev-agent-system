"""A2A 协议与内部状态数据模型。"""
from __future__ import annotations

import typing
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


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
    language: Optional[str] = "python"
    payload: Optional[Dict[str, Any]] = Field(default_factory=dict)


class TaskResponse(BaseModel):
    status: Literal["submitted", "working", "completed", "failed", "skipped", "awaiting_approval"] = "submitted"
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
    model_config = ConfigDict(extra="ignore")

    status: Literal["completed", "needs_help"] = "completed"
    files_modified: List[str] = Field(default_factory=list)
    test_result: Literal["passed", "failed"] = "failed"
    note: Optional[str] = None


class ReviewReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    severity: Literal["low", "medium", "high"] = "low"
    passed: bool = False
    issues: List[Dict[str, Any]] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)


class TestReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    passed: int = 0
    failed: int = 0
    coverage: float = 0.0
    report: str = ""


class WorkflowState(BaseModel):
    request_id: str
    input: str
    language: Optional[str] = "python"
    iteration: int = 0
    max_iterations: int = 10
    status: Literal["submitted", "working", "completed", "failed", "awaiting_approval"] = "submitted"
    architect: Optional[Dict[str, Any]] = None
    coder: Optional[Dict[str, Any]] = None
    tester: Optional[Dict[str, Any]] = None
    docs: Optional[Dict[str, Any]] = None
    reviewer: Optional[Dict[str, Any]] = None
    devops: Optional[Dict[str, Any]] = None
    artifacts: Dict[str, Any] = Field(default_factory=dict)


class AgentFile(BaseModel):
    """结构化输出中的单个文件对象。"""

    path: str
    code: str = ""


class AgentOutput(BaseModel):
    """结构化 Agent 输出：文件列表 + 报告字典。"""

    model_config = ConfigDict(extra="forbid")

    files: List[AgentFile] = Field(default_factory=list)
    report: Dict[str, Any] = Field(default_factory=dict)


class DesignOutput(BaseModel):
    """Architect Agent 的 JSON 输出。"""

    model_config = ConfigDict(extra="ignore")

    modules: List[str] = Field(default_factory=list)
    api_contract: Dict[str, Any] = Field(default_factory=dict)
    tech_stack: str = ""
    mermaid: str = ""
    notes: str = ""


class DBAReport(BaseModel):
    """DBA Agent 的 JSON 报告。"""

    model_config = ConfigDict(extra="ignore")

    tables: List[str] = Field(default_factory=list)
    notes: str = ""


class PRDOutput(BaseModel):
    """Product Manager Agent 的 JSON 输出。"""

    model_config = ConfigDict(extra="ignore")

    prd_markdown: str = ""
    user_stories: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)


class GraphState(typing.TypedDict, total=False):
    """LangGraph 状态图使用的状态类型（TypedDict，便于字段部分更新）。"""

    request_id: str
    input: str
    language: Optional[str]
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
    product_manager: Optional[Dict[str, Any]]
    security: Optional[Dict[str, Any]]
    dba: Optional[Dict[str, Any]]
    memory: Optional[Dict[str, Any]]
    history: List[Dict[str, Any]]
    artifacts: Dict[str, Any]
    finished_at: Optional[str]


class GraphStateModel(BaseModel):
    """GraphState 的 Pydantic 校验模型，用于启动工作流前做强类型校验。

    保持 `extra="allow"` 以兼容 LangGraph 在运行中注入的额外通道字段，
    同时确保核心字段类型、状态枚举一致。
    """

    model_config = ConfigDict(extra="allow")

    request_id: str
    input: str = ""
    language: Optional[str] = "python"
    workspace: Optional[str] = None
    iteration: int = 0
    max_iterations: int = 10
    status: Literal["submitted", "working", "completed", "failed", "awaiting_approval"] = "submitted"
    architect: Optional[Dict[str, Any]] = None
    coder: Optional[Dict[str, Any]] = None
    tester: Optional[Dict[str, Any]] = None
    docs: Optional[Dict[str, Any]] = None
    reviewer: Optional[Dict[str, Any]] = None
    devops: Optional[Dict[str, Any]] = None
    product_manager: Optional[Dict[str, Any]] = None
    security: Optional[Dict[str, Any]] = None
    dba: Optional[Dict[str, Any]] = None
    memory: Optional[Dict[str, Any]] = None
    history: List[Dict[str, Any]] = Field(default_factory=list)
    artifacts: Dict[str, Any] = Field(default_factory=dict)
    finished_at: Optional[str] = None
