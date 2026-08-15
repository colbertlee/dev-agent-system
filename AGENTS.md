# AGENTS.md — 多 Agent 系统开发过程指导

本文件记录 `dev_agent_system` 的协作规则、状态图、Agent 扩展方式与版本管理要求，用于指导后续多 Agent 开发。

## 1. 系统目标

构建一个面向个人开发者的软件工程多 Agent 协作系统：

- 通过 A2A 协议让 Agent 互相发现与通信。
- 通过 MCP 工具沙箱让 Agent 安全地读写文件、执行命令。
- 通过 LangGraph DAG 编排复杂工作流，实现可追踪、可迭代、可并行的开发过程。

## 2. 角色与职责

| Agent | 职责 | 输入 | 输出 | 自治级别 |
|---|---|---|---|---|
| ProductManager | 需求澄清、PRD、用户故事、验收标准 | 用户自然语言需求 | `prd.md`、用户故事列表 | L2 |
| Architect | 需求分析、架构设计、技术选型 | 用户自然语言需求 / ProductManager PRD | 架构文档、API 契约、Mermaid 图 | L2 |
| DBA | 数据库 Schema 与迁移脚本 | Architect 架构设计 | `schema.sql`、迁移脚本 | L2 |
| Coder | 代码实现、自测 | Architect 输出 / DBA 设计 | 可运行代码、CoderReport JSON | L2 |
| Tester | 测试生成与执行 | Coder 输出、API 契约 | 测试报告、覆盖率 JSON | L3 |
| Reviewer | 独立审查代码、测试、文档 | 需求 + 中间产物 | 审查报告 JSON | L2 |
| Security | 独立安全审查 | 需求 + 代码 + 测试 + 架构 | `security_report.json` | L2 |
| Docs | 文档同步 | 架构 + 代码 | README、API 文档 | L3 |
| DevOps | CI/CD、部署脚本 | 代码 | Dockerfile、CI 配置、部署状态 | L2 |

> **状态传递原则**：Agent 运行后，`GraphState` 中只保留 `summary_budget` 控制的关键信息摘要（JSON 格式）；完整产物写入 `workspace/` 文件，原始 LLM 输出不进入下游 prompt/checkpoint。

支撑组件：

- **Orchestrator**：LangGraph StateGraph 编排器，负责任务分解与状态流转。
- **Memory**：三层记忆（短期/工作/长期），默认内存+SQLite 降级。
- **Scheduler**：通过 LangGraph 条件边控制迭代，最多 10 轮。

## 3. 状态图（DAG）

```
start
 │
 ▼
product_manager_node  (可选 enable_product_manager)
 │
 ▼
architect_node
 │
 ▼
dba_node  (可选 enable_dba)
 │
 ▼
coder_node
 │
 ▼
tester_docs_node (Tester / Docs 并行)
 │
 ▼
reviewer_node
 │
 ▼
security_node  (可选 enable_security)
 │
 ▼
should_continue? （条件边）
 ┌──────────┴──────────┐
 ▼                     ▼
 end (completed)      architect_node (新一轮，最多 max_iterations 轮)
```

设计原则：

- 无回流边：Reviewer 不直接修改 Coder 输出；未通过时由 Scheduler 发起新一轮。
- 顺序依赖：Coder 必须在 Tester 之前（Tester 需要读取代码文件生成测试）。
- 并行节点：Tester 与 Docs 在 Coder 完成后 `asyncio.gather` 并行执行。
- 状态集中：所有节点共享 `GraphState`，节点返回更新后的部分字段。
- 产物落地：每个 Agent 通过 `ToolSandbox` 把产物写入以 `request_id` 隔离的 `workspace/`，最终由 Reviewer 写入 `review_report.json`。

## 4. 如何新增一个 Agent

