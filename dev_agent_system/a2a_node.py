"""A2A 独立 Agent 节点启动器。

用法：
    python -m dev_agent_system.a2a_node --agent architect --port 8081
    python -m dev_agent_system.a2a_node --agent coder --port 8082
"""
from __future__ import annotations

import argparse
import uuid
from typing import Any, Dict

from fastapi import FastAPI
import uvicorn

from dev_agent_system.agents import (
    ArchitectAgent,
    CoderAgent,
    DevOpsAgent,
    DocsAgent,
    ReviewerAgent,
    TesterAgent,
)
from dev_agent_system.schemas import Task, TaskResponse

AGENT_CLASSES: Dict[str, Any] = {
    "architect": ArchitectAgent,
    "coder": CoderAgent,
    "tester": TesterAgent,
    "reviewer": ReviewerAgent,
    "docs": DocsAgent,
    "devops": DevOpsAgent,
}


def create_app(agent_name: str, agent: Any, port: int) -> FastAPI:
    app = FastAPI(title=f"{agent_name} A2A Agent")

    @app.get("/.well-known/agent.json")
    def agent_card():
        return agent.agent_card(url=f"http://localhost:{port}").model_dump()

    @app.post("/tasks")
    async def receive_task(task: Task):
        request_id = task.request_id or str(uuid.uuid4())
        state = {"input": task.description, "request_id": request_id, "payload": task.payload or {}}
        result = await agent.run(state)
        return TaskResponse(status="completed", task_id=request_id, result=result)

    @app.get("/tasks/{task_id}")
    def task_status(task_id: str):
        return {"task_id": task_id, "status": "completed"}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="启动单个 A2A Agent 服务")
    parser.add_argument("--agent", required=True, choices=list(AGENT_CLASSES), help="Agent 名称")
    parser.add_argument("--port", type=int, required=True, help="监听端口")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    args = parser.parse_args()

    agent_cls = AGENT_CLASSES[args.agent]
    agent = agent_cls()
    app = create_app(args.agent, agent, args.port)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
