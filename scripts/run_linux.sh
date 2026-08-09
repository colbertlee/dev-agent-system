#!/usr/bin/env bash
# run_linux.sh — Linux/macOS 启动统一 A2A 网关
set -e

# 优先激活虚拟环境
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# 检查 .env 是否存在
if [ ! -f ".env" ]; then
    echo "警告：.env 不存在，将使用 .env.example 中的默认配置（MOCK 模式）"
fi

echo "启动统一 A2A 网关：http://localhost:8000"
python -m dev_agent_system.server --host 0.0.0.0 --port 8000
