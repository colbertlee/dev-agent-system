"""FastAPI A2A 网关：统一暴露所有 Agent Card 与任务端点，支持流式编排。"""
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
    DBAAgent,
    DevOpsAgent,
    DocsAgent,
    ProductManagerAgent,
    ReviewerAgent,
    SecurityAgent,
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
    "product_manager": ProductManagerAgent(),
    "security": SecurityAgent(),
    "dba": DBAAgent(),
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
            result = await agent.run(state)
            return TaskResponse(status="completed", task_id=task.request_id or f"{name}-001", result=result)

        @app.get(f"/{name}/tasks/{{task_id}}")
        def _status(task_id: str):
            return {"task_id": task_id, "status": "completed"}

        @app.post(f"/{name}/stream")
        async def _stream(task: Task):
            """单个 Agent 的流式输出：逐字返回 LLM 生成的 token。"""
            state = {"input": task.description, "request_id": task.request_id or f"stream-{name}"}
            from dev_agent_system.llm import LLMClient

            llm = LLMClient(model=agent.model)
            prompt = agent.build_prompt(state)

            async def event_generator():
                async for token in llm.astream(agent.system_prompt, prompt):
                    yield f"data: {token}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(event_generator(), media_type="text/event-stream")

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


@app.post("/orchestrate/stream")
async def orchestrate_stream(
    task: Task, internal_key: Optional[str] = Header(None, alias="X-Internal-API-Key")
):
    _auth(internal_key)
    max_iter = task.max_iterations or 10
    orch = Orchestrator(max_iterations=max_iter)

    async def event_generator():
        async for chunk in orch.run_stream(task.description, request_id=task.request_id):
            yield chunk

    return StreamingResponse(event_generator(), media_type="text/event-stream")


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
    if method == "orchestrate_stream":
        params = req.params or {}
        max_iter = params.get("max_iterations", 10)
        orch = Orchestrator(max_iterations=max_iter)

        async def event_generator():
            async for chunk in orch.run_stream(params.get("description", ""), request_id=req.id):
                yield chunk

        return StreamingResponse(event_generator(), media_type="text/event-stream")
    return JSONRPCResponse(result={"error": "unknown method"}, id=req.id)


@app.get("/tasks/{request_id}/checkpoints")
def list_checkpoints(request_id: str):
    """查询指定任务的历史 checkpoint 列表。"""
    orch = Orchestrator()
    checkpoints = orch.list_checkpoints(request_id)
    return {"request_id": request_id, "checkpoints": checkpoints}


@app.post("/tasks/{request_id}/resume")
async def resume_task(request_id: str):
    """从最近的 checkpoint 恢复并继续执行工作流。"""
    orch = Orchestrator()
    result = await orch.resume(request_id)
    return result


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
