# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.21.0] - 2026-08-14

### Added

- 结构化 JSON 输出与 Pydantic 校验：
  - `LLMClient` / `LLMProvider` 增加 `json_mode` 参数，OpenAI/DeepSeek 调用时使用 `response_format={"type": "json_object"}`，Ollama 调用时使用 `format="json"`。
  - `BaseAgent` 新增 `_parse_json_output`，支持解析纯 JSON、Markdown 内嵌 JSON 与 `dict` 校验，失败时仍兼容历史 Markdown 代码块。
  - `schemas.py` 新增 `AgentOutput`、`AgentFile`、`DesignOutput`、`DBAReport`、`PRDOutput` 等 Pydantic 模型。
  - `CoderAgent`、`TesterAgent`、`DBAAgent`、`ArchitectAgent`、`ReviewerAgent`、`SecurityAgent`、`ProductManagerAgent` 都配置了对应的 `report_schema`，输出现在会经过 Pydantic 校验。
- Human-in-the-Loop 人工审批：
  - 新增 `dev_agent_system/human_approval.py`：`HumanApprovalStore` 基于 SQLite 持久化审批状态（`pending`/`approved`/`rejected`）。
  - `Orchestrator._devops_node` 在真实部署（`DEVOPS_DRY_RUN=false`）前检查审批状态；未审批时返回 `awaiting_approval` 并暂停。
  - `Orchestrator` 新增 `approve_devops` 与 `get_approval_status` 方法。
  - `server.py` 新增 `/tasks/{request_id}/approval`、`/tasks/{request_id}/approve`、`/tasks/{request_id}/reject` 端点。

### Changed

- `prompts.yaml` 中 `coder`、`tester`、`dba` 的系统提示更新为“仅输出合法 JSON”的格式说明。
- `dev_agent_system/__init__.py` 版本号更新为 `0.21.0`。

### Fixed

- 修复“过分依赖自然语言提示、缺少代码层约束”的雷区：通过 `json_mode` + Pydantic 校验，强制或校验 Agent 结构化输出。
- 修复“高危操作缺少人类确认”的雷区：DevOps 真实部署前必须通过审批 API 人工确认。

### Security

- `HumanApprovalStore` 将审批记录持久化到本地 SQLite，避免仅依赖内存导致的状态丢失。

### Model Changes

- 无。

## [0.20.1] - 2026-08-12

### Added

- 新增可复现当前多 Agent 系统的生成器规范：
  - `docs/agent_generator_spec.md`：逐 Agent 的 4-Block Framework 映射、Prompting Specification Template（Role/Goal / Inputs / SOP / Constraints / Exception）、I/O Schema、异常处理与产物约定。
  - `docs/agent_generator_spec.html`：响应式布局、侧边目录、锚点导航、代码块与表格样式、暗色模式支持。
  - 附录包含完整 `prompts.yaml`、`agent_cards.json`、`schemas.py`、`templates.py`、`mcp.py`、`security.py`、`memory.py`、`llm.py`、`llm_providers.py`、配置 YAML 与模块清单。
- 在 `README.md` 与 `AGENTS.md` 中增加 `agent_generator_spec` 导航链接。

### Changed

- `dev_agent_system/__init__.py` 版本号更新为 `0.20.1`。

### Model Changes

- 无。

## [0.20.0] - 2026-08-11

### Added

- Agent 架构四要素与 Prompting 规范反推文档：
  - 新增 `docs/agent_framework_retrospective.md`，系统梳理 4-Block Framework（角色/安全、上下文/IO、工具/能力、工作流/异常）在当前 `dev_agent_system` 中的映射。
  - 新增 `docs/agent_framework_retrospective.html`，提供响应式布局、目录导航、代码块与表格样式、暗色模式支持的离线 HTML 版本。

### Changed

- 无代码功能变更。

### Model Changes

- 无。

## [0.19.0] - 2026-08-11

### Added

- Skill 市场协议与 Agent 自动发现：
  - `SkillManager.find(query)`：按 id/name/description 关键词匹配 Skill。
  - `BaseAgent` 初始化时自动将已安装 Skill 注册到 `MCPToolRegistry`，每个 Agent 都能发现调用。
  - `server.py` 新增 `/skills`、`/skills/{skill_id}`、`/skills/{skill_id}/invoke` 端点，形成最小 Skill 市场协议。
  - 新增 `tests/test_server_skills.py`：覆盖 Skill 市场端点的 list/get/invoke。

### Changed

- `README.md` 与 `AGENTS.md` 更新 Skill 市场协议说明。

### Model Changes

- 无。

## [0.18.0] - 2026-08-11

