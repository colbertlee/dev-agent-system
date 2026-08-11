# 软件开发多 Agent 协作系统

基于 `框架一_软件开发多Agent系统.html` 实现的完整多 Agent 开发框架。

## 架构

- **6 个业务 Agent**：Architect、Coder、Tester、Reviewer、Docs、DevOps
- **3 个支撑组件**：Orchestrator、Memory、Scheduler（迭代控制）
- **编排**：LangGraph `StateGraph` DAG，`Architect → Coder → {Tester, Docs} → Reviewer`
- **通信**：A2A 协议，`/.well-known/agent.json` + `/tasks`
- **工具**：MCP 风格工具沙箱（白名单+黑名单+路径限制+超时）
- **记忆**：三层记忆（短期/工作/长期），默认内存+SQLite 降级

## 文档导航

| 文档 | 内容 |
|---|---|
| [README.md](README.md) | 快速开始、部署方式、设计要点 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 架构图、数据流、模块依赖、部署形态 |
| [CONTRIBUTE.md](CONTRIBUTE.md) | 代码规范、Git 提交格式、分支策略、PR checklist |
| [AGENTS.md](AGENTS.md) | 多 Agent 协作规则、状态图、扩展方式 |
| [docs/usage_operations.md](docs/usage_operations.md) | 安装、部署、监控、备份、故障排查 |
| [docs/tools_spec.md](docs/tools_spec.md) | MCP 工具 JSON Schema、白名单、错误码 |
| [docs/prompt_templates.md](docs/prompt_templates.md) | System Prompt 版本管理、输出格式约定 |
| [RELEASE_NOTES.md](RELEASE_NOTES.md) | 版本价值、影响矩阵、升级建议 |
| [CHANGELOG.md](CHANGELOG.md) | 扁平化变更清单 |

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 运行完整工作流（MOCK 模式）
python -m dev_agent_system.main "开发一个支持 JWT 的用户登录模块"

# 指定目标语言（python / java / go / typescript）
python -m dev_agent_system.main "开发一个加法模块" --language go

# TUI 终端进度面板（需安装 rich）
python -m dev_agent_system.tui "开发一个支持 JWT 的用户登录模块"

# TUI 指定语言
python -m dev_agent_system.tui "开发一个加法模块" --language go

# 启动统一 A2A 网关（含 /health、/metrics、/dashboard）
python -m dev_agent_system.server --port 8000

# 查看 Prometheus 指标
curl http://localhost:8000/metrics

# 运行安全扫描（Secret + 依赖漏洞 + 容器沙箱示例，依赖 safety/pip-audit/docker）
python - <<'PY'
from pathlib import Path
from dev_agent_system.security_scanner import SecurityPipeline
pipeline = SecurityPipeline(Path("workspace/<request_id>"), Path("requirements.txt"))
print(pipeline.run(command="pytest -q", use_container=False))
PY

# 打开 Web Dashboard
open http://localhost:8000/dashboard  # Linux/macOS
# start http://localhost:8000/dashboard  # Windows

# 启动 6 个独立 A2A Agent 服务
python scripts/run_a2a_cluster.py

# 或单独启动某个 Agent
python -m dev_agent_system.a2a_node --agent architect --port 8081

# 安装并调用一个 Skill（示例）
python - <<'PY'
from dev_agent_system.skills import SkillManager
manager = SkillManager()
manager.install({
    "id": "greet",
    "name": "问候",
    "description": "返回问候语",
    "code": "def run(name='world'):\n    return {'success': True, 'message': f'Hello, {name}'}\n",
})
print(manager.invoke("greet", name="dev"))
PY

# 运行测试
pytest -q

# 运行评估 benchmark（默认使用 tests/eval_dataset.json）
python -m dev_agent_system.eval --max-iter 3 --output-dir eval_results

# 首次跑 benchmark 并保存 baseline
python -m dev_agent_system.eval --max-iter 3 --output-dir eval_results --update-baseline

# 后续做回归检测（指标下降超过 5% 会返回非 0 退出码）
python -m dev_agent_system.eval --max-iter 3 --output-dir eval_results --baseline eval_results/eval_baseline.json

# 运行完整工作流并启用 DevOps 闭环（dry-run，不实际部署）
python -m dev_agent_system.main "开发一个加法模块" --max-iter 1 --devops

