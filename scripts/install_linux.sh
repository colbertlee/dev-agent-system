#!/usr/bin/env bash
# install_linux.sh — Linux/macOS 安装脚本
set -e

echo "==================== Linux 安装 ===================="

# 1. 检查 Python
python3 --version || { echo "未检测到 python3"; exit 1; }

# 2. 创建虚拟环境（可选）
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "已创建 .venv 虚拟环境"
fi

# 3. 激活虚拟环境并安装依赖
source .venv/bin/activate
pip install -r requirements.txt

# 4. 创建运行目录
mkdir -p workspace memory_store backups chroma_data

# 5. 提示配置 .env
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "已复制 .env.example 为 .env，请编辑填写真实 LLM API Key"
fi

echo "==================== 安装完成 ===================="
echo "启动服务：bash scripts/run_linux.sh"