### Added

- 最小版 Skill 管理系统：
  - 新增 `dev_agent_system/skills.py`：
    - `Skill` 数据类、`SkillStore` 本地仓库、`SkillManager` 管理器。
    - 支持从本地目录或字典安装 Skill，自动生成 `SKILL.md` + `skill.py` 骨架。
    - 支持卸载、列出、调用（`invoke`）与向 `MCPToolRegistry` 注册为 MCP 工具。
  - `config.py` 增加 `skills_dir()` 与 `skills_enabled()` 配置。
  - 新增 `tests/test_skills.py`，覆盖安装、调用、卸载、本地路径安装与 MCP 注册。

### Changed

- `README.md` 与 `AGENTS.md` 增加 Skill 使用说明。

### Model Changes

- 无。

## [0.17.0] - 2026-08-11

### Added

- 安全加固进阶（路线图第 6 条）：
  - 新增 `dev_agent_system/security_scanner.py`：
    - `SecretScanner`：基于正则扫描工作区文件中的 API Key、Token、密码、私钥等 Secret。
    - `DependencyScanner`：调用 `safety` 或 `pip-audit` 对 `requirements.txt` 做依赖漏洞扫描。
    - `ContainerSandbox`：把命令包装成 `docker run --rm --network none ...` 容器执行，增强隔离。
    - `SecurityPipeline`：组合 Secret 扫描、依赖扫描与命令执行，输出 `safe` 判定。
  - 新增 `.github/workflows/security.yml`：TruffleHog Secret 扫描、Safety 依赖漏洞扫描、Bandit 静态代码安全扫描，并定时每周运行。
  - 新增 `tests/test_security_scanner.py`。

### Changed

- `README.md` 与 `AGENTS.md` 增加安全扫描使用说明与 CI 说明。

### Model Changes

- 无。

## [0.16.0] - 2026-08-11

### Added

- 多语言支持（路线图第 5 条）：
  - 新增 `dev_agent_system/templates.py`：Python、Java、Go、TypeScript 语言模板，包含文件扩展名、主文件/测试文件命名、构建/测试命令、包管理文件与默认骨架。
  - `GraphState` / `WorkflowState` / `Task` 增加 `language` 字段，支持按任务指定目标语言。
  - `Orchestrator.run` / `run_stream` / `resume` 与 `EvaluationRunner` 透传 `language`。
  - `ArchitectAgent`、`CoderAgent`、`TesterAgent` 根据 `language` 动态生成对应语言产物与测试命令。
  - `ToolSandbox` 命令白名单扩展 `mvn`、`gradle`、`javac`、`java`、`go`、`npm`、`npx`、`node`。
  - `main.py` 与 `tui.py` 增加 `--language` 参数。
  - `tests/eval_dataset.json` 增加 Java / Go / TypeScript 多语言 benchmark 用例。
  - 新增 `tests/test_templates.py`、`tests/test_multilang.py`。

### Changed

- `tests/test_flow.py` 的 `_mock_chat` 改用更精确的系统 prompt 关键词匹配，避免 Coder/Tester 子串误匹配。
- `README.md` 与 `AGENTS.md` 更新多语言使用说明。

### Model Changes

- `GraphState`、`WorkflowState`、`Task` 新增 `language: Optional[str]`。

## [0.15.0] - 2026-08-11

### Added

- 评估与 benchmark 调优（路线图第 4 条）：
  - `tests/eval_dataset.json` 从 10 条扩充到 15 条，覆盖 CSV 处理、LRU 缓存、邮件服务、限流器、配置中心等场景。
  - `dev_agent_system/eval.py` 新增 `RegressionChecker`：支持 `--baseline`、`--update-baseline`、`--tolerance`，自动检测指标回退。
  - `python -m dev_agent_system.eval` 默认与 `output_dir/eval_baseline.json` 对比，回退超过阈值时退出码 1。
  - 新增 `tests/test_eval.py`：覆盖 `MetricCalculator`、文件召回、覆盖率提取、回归检测与 `EvaluationRunner` mock 端到端。

### Changed

- `README.md` 更新 eval 使用说明，增加 `--update-baseline` 与回归检测示例。

### Model Changes

- 无。

## [0.14.0] - 2026-08-11

### Added