1. 在 `dev_agent_system/agents.py` 中继承 `BaseAgent` 实现新 Agent。
2. 在 `dev_agent_system/prompts.yaml` 中添加该 Agent 的 system prompt，要求输出合法 JSON。
3. 可选：在 `BaseAgent.__init__` 中为该 Agent 设置 `report_schema`（Pydantic 模型）与 `summary_budget`（摘要长度上限）。
4. 在 `dev_agent_system/agent_cards.json` 中添加 A2A Agent Card。
5. 在 `dev_agent_system/orchestrator.py` 的 `__init__` 中注册 Agent 实例。
6. 如果该 Agent 需要在工作流中显式执行，在 `orchestrator.py` 的 `StateGraph` 中添加节点与边。
7. 在 `config/model.yaml` 中锁定该 Agent 使用的模型版本。
8. 在 `tests/` 中补充对该 Agent 输入输出格式与摘要行为的单元测试。
9. 更新 `README.md`、对应 `docs/` 文档与 `CHANGELOG.md`。

## 5. 配置、版本管理与 Git 分支 SOP

### 5.1 需要版本化的资产

| 资产 | 位置 | 变更时记录 |
|---|---|---|
| 代码 | `dev_agent_system/` | 常规 Git commit |
| System Prompt | `dev_agent_system/prompts.yaml` | 单独 commit，说明原因 |
| Agent Card | `dev_agent_system/agent_cards.json` | Capability 变更时更新 |
| 模型版本 | `config/model.yaml` | 锁定到具体版本号，禁止 `latest` |
| MCP 配置 | `config/mcp.yaml` | 工具增删时更新 |
| 评估数据集 | `tests/eval_dataset.json` | 当前 18 条，新增用例时更新 |
| 运行环境 | `requirements.txt` | 锁定依赖版本 |
| 生成器规范 | `docs/agent_generator_spec.md` / `.html` | Agent/Prompt/源码约定变更时更新 |
| 架构回顾 | `docs/agent_framework_retrospective.md` / `.html` | 架构四要素映射变化时更新 |
| 文档生成器 | `scripts/generate_docs.py` | HTML 生成逻辑或样式变化时更新 |

### 5.2 语义化版本规范

- **MAJOR**：Agent 角色增删、A2A 协议不兼容变更
- **MINOR**：新增功能/工具、Prompt 重大优化
- **PATCH**：Bug 修复、Prompt 微调、依赖更新

### 5.3 Git 分支策略

采用 Trunk-Based 简化版：

| 分支 | 用途 | 规则 |
|---|---|---|
| `main` | 生产就绪版本 | 每次合并 = 一次 Release，必须通过全部测试 |
| `dev` | 日常开发分支 | 功能完成后 merge 到 main |
| `feature/xxx` | 新功能/新 Agent 开发 | 从 dev 切出，合并回 dev |
| `hotfix/xxx` | 紧急修复 | 从 main 切出，修复后 merge 到 main 和 dev |

### 5.4 发布流程脚本

```bash
# 1. 预发布检查
bash pre-release-check.sh

# 2. Git SOP 检查
bash scripts/git-sop-check.sh

# 3. 提交并推送到 GitHub
bash scripts/push_to_github.sh "feat: 新增 xxx"
# Windows 下使用：.\scripts\push_to_github.ps1 -Message "feat: 新增 xxx"

# 4. 升级版本（patch / minor / major）
python scripts/bump-version.py patch

# 5. 完整发布流程（先检查、后升级版本）
bash scripts/release.sh patch
```

`scripts/bump-version.py` 会自动更新 `dev_agent_system/__init__.py` 与 `CHANGELOG.md`，请在生成后手动填充 CHANGELOG 内容，再提交并打 tag。

`push_to_github.sh` / `push_to_github.ps1` 会自动执行 pytest、检查分支命名、提交、推送，并在 `feature/*` 或 `hotfix/*` 分支尝试使用 `gh` 创建 Pull Request。

## 6. 测试策略

| 类型 | 范围 | 命令 |
|---|---|---|
| 单元测试 | Agent 输入输出、沙箱规则、幂等 | `python -m pytest tests -q` |
| 集成测试 | 完整 DAG 流程 | `python -m dev_agent_system.main "需求"` |
| 评估数据集 | 18 条真实需求（含 Java/Go/TypeScript） | 查看 `tests/eval_dataset.json` |
| 预发布检查 | pytest + model.yaml + CHANGELOG + ChromaDB 备份 | `bash pre-release-check.sh` |