# 真实 DevOps 闭环（需本地安装 Docker 并设置 DEVOPS_DRY_RUN=false）
# $env:DEVOPS_DRY_RUN="false"
# python -m dev_agent_system.main "开发一个加法模块" --max-iter 1 --devops
```

## 配置真实 LLM

## OpenAI / DeepSeek

```bash
export LLM_PROVIDER="openai"
export LLM_API_KEY="your-key"
export LLM_BASE_URL="https://api.deepseek.com"
export LLM_MODEL="deepseek-chat"
```

## Ollama 本地模型

```bash
export LLM_PROVIDER="ollama"
export OLLAMA_URL="http://localhost:11434"
export LLM_MODEL="llama3"
```

> 也可以直接在 `LLM_MODEL` 中使用前缀：`LLM_MODEL="ollama/llama3"`。

Windows:
```powershell
$env:LLM_PROVIDER="openai"
$env:LLM_API_KEY="your-key"
$env:LLM_BASE_URL="https://api.deepseek.com"
$env:LLM_MODEL="deepseek-chat"
```

或复制 `.env.example` 为 `.env` 并填写：
```bash
cp .env.example .env
```

## 部署方式

### Windows 本地

```powershell
# 安装
.\scripts\install_windows.ps1

# 启动统一 A2A 网关
.\scripts\run_windows.ps1
```

### Linux / macOS 本地

```bash
bash scripts/install_linux.sh
bash scripts/run_linux.sh
```

### Docker（跨平台）

```bash
# 复制并编辑 .env
cp .env.example .env

# 构建并启动
docker-compose up --build -d

# 查看日志
docker-compose logs -f
```

## 项目结构

```
├── dev_agent_system/    # 核心包
│   ├── agents.py        # 6 业务 Agent + Memory
│   ├── orchestrator.py  # LangGraph StateGraph DAG 编排与迭代
│   ├── server.py        # 统一 FastAPI A2A 网关（6 个 Agent 合一）
│   ├── a2a_node.py      # 单个 A2A Agent 节点启动器
│   ├── a2a_client.py    # A2A 客户端（发现 + 发任务）
│   ├── main.py          # CLI 入口
│   ├── config.py        # 统一配置加载（.env + YAML）
│   ├── schemas.py        # Pydantic 模型与 GraphState TypedDict
│   ├── llm.py           # LLM 客户端（Provider 调度，含流式输出）
│   ├── llm_providers.py # OpenAI/DeepSeek、Ollama、Mock Provider 实现
│   ├── templates.py      # 多语言项目模板（Python/Java/Go/TypeScript）
│   ├── router.py        # 模型路由
│   ├── mcp.py           # MCP 工具沙箱
│   ├── memory.py        # 三层记忆
│   ├── security.py         # 基础安全扫描、路径校验、敏感信息脱敏
│   ├── security_scanner.py # Secret/依赖漏洞扫描、容器沙箱
│   ├── skills.py          # 最小版 Skill 管理器（安装/卸载/调用/注册 MCP）
│   ├── metrics.py       # Prometheus 格式指标收集
│   ├── telemetry.py      # OpenTelemetry 风格 Span 与结构化日志
│   ├── tracker.py        # 工作流全局状态追踪
│   ├── tui.py            # rich 终端进度面板
│   ├── dashboard.py      # Web Dashboard 页面
│   ├── devops.py        # DevOps 真实闭环（build/run/health/cleanup）
│   ├── eval.py          # 评估与指标体系
│   ├── checkpoint.py    # 状态持久化与断点续跑
│   ├── prompts.yaml     # System Prompt 版本化
│   └── agent_cards.json # A2A Agent Card 汇总
├── config/
│   ├── model.yaml       # 模型版本锁定（无 latest）
│   └── mcp.yaml         # MCP Server 配置
├── tests/
│   ├── eval_dataset.json    # 18 条评估数据集
│   ├── test_flow.py         # 集成测试
│   ├── test_checkpoint.py   # checkpoint 持久化测试
│   ├── test_memory.py       # 记忆后端测试
│   ├── test_eval.py         # 评估指标测试
│   ├── test_devops.py       # DevOps 闭环测试
│   ├── test_security.py     # 安全与沙箱测试
│   ├── test_metrics.py      # 指标收集测试
│   ├── test_telemetry.py     # 链路追踪测试
│   ├── test_server.py        # Server 端点测试
│   ├── test_dashboard.py    # Dashboard 端点测试
│   ├── test_tui.py          # TUI 与 Tracker 测试
│   └── test_a2a.py          # A2A 协议测试
├── scripts/
│   ├── run_a2a_cluster.py     # 一键启动 6 个独立 A2A Agent
│   ├── install_windows.ps1    # Windows 安装脚本
│   ├── run_windows.ps1        # Windows 启动脚本
│   ├── install_linux.sh       # Linux 安装脚本
│   ├── run_linux.sh           # Linux 启动脚本
│   ├── bump-version.py        # 版本升级
│   ├── git-sop-check.sh       # Git SOP 检查
│   ├── release.sh             # 发布流程
│   ├── push_to_github.sh      # Linux/macOS 提交推送
│   └── push_to_github.ps1     # Windows 提交推送
├── .github/
│   └── workflows/
│       └── ci.yml             # GitHub Actions CI
├── pre-release-check.sh    # 预发布检查脚本
├── .env.example            # 环境变量模板
├── Dockerfile              # Docker 镜像
├── docker-compose.yml      # Docker Compose 编排
├── AGENTS.md               # 多 Agent 开发过程指导
├── ARCHITECTURE.md         # 架构图与核心数据流
├── CONTRIBUTE.md           # 代码规范与分支策略
├── RELEASE_NOTES.md        # 版本价值与升级影响说明
├── requirements.txt
├── CHANGELOG.md
└── README.md

