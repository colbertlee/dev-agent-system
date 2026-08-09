"""FastAPI A2A 网关：统一暴露所有 Agent Card 与任务端点。"""
from __future__ import annotations

import argparse
import asyncio
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn

from dev_agent_system.agents import (
    ArchitectAgent,
    CoderAgent,
    DevOpsAgent,
    DocsAgent,
    ReviewerAgent,
    TesterAgent,
)
from dev_agent_system.orchestrator import Orchestrator
from dev_agent_system.types import JSONRPCRequest, JSONRPCResponse, Task, TaskResponse

app = FastAPI(title="Dev Agent System A2A Gateway")

AGENTS: Dict[str, Any] = {
    "architect": ArchitectAgent(),
    "coder": CoderAgent(),
    "tester": TesterAgent(),
    "docs": DocsAgent(),
    "reviewer": ReviewerAgent(),
    "devops": DevOpsAgent(),
}

INTERNAL_API_KEY = "dev-internal-key"  # 生产应通过环境变量配置


def _auth(internal_key: Optional[str]) -> None:
    if internal_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid internal API key")


for _name, _agent in AGENTS.items():
    # 使用工厂函数避免在 FastAPI 默认参数中保存不可序列化的 Agent 对象
    def _register_agent_routes(name: str = _name, agent=_agent):
        @app.get(f"/{name}/.well-known/agent.json")
        def _card():
            return agent.agent_card(url=f"http://localhost:8000/{name}").model_dump()

        @app.post(f"/{name}/tasks")
        async def _task(task: Task):
            state = {"input": task.description, "request_id": task.request_id or f"task-{name}"}
            result = agent.run(state) if not asyncio.iscoroutinefunction(agent.run) else await agent.run(state)
            return TaskResponse(status="completed", task_id=task.request_id or f"{name}-001", result=result)

        @app.get(f"/{name}/tasks/{{task_id}}")
        def _status(task_id: str):
            return {"task_id": task_id, "status": "completed"}

    _register_agent_routes()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/orchestrate")
async def orchestrate(task: Task, internal_key: Optional[str] = Header(None, alias="X-Internal-API-Key")):
    _auth(internal_key)
    max_iter = task.max_iterations or 10
    orch = Orchestrator(max_iterations=max_iter)
    result = await orch.run(task.description, request_id=task.request_id)
    return JSONResponse(content=result)


@app.post("/rpc")
async def rpc(req: JSONRPCRequest, internal_key: Optional[str] = Header(None, alias="X-Internal-API-Key")):
    _auth(internal_key)
    method = req.method
    if method == "orchestrate":
        params = req.params or {}
        max_iter = params.get("max_iterations", 10)
        orch = Orchestrator(max_iterations=max_iter)
        result = await orch.run(params.get("description", ""), request_id=req.id)
        return JSONRPCResponse(result=result, id=req.id)
    return JSONRPCResponse(result={"error": "unknown method"}, id=req.id)


@app.get("/tasks/{task_id}/stream")
def stream(task_id: str):
    async def event_generator():
        for i in range(5):
            yield f"data: {{\"task_id\": \"{task_id}\", \"progress\": {(i+1)*20}}}\n\n"
            await asyncio.sleep(0.2)
        yield f"data: {{\"task_id\": \"{task_id}\", \"status\": \"completed\"}}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