Mock LLM：测试通过 monkeypatch `LLMClient.chat` 实现，无需真实 API Key。

## 7. 安全规则

1. LLM 生成的代码不直接在宿主机执行，必须经过 `ToolSandbox`。
2. 文件操作限制在 `workspace/` 目录内，禁止目录穿越。
3. 终端命令白名单：`python`, `pytest`, `git`, `ls`, `cat`, `echo`, `docker build`，以及 Java/Go/TS 工具链 `mvn`, `gradle`, `javac`, `java`, `go`, `npm`, `npx`, `node`。
4. 黑名单拦截：`rm -rf`, `curl | sh`, `wget -O-` 等危险模式。
5. 命令执行默认超时 5 秒。
6. 调用 LLM 前自动脱敏 API Key、手机号、密码。
7. 涉及部署、资金、删除、发布的操作必须 Human-in-the-Loop（L2 以下）。
   - DevOps 真实部署（`DEVOPS_DRY_RUN=false`）前会进入 `awaiting_approval` 状态。
   - 管理员可通过 `POST /tasks/{request_id}/approve` 批准，或 `POST /tasks/{request_id}/reject` 拒绝。
   - 审批状态由 `HumanApprovalStore` 持久化到 SQLite，路径可通过 `APPROVAL_DB` 环境变量配置。
8. 进阶安全：`security_scanner.py` 提供 Secret 扫描、依赖漏洞扫描与 `ContainerSandbox` 容器隔离；CI 通过 `.github/workflows/security.yml` 定时扫描。

## 8. 常用命令

```bash
# 安装依赖
pip install -r requirements.txt

# 运行完整工作流
python -m dev_agent_system.main "你的需求"

# 启动统一 A2A 网关
python -m dev_agent_system.server --port 8000

# 启动 6 个独立 A2A Agent 服务
python scripts/run_a2a_cluster.py

# 或单独启动某个 Agent
python -m dev_agent_system.a2a_node --agent architect --port 8081

# 运行测试
python -m pytest tests -q

# 预发布检查
bash pre-release-check.sh
```

GitHub Actions `.github/workflows/ci.yml` 会在 `push` / `pull_request` 时自动运行 pytest、语法检查、并校验 `config/model.yaml` 不含 `latest`。

### 跨平台部署

Windows:
```powershell
.\scripts\install_windows.ps1
.\scripts\run_windows.ps1
```

Linux / macOS:
```bash
bash scripts/install_linux.sh
bash scripts/run_linux.sh
```

Docker:
```bash
cp .env.example .env
# 编辑 .env 填写 LLM_API_KEY
docker-compose up --build -d
```

配置由 `dev_agent_system/config.py` 统一管理：`.env` 文件 > `config/model.yaml` > 环境变量 > 默认值。

## 9. 扩展方向

- 接入真实 Redis + ChromaDB 替换内存降级实现。
- 接入 `langgraph.checkpoint` 实现状态持久化与重放。
- 增加更多垂直角色，如 Performance Agent、Cost Agent、Compliance Agent。
- 对接 CI/CD 真实环境（GitHub Actions、Docker Registry）。
- 接入真实 LLM 跑分，利用 `RegressionChecker` 做持续回归检测。
- 进一步扩展语言模板（如 Rust / C# / Kotlin）。
- 完善 Skill 系统：增加 Skill 签名校验、沙箱执行、版本管理与 Skill 市场协议；支持 Agent 间远程 Skill 调用。

## 10. 生成器规范

要从零复现或生成等价的多 Agent 系统，请参阅：

- [docs/agent_generator_spec.md](docs/agent_generator_spec.md) —— 可复现当前系统的完整生成规范（4-Block Framework + 每个 Agent 的 Prompting 模板 + 源码附录）
- [docs/agent_generator_spec.html](docs/agent_generator_spec.html) —— 带目录、响应式、暗色模式的离线 HTML 版本