├── docs/
│   ├── tools_spec.md       # 工具 JSON Schema
│   ├── prompt_templates.md # System Prompt 版本管理
│   └── usage_operations.md # 使用与运维手册
```

## 版本管理与发布

```bash
# 预发布检查
bash pre-release-check.sh

# Git SOP 检查
bash scripts/git-sop-check.sh

# 一键提交并推送到 GitHub（Linux/macOS/Git Bash）
bash scripts/push_to_github.sh "feat: 新增 xxx"

# 一键提交并推送到 GitHub（Windows PowerShell）
.\scripts\push_to_github.ps1 -Message "feat: 新增 xxx"

# 升级版本（patch / minor / major）
python scripts/bump-version.py patch

# 完整发布流程
bash scripts/release.sh patch
```

分支策略：`main` / `dev` / `feature/*` / `hotfix/*`，详见 `AGENTS.md`。

GitHub Actions：`.github/workflows/ci.yml` 在 push/PR 时自动运行 pytest、语法检查与 `model.yaml` 无 `latest` 校验。

## 设计要点

- **无回流边**：Reviewer 未通过时，由 Scheduler 发起新一轮，避免 DAG 循环依赖。
- **最大迭代**：默认 10 轮，超过后强制结束。
- **幂等**：所有请求携带 `request_id`，A2A 服务端去重。
- **安全**：LLM 生成代码不直接在宿主机执行；`security.py` 提供 `SafetyScanner`（命令/代码危险模式扫描）、`PathValidator`（路径越界校验）、`SecretRedactor`（API Key/手机号/邮箱/密码脱敏）；`security_scanner.py` 提供 Secret 扫描、依赖漏洞扫描与 `ContainerSandbox` 容器隔离。
- **产物落地**：Coder 写入 `main.py`、Tester 写入 `test_*.py` 并执行 `pytest`、Docs 写入 `README.md/API.md`、Reviewer 写入 `review_report.json`，全部落在 `workspace/<request_id>/` 下。
- **模型路由**：`config/model.yaml` 配置各 Agent 的模型版本与温度；`router.py` 支持按提示长度自适应切换大模型。
- **流式输出**：`POST /orchestrate/stream` 与 `POST /{agent}/stream` 返回 `text/event-stream` 实时推送进度。
- **记忆后端**：支持 Redis / ChromaDB / SQLite 三档记忆，通过 `MEMORY_BACKEND` 切换；自动降级确保可用性。
- **上下文压缩**：超过 `CONTEXT_COMPRESS_THRESHOLD` 时自动截断中间文本，保护 LLM 上下文窗口。
- **状态持久化**：LangGraph checkpoint 自动写入 SQLite，支持断点续跑与 `POST /tasks/{request_id}/resume`。
- **评估指标**：`eval.py` 跑通 `tests/eval_dataset.json` benchmark（18 条任务，含 Java/Go/TypeScript），产出 Review 通过率、文件召回率、覆盖率、迭代次数与耗时等多维报告，支持 `--update-baseline` 与自动回归检测。
- **DevOps 闭环**：`devops.py` 支持 build → run → health → cleanup 真实 Docker 闭环，默认 dry-run 保障安全。
- **角色扩展**：默认 6 个核心 Agent（Architect/Coder/Tester/Reviewer/Docs/DevOps），可通过 `Orchestrator` 的 `enable_product_manager`、`enable_security`、`enable_dba` 扩展为产品经理、安全审查、数据库架构等角色。
- **可观测性**：`metrics.py` + `telemetry.py` 提供 Prometheus 格式指标、OpenTelemetry 风格 Span 与结构化日志；`server.py` 暴露 `/metrics` 与 `/health` 端点；`tui.py` 与 `dashboard.py` 提供终端/Web 实时进度面板。
- **Skill 系统**：`skills.py` 提供最小版 Skill 管理器，支持安装/卸载/调用，并可将 Skill 注册为 MCP 工具。

## 预发布检查

```bash
bash pre-release-check.sh
```

检查 pytest、model.yaml 无 `latest`、CHANGELOG 已更新、ChromaDB 备份。
