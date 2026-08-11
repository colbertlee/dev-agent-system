# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-08-11

### Added

- Agent 产物落地：
  - `CoderAgent` 解析 LLM 输出的代码块并写入 `workspace/<request_id>/`。
  - `TesterAgent` 读取代码文件、生成 `test_*.py`、调用 `pytest -q` 并解析测试报告。
  - `DocsAgent` 生成 `docs/README.md` 与 `docs/API.md`。
  - `ReviewerAgent` 解析 JSON 审查报告并写入 `review_report.json`。
  - `ArchitectAgent` 解析 JSON 架构设计并写入 `design.json`。
- `BaseAgent` 增加 `postprocess` 生命周期钩子，支持异步 MCP 工具调用。
- `MCPToolRegistry.ainvoke` 异步工具调用接口。
- `ToolSandbox.run_command` 支持 `base_dir` 参数，允许在不同 workspace 中运行命令。
- `GraphState` 增加 `workspace` 字段，Orchestrator 为每个请求分配独立工作目录。
- `test_flow.py` 集成测试现在会验证 `main.py`、`test_main.py`、`review_report.json` 是否真实写入。

### Changed

- LangGraph DAG 调整为：`Architect → Coder → {Tester, Docs} 并行 → Reviewer`。
- `BaseAgent.run` 改为 `async def`，统一支持异步 postprocess。
- `a2a_node.py` 与 `server.py` 的 Agent 任务端点统一 `await agent.run(...)`。
- `orchestrator._should_continue` 与 `_reviewer_node` 优先读取 Reviewer 的 `passed` 布尔字段。

### Fixed

- 修复并行节点中 Tester 无法读取 Coder 产物的问题（先执行 Coder，再并行 Tester/Docs）。

### Security

- 文件写入仍受 `ToolSandbox` 白名单/黑名单/路径限制约束，无法越界。

### Model Changes

- 无

## [0.2.0] - 2026-08-09

首个可运行、可部署、可验证的多 Agent 软件开发系统版本。

### Added

- 完整多 Agent 软件开发系统骨架（Architect / Coder / Tester / Reviewer / Docs / DevOps）。
- LangGraph `StateGraph` 编排器 `dev_agent_system/orchestrator.py`：支持 `Architect → Coder → {Tester, Docs} → Reviewer` 流程与条件迭代。
- `AGENTS.md` 多 Agent 开发过程指导文档，含角色职责、DAG、Agent 扩展、版本管理、Git 分支 SOP、测试与安全规则。
- `GraphState` TypedDict 状态类型 `dev_agent_system/types.py`。
- `langgraph==0.2.0` 与 `langchain-core==0.2.27` 依赖锁定。
- 统一 FastAPI A2A 网关 `dev_agent_system/server.py`：暴露 `/.well-known/agent.json`、`/tasks`、`/orchestrate`、`/rpc`、`/health` 与 SSE 流式端点。
- 独立 A2A Agent 节点 `dev_agent_system/a2a_node.py`：支持 `python -m dev_agent_system.a2a_node --agent architect --port 8081` 启动单个服务。
- A2A 客户端 `dev_agent_system/a2a_client.py`：支持 Agent Card 发现与任务发送。
- `scripts/run_a2a_cluster.py`：一键启动 6 个独立 A2A Agent 服务。
- MCP 工具沙箱 `dev_agent_system/mcp.py`：白名单、黑名单、路径限制、超时。
- Memory Agent `dev_agent_system/memory.py`：三层记忆（短期/工作/长期）内存+SQLite 降级实现。
- LLM 客户端 `dev_agent_system/llm.py`：OpenAI 兼容 + MOCK 降级 + PII 脱敏。
- 统一配置加载 `dev_agent_system/config.py`：支持 `.env` 环境变量 + `config/*.yaml` 配置，Agent 自动读取 `config/model.yaml` 中的模型版本。
- Prompt 版本化 `dev_agent_system/prompts.yaml` 与 Agent Card `dev_agent_system/agent_cards.json`。
- Docker 部署支持 `Dockerfile` + `docker-compose.yml` + `.env.example`。
- Windows 与 Linux 本地安装/运行脚本 `scripts/install_windows.ps1`、`scripts/run_windows.ps1`、`scripts/install_linux.sh`、`scripts/run_linux.sh`。
- GitHub 一键推送脚本 `scripts/push_to_github.sh` 与 `scripts/push_to_github.ps1`（自动 pytest + 分支检查 + 推送 + PR）。
- GitHub Actions CI `.github/workflows/ci.yml`（pytest、语法检查、model.yaml 无 `latest` 校验）。
- 版本管理脚本 `scripts/bump-version.py`、`scripts/git-sop-check.sh`、`scripts/release.sh`。
- 模型版本锁定 `config/model.yaml`（禁止 latest）与 MCP 配置 `config/mcp.yaml`。
- 10 条评估数据集 `tests/eval_dataset.json`。
- 预发布检查脚本 `pre-release-check.sh`。
- 单元与集成测试 `tests/test_flow.py`、`tests/test_a2a.py`。

### Fixed

- `dev_agent_system/server.py`：将 Python 3.10 的 `str | None` 语法替换为 `Optional[str]`，以兼容 Python 3.9。
- `dev_agent_system/server.py`：修复 Agent 实例作为默认参数导致 FastAPI 深拷贝失败的问题，改为闭包方式注册路由。
- `dev_agent_system/orchestrator.py`：为 LangGraph 设置 `recursion_limit`，避免 `max_iterations` 较大时触发递归限制。
- `dev_agent_system/types.py`：为 `Task` 增加 `max_iterations` 字段，支持 `/orchestrate` 和 `/rpc` 调整最大迭代次数。

### Model Changes

- Architect: gpt-4-0613
- Coder: gpt-4-turbo-2024-04-09
- Reviewer: gpt-4o-2024-08-06
- Tester: gpt-4-0613
- Docs: gpt-3.5-turbo-0125
- DevOps: gpt-4-0613

## [0.1.0] - 2026-08-09

### Added

- 项目初始骨架与目录结构。
