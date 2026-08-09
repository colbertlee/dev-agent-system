"""CLI 入口。"""
from __future__ import annotations

import argparse
import asyncio
import json

from dev_agent_system.orchestrator import Orchestrator


async def cli():
    parser = argparse.ArgumentParser(description="软件开发多 Agent 协作系统 CLI")
    parser.add_argument(
        "requirement",
        nargs="?",
        default="开发一个支持 JWT 的用户登录模块",
        help="自然语言需求",
    )
    parser.add_argument("--max-iter", type=int, default=3, help="最大迭代次数")
    parser.add_argument("--devops", action="store_true", help="启用 DevOps Agent")
    parser.add_argument(
        "--output",
        default="orchestrator_result.json",
        help="结果 JSON 文件路径",
    )
    args = parser.parse_args()

    orch = Orchestrator(max_iterations=args.max_iter, enable_devops=args.devops)
    result = await orch.run(args.requirement)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"✅ 工作流完成，状态：{result.get('status')}")
    print(f"📄 结果已保存至：{args.output}")


if __name__ == "__main__":
    asyncio.run(cli())
