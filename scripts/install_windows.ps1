# install_windows.ps1 — Windows 安装脚本
$ErrorActionPreference = "Stop"

Write-Host "==================== Windows 安装 ===================="

# 1. 检查 Python
python --version
if ($LASTEXITCODE -ne 0) {
    Write-Error "未检测到 Python，请先安装 Python 3.9+"
}

# 2. 创建虚拟环境（可选）
if (-not (Test-Path ".venv")) {
    python -m venv .venv
    Write-Host "已创建 .venv 虚拟环境"
}

# 3. 激活虚拟环境并安装依赖
& .venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 4. 创建工作目录与记忆目录
New-Item -ItemType Directory -Force -Path workspace | Out-Null
New-Item -ItemType Directory -Force -Path memory_store | Out-Null
New-Item -ItemType Directory -Force -Path backups | Out-Null
New-Item -ItemType Directory -Force -Path chroma_data | Out-Null

# 5. 提示配置 .env
if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
    Write-Host "已复制 .env.example 为 .env，请编辑填写真实 LLM API Key"
}

Write-Host "==================== 安装完成 ===================="
Write-Host "启动服务：.\scripts\run_windows.ps1"