- CLI / UI 增强（路线图第 3 条）：
  - 新增 `dev_agent_system/tracker.py`：全局工作流状态追踪器，支持 `start`/`update`/`finish`/`list`/`snapshot`。
  - `Orchestrator` 集成 `WorkflowTracker`，实时记录当前 Agent、迭代、状态与产物。
  - 新增 `dev_agent_system/tui.py`：基于 `rich` 的终端进度面板，展示 Agent 执行状态、工作流指标与最近事件；支持 `python -m dev_agent_system.tui "需求"`。
  - 新增 `dev_agent_system/dashboard.py`：Web Dashboard HTML 模板与数据聚合。
  - `server.py` 新增 `/dashboard`、`/api/status`、`/api/status/{request_id}` 端点。
  - 新增 `tests/test_dashboard.py`、`tests/test_tui.py`；`requirements.txt` 增加 `rich==13.9.4`。

### Changed

- `README.md` 增加 TUI 与 Dashboard 使用说明。

### Model Changes

- 无。

## [0.13.0] - 2026-08-11

### Added

- 真实 LLM 联调（路线图第 2 条）：
  - 新增 `dev_agent_system/llm_providers.py`：OpenAI/DeepSeek、Ollama 本地模型、Mock 的统一 Provider 抽象。
  - `LLMClient` 支持通过 `LLM_PROVIDER` 环境变量或模型名前缀 `ollama/<model>` 自动选择 Provider。
  - `OpenAIProvider` 兼容 OpenAI 风格 API，支持同步/异步流式输出。
  - `OllamaProvider` 通过 `/api/chat` 调用本地 Ollama，支持 stream 与非 stream 模式。
  - `MockProvider` 支持自定义返回与流式 token 拆分。
  - 新增 `LLM_TIMEOUT`、`LLM_MAX_RETRIES`、`OLLAMA_URL` 配置项。
  - 新增 `tests/test_llm.py`：覆盖 Provider 选择、Mock 流式、Ollama 请求体构建与 Chat 调用。

### Changed

- `dev_agent_system/llm.py` 重写为基于 Provider 的调度器，保留 `chat`/`stream`/`astream` 接口与 `MockLLM` 兼容类。
- `dev_agent_system/config.py` 增加 `llm_model()`、`llm_provider()`、`ollama_url()` 配置读取。
- `.env.example` 增加 `LLM_PROVIDER` 与 `OLLAMA_URL` 示例。
- `dev_agent_system/agents.py` 中 `CoderAgent` 的 MOCK 降级判断改为 `self.llm.is_mock()`。

### Model Changes

- 无。

## [0.12.0] - 2026-08-11

### Added

- 监控与可观测性（路线图第 9 条）：
  - 新增 `dev_agent_system/metrics.py`：轻量级内存指标收集器，支持 Counter / Gauge / Histogram，输出 Prometheus 文本协议。
  - 新增 `dev_agent_system/telemetry.py`：OpenTelemetry 风格 `Span` 与 `Telemetry`，支持嵌套链路、结构化 JSON 日志与事件记录。
  - `Orchestrator` 集成 Telemetry：自动记录 `orchestrator.run` / `orchestrator.resume` 跨度，以及每个 Agent 节点的执行跨度；自动写入 `agent_runs_total`、`workflow_total`、`review_decisions_total`、`workflow_iterations` 等指标。
  - `BaseAgent.run` 集成 LLM 调用追踪：记录 `llm_calls_total`、近似 prompt / output token 分布。
  - `server.py` 新增 `/metrics` 端点返回 Prometheus 格式指标；`/health` 返回当前 metrics 计数摘要。
  - 新增 `tests/test_metrics.py`、`tests/test_telemetry.py`、`tests/test_server.py`，覆盖指标渲染、Span 记录、事件计数与端点可用性。

### Changed

- 将 `dev_agent_system/types.py` 重命名为 `dev_agent_system/schemas.py`，彻底避免 `types` 名称遮蔽 Python 标准库；同步更新所有导入路径与文档。
- `metrics.py` 使用 `typing.Union` 替代 `|` 类型联合，兼容 Python 3.9 运行时。

### Fixed

- 修复 `types.py` 名称冲突导致的直接运行入口脚本失败。

### Model Changes

- 无。

## [0.11.0] - 2026-08-11

### Added

- 新增角色 Agent（路线图第 8 条）：
  - `ProductManagerAgent`：把用户需求拆分为 PRD、用户故事、验收标准，输出 `prd.md`。
  - `SecurityAgent`：独立安全审查，输出 `security_report.json`。
  - `DBAAgent`：根据架构设计产出数据库 Schema 与迁移 SQL。
  - `prompts.yaml` 新增 `product_manager`、`security`、`dba` 系统提示。
  - `agent_cards.json` 新增 3 个 A2A Agent Card。
  - `config/model.yaml` 锁定 3 个新 Agent 的模型版本。
  - `Orchestrator` 新增 `enable_product_manager`、`enable_security`、`enable_dba` 参数，可把工作流扩展为：
    - Product Manager → Architect → DBA → Coder → {Tester, Docs} → Reviewer → Security → (DevOps/End)。
  - `server.py` 的 `AGENTS` 注册中心加入新角色。
  - 新增 `tests/test_new_agents.py`，覆盖 3 个新 Agent 的 postprocess 与完整编排流程。

