"""一键启动 6 个独立 A2A Agent 服务。"""
from __future__ import annotations

import subprocess
import sys
import time

AGENTS = [
    ("architect", 8081),
    ("coder", 8082),
    ("tester", 8083),
    ("docs", 8084),
    ("reviewer", 8085),
    ("devops", 8086),
]


def main() -> None:
    processes = []
    for name, port in AGENTS:
        cmd = [sys.executable, "-m", "dev_agent_system.a2a_node", "--agent", name, "--port", str(port)]
        print(f"启动 {name} Agent @ port {port}")
        p = subprocess.Popen(cmd)
        processes.append((name, p))
        time.sleep(0.5)

    print("所有 Agent 已启动，按 Ctrl+C 停止")
    try:
        for _, p in processes:
            p.wait()
    except KeyboardInterrupt:
        print("\n正在停止所有 Agent...")
        for name, p in processes:
            p.terminate()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
        print("已停止")


if __name__ == "__main__":
    main()
