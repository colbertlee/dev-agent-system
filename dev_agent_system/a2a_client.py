"""A2A 客户端：Agent 发现与任务委派。"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

import httpx

from dev_agent_system.types import AgentCard, JSONRPCRequest, JSONRPCResponse, Task, TaskResponse


class A2AClient:
    """轻量级 A2A 客户端：支持 Agent Card 发现、任务发送、JSON-RPC。"""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def discover(self) -> AgentCard:
        """读取 Agent Card（/.well-known/agent.json）。"""
        resp = self._client.get("/.well-known/agent.json")
        resp.raise_for_status()
        return AgentCard(**resp.json())

    def send_task(self, description: str, request_id: Optional[str] = None, payload: Optional[Dict[str, Any]] = None) -> TaskResponse:
        """向该 Agent 发送任务。"""
        request_id = request_id or str(uuid.uuid4())
        task = Task(description=description, request_id=request_id, payload=payload)
        resp = self._client.post("/tasks", json=task.model_dump(exclude_none=True))
        resp.raise_for_status()
        return TaskResponse(**resp.json())

    def get_status(self, task_id: str) -> Dict[str, Any]:
        resp = self._client.get(f"/tasks/{task_id}")
        resp.raise_for_status()
        return resp.json()

    def rpc(self, method: str, params: Any, req_id: Optional[str] = None) -> JSONRPCResponse:
        request = JSONRPCRequest(method=method, params=params, id=req_id or str(uuid.uuid4()))
        resp = self._client.post("/rpc", json=request.model_dump())
        resp.raise_for_status()
        return JSONRPCResponse(**resp.json())

    def close(self) -> None:
        self._client.close()


def discover_agent(url: str) -> AgentCard:
    """一次性发现辅助函数。"""
    return A2AClient(url).discover()


def send_task_to(url: str, description: str, request_id: Optional[str] = None) -> TaskResponse:
    """一次性发送任务辅助函数。"""
    client = A2AClient(url)
    try:
        return client.send_task(description, request_id=request_id)
    finally:
        client.close()