### Changed

- `GraphState` 增加 `product_manager`、`security`、`dba` 字段，支持新增节点状态传递。
- `ArchitectAgent.build_prompt` 在启用 Product Manager 时自动读取 PRD 作为输入。
- `CoderAgent.build_prompt` 在启用 DBA 时自动读取数据库设计作为输入。

### Fixed

- 无。

### Model Changes

- `config/model.yaml` 新增 `product_manager`、`security`、`dba` 模型配置。

## [0.10.0] - 2026-08-11

### Added

- 安全与沙箱加固：
  - 新增 `dev_agent_system/security.py`：`SafetyScanner`（命令/代码安全扫描）、`PathValidator`（路径越界校验）、`SecretRedactor`（敏感信息脱敏）。
  - `ToolSandbox` 集成 `SafetyScanner` 与 `PathValidator`，命令执行前扫描危险模式，文件读写前校验工作目录边界。
  - `BaseAgent.run` 在 LLM 调用前后通过 `SecretRedactor` 脱敏，防止 API Key、手机号、邮箱、密码进入记忆或返回结果。
  - `CoderAgent.postprocess` 对生成的每段代码调用 `SafetyScanner.scan_code`，将可疑模式（eval/exec/subprocess 等）作为 `security_issues` 上报。
  - `config.py` 新增 `safety_block_dangerous_commands()`、`safety_redact_secrets()`、`safety_code_scan()`；`.env.example` 同步补充。
  - 新增 `tests/test_security.py`，覆盖危险命令拦截、路径穿越、敏感信息脱敏、代码扫描与 ToolSandbox 集成。

### Changed

- `ToolSandbox` 路径校验统一收敛到 `PathValidator.resolve`，错误信息更明确。
- `Settings.sanitize` 复用 `SecretRedactor.redact`，避免规则重复。

### Fixed

- 无。

### Model Changes

- 无。

## [0.9.0] - 2026-08-11

### Added

- DevOps 真实闭环：
  - 新增 `dev_agent_system/devops.py`：`DevOpsRunner` 实现 build → run → health → cleanup 闭环。
  - 默认 `DEVOPS_DRY_RUN=true`，仅生成部署报告；关闭后可真实执行 `docker build/run`。
  - `Orchestrator` 在 `enable_devops=True` 时调用 `DevOpsRunner`，将部署结果写入 `state["devops"]`。
  - `config.py` 新增 `devops_dry_run()` 与 `devops_timeout()`；`.env.example` 同步补充。
  - 新增 `tests/test_devops.py`，覆盖镜像名清洗、dry-run 部署、Orchestrator 集成。

### Changed

- `Orchestrator.__init__` 新增 `devops_runner` 注入参数，便于测试与扩展。

### Fixed

- 无。

### Model Changes

- 无。

## [0.8.0] - 2026-08-11

### Added

- 评估与指标体系：
  - 新增 `dev_agent_system/eval.py`：`EvaluationRunner` + `MetricCalculator`，跑通 `tests/eval_dataset.json` benchmark。
  - 支持指标：Reviewer 通过率、期望文件召回率、测试覆盖率（含 `min_test_coverage` 达标判定）、平均迭代次数、平均耗时。
  - 输出 JSON 评估报告与 Markdown 摘要到 `EVAL_OUTPUT_DIR`（默认 `./eval_results`）。
  - CLI 入口：`python -m dev_agent_system.eval --dataset tests/eval_dataset.json --max-iter 3`。
  - 新增 `tests/test_eval.py` 覆盖 MetricCalculator 与 EvaluationRunner 的指标计算、异常处理。
- `config.py` 新增 `eval_output_dir()` 与 `eval_max_workers()`；`.env.example` 补充 `EVAL_OUTPUT_DIR` / `EVAL_MAX_WORKERS`。

### Changed

- 无破坏性变更。

### Fixed

- 无。

### Model Changes

- 无。

## [0.7.0] - 2026-08-11

### Added

