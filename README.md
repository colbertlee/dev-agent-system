# 软件开发多 Agent 协作系统

基于 `框架一_软件开发多Agent系统.html` 实现的完整多 Agent 开发框架。

## 架构

- **6 个业务 Agent**：Architect、Coder、Tester、Reviewer、Docs、DevOps
- **3 个支撑组件**：Orchestrator、Memory、Scheduler（迭代控制）
- **编排**：LangGraph `StateGraph` DAG，`Architect → {Coder, Tester, Docs} → Reviewer`
- **通信**：A2A 协议，`/.well-known/agent.json` + `/tasks`
- **工具**：MCP 风格工具沙箱（白名单+黑名单+路径限制+超时）
- **记忆**：三层记忆（短期/工作/长期），默认内存+SQLite 降级

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 运行完整工作流（MOCK 模式）
python -m dev_agent_system.main "开发一个支持 JWT 的用户登录模块"

# 启动统一 A2A 网关
python -m dev_agent_system.server --port 8000

# 启动 6 个独立 A2A Agent 服务
python scripts/run_a2a_cluster.py

# 或单独启动某个 Agent
python -m dev_agent_system.a2a_node --agent architect --port 8081

# 运行测试
pytest -q
```

## 配置真实 LLM

```bash
export LLM_API_KEY="your-key"
export LLM_BASE_URL="https://api.deepseek.com"
export LLM_MODEL="deepseek-chat"
```

Windows:
```powershell
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
│   ├── types.py         # Pydantic 模型
│   ├── llm.py           # LLM 客户端（含流式输出）
│   ├── router.py        # 模型路由
│   ├── mcp.py           # MCP 工具沙箱
│   ├── memory.py        # 三层记忆
│   ├── prompts.yaml     # System Prompt 版本化
│   └── agent_cards.json # A2A Agent Card 汇总
├── config/
│   ├── model.yaml       # 模型版本锁定（无 latest）
│   └── mcp.yaml         # MCP Server 配置
├── tests/
│   ├── eval_dataset.json  # 10 条评估数据集
│   └── test_flow.py       # 集成测试
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
├── requirements.txt
├── CHANGELOG.md
└── README.md
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
- **安全**：LLM 生成代码不直接在宿主机执行，沙箱白名单+超时。
- **产物落地**：Coder 写入 `main.py`、Tester 写入 `test_*.py` 并执行 `pytest`、Docs 写入 `README.md/API.md`、Reviewer 写入 `review_report.json`，全部落在 `workspace/<request_id>/` 下。
- **模型路由**：`config/model.yaml` 配置各 Agent 的模型版本与温度；`router.py` 支持按提示长度自适应切换大模型。
- **流式输出**：`POST /orchestrate/stream` 与 `POST /{agent}/stream` 返回 `text/event-stream` 实时推送进度。
- **记忆后端**：支持 Redis / ChromaDB / SQLite 三档记忆，通过 `MEMORY_BACKEND` 切换；自动降级确保可用性。
- **上下文压缩**：超过 `CONTEXT_COMPRESS_THRESHOLD` 时自动截断中间文本，保护 LLM 上下文窗口。

## 预发布检查

```bash
bash pre-release-check.sh
```

检查 pytest、model.yaml 无 `latest`、CHANGELOG 已更新、ChromaDB 备份。
