# run_windows.ps1 — Windows 启动统一 A2A 网关
$ErrorActionPreference = "Stop"

# 优先激活虚拟环境
if (Test-Path ".venv\Scripts\Activate.ps1") {
    & .venv\Scripts\Activate.ps1
}

# 检查 .env 是否存在
if (-not (Test-Path ".env")) {
    Write-Warning ".env 不存在，将使用 .env.example 中的默认配置（MOCK 模式）"
}

# 启动统一 A2A 网关
Write-Host "启动统一 A2A 网关：http://localhost:8000"
python -m dev_agent_system.server --host 0.0.0.0 --port 8000