- 状态持久化与断点续跑：
  - 新增 `dev_agent_system/checkpoint.py`：自定义 `SQLiteCheckpointSaver`，基于 `langgraph.checkpoint.base.BaseCheckpointSaver` 实现。
  - Orchestrator 编译 LangGraph 时传入 `checkpointer`，以 `request_id` 作为 `thread_id` 自动持久化每步状态。
  - 新增 `Orchestrator.resume(request_id)` 方法，支持从最近 checkpoint 恢复并继续执行。
  - 新增 `GET /tasks/{request_id}/checkpoints` 与 `POST /tasks/{request_id}/resume` 端点。
  - 新增 `Settings.checkpoint_db()` 与 `Settings.checkpoint_enabled()` 配置项，`.env.example` 补充 `CHECKPOINT_ENABLED` / `CHECKPOINT_DB`。
  - 新增 `tests/test_checkpoint.py` 覆盖 checkpoint 读写、writes 持久化、Orchestrator 断点续跑。

### Changed

- `Orchestrator.run` 与 `run_stream` 使用 `configurable.thread_id` 作为运行配置，触发 LangGraph checkpoint。

### Fixed

- 无

### Security

- SQLite checkpoint 数据库默认写入 `memory_store/`（已在 `.gitignore` 中忽略）。

### Model Changes

- 无

## [0.6.0] - 2026-08-11

### Added

- 文档生态：
  - 新增 `ARCHITECTURE.md`：系统架构图、核心数据流、模块依赖、部署形态。
  - 新增 `CONTRIBUTE.md`：代码规范、Conventional Commits、分支策略、PR checklist。
  - 新增 `RELEASE_NOTES.md`：版本价值、影响矩阵、升级建议。
  - 新增 `docs/tools_spec.md`：MCP 工具 JSON Schema、白名单、错误码。
  - 新增 `docs/prompt_templates.md`：System Prompt 版本管理、输出格式约定。
  - 新增 `docs/usage_operations.md`：安装、部署、监控、备份、故障排查。
- `README.md` 新增文档导航与项目结构补充。
- `.env.example` 补充 `MEMORY_BACKEND`、`REDIS_URL`、`CONTEXT_COMPRESS_THRESHOLD`、`CONTEXT_WINDOW_LIMIT`。

### Changed

- 无

### Fixed

- 无

### Security

- 无

### Model Changes

- 无

## [0.5.0] - 2026-08-11

### Added

- 记忆后端可插拔：
  - 新增 `MemoryBackend` 协议、`SQLiteMemoryBackend`、`RedisMemoryBackend`、`ChromaMemoryBackend`。
  - 通过 `MEMORY_BACKEND` 环境变量选择 `sqlite` / `redis` / `chroma`，未配置或依赖缺失时自动降级到 SQLite。
- `ContextCompressor` 上下文压缩：超过 `CONTEXT_COMPRESS_THRESHOLD` 字符时保留头部/尾部，避免 LLM 上下文过长。
- `BaseAgent.run` 在发送给 LLM 前自动调用上下文压缩。
- `config.py` 新增 `memory_backend()`、`context_compress_threshold()`、`context_window_limit()`。
- `tests/test_memory.py`：覆盖短期/工作记忆、上下文压缩、记忆条数压缩。

### Changed

- `MemoryAgent` 重构为统一后端入口，保留旧 `MemoryAgentFacade` 兼容。

### Fixed

- 长提示不再直接传入 LLM，避免触发上下文限制或 Token 浪费。

### Security

- 记忆后端切换不影响现有沙箱路径安全策略。

### Model Changes

- 无

## [0.4.0] - 2026-08-11

### Added

- 模型路由 `dev_agent_system/router.py`：根据 Agent 与提示长度自适应选择模型版本和温度。
- LLM 流式生成：`LLMClient.stream` / `LLMClient.astream` 支持 OpenAI 风格流式输出。
- 编排流式端点：
  - `POST /orchestrate/stream`：以 SSE 实时推送节点开始/结束/最终结果。
  - `POST /{agent}/stream`：单个 Agent 的 token 级 SSE 输出。
  - `JSONRPC` `method=orchestrate_stream` 同样支持 SSE。
- `LLMClient.chat` 支持 `model/temperature/max_tokens` 运行时覆盖。
- `BaseAgent` 集成 `ModelRouter`，每次调用自动选择模型参数。

### Changed

- `server.py` 路由扩展：新增流式相关端点，保持 `/orchestrate` 与 `/rpc` 兼容。
- `LLMClient` 在无 `LLM_API_KEY` 时仍然生成 `[MOCK ...]` 降级输出，但保留覆盖参数接口。

### Fixed

- `LLMClient.chat` 现在能正确把 `temperature` 等生成参数传给后端。

### Security

- 流式输出仍然通过 `LLMClient._mask` 做 PII 脱敏。

### Model Changes

- 无

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
