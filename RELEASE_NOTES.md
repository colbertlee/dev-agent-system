# Release Notes

本文件以“创新发布说明”形式记录每个版本的关键价值、影响范围、升级路径与已知问题，方便用户与运维团队快速判断是否需要升级。

---

## v0.13.0 — 真实 LLM 联调（最新）

**发布日期**：2026-08-11

### 核心价值

- 让 `LLMClient` 同时支持 OpenAI/DeepSeek 云端 API 与 Ollama 本地模型，自动按环境变量选择 Provider，未配置时仍降级为 Mock。
- 为接入真实模型扫清障碍，同步提供同步/异步流式输出接口与单元测试。

### 关键变更

- 新增 `dev_agent_system/llm_providers.py`：`LLMProvider` 抽象 + `OpenAIProvider` + `OllamaProvider` + `MockProvider`。
- `dev_agent_system/llm.py` 重写为 Provider 调度器，保留原有 `chat`/`stream`/`astream` 与 `MockLLM`。
- `dev_agent_system/config.py` 增加 `llm_model()`、`llm_provider()`、`ollama_url()`。
- `.env.example` 增加 `LLM_PROVIDER`（openai/deepseek/ollama/mock）与 `OLLAMA_URL`。
- `dev_agent_system/agents.py` 更新 MOCK 降级判断为 `is_mock()`。
- 新增 `tests/test_llm.py`，63 个测试通过，1 个因未安装 `openai` 被跳过。

### 升级注意

- 无破坏性接口变更。
- 如已配置 `LLM_API_KEY` + `LLM_BASE_URL`，会自动走 `OpenAIProvider`，与旧版本行为一致。
- 想使用本地 Ollama：设置 `LLM_PROVIDER=ollama` 与 `OLLAMA_URL=http://localhost:11434`，模型名使用 `llama3` 或 `ollama/llama3`。

### 已知问题

- `OpenAIProvider` 依赖 `openai` Python 包；若未安装则跳过相关单元测试。

---

## v0.12.0 — 监控与可观测性

**发布日期**：2026-08-11

### 核心价值

- 为系统增加可观测性层，让多 Agent 工作流的每个节点、每次 LLM 调用、每次安全/审查决策都可被度量和追踪。
- `/metrics` 端点直接输出 Prometheus 格式，可接入 Grafana/Alertmanager；`/health` 端点携带实时指标摘要。
- 链路追踪采用 OpenTelemetry 风格 Span，输出结构化 JSON 日志，便于对接 Loki/ELK 等日志聚合系统。

### 关键变更

- 新增 `dev_agent_system/metrics.py`：Counter / Gauge / Histogram 内存实现，支持 Prometheus 文本渲染。
- 新增 `dev_agent_system/telemetry.py`：`Span`、`Telemetry`、嵌套上下文、结构化日志。
- `Orchestrator` 与 `BaseAgent` 自动埋点：工作流运行、Agent 节点、LLM 调用、Review 决策等。
- `server.py` 新增 `/metrics` 与增强 `/health` 端点。
- 将 `dev_agent_system/types.py` 重命名为 `dev_agent_system/schemas.py`，彻底修复 `types` 名称遮蔽 Python 标准库的问题，并同步更新所有导入路径与文档。
- 新增 `tests/test_metrics.py`、`tests/test_telemetry.py`、`tests/test_server.py`，54 个测试全部通过。

### 升级注意

- 无破坏性接口变更。
- `Telemetry` 默认使用 `NullHandler`，日志通过 `propagate=True` 交给上层 logger；生产环境可配置 root logger 或保留默认。
- 直接运行入口脚本现在可以用 `python dev_agent_system/server.py` 或 `python -m dev_agent_system.server`；`types.py` 已重命名为 `schemas.py` 避免标准库遮蔽。

### 已知问题

- 无。

---

## v0.11.0 — 新增角色 Agent

**发布日期**：2026-08-11

### 核心价值

- 将单一“需求→架构→代码”流水线扩展为可插拔的多角色协作矩阵，新增产品经理、安全审查、数据库架构三个角色。
- 通过 `Orchestrator` 的 `enable_*` 参数按需启用新角色，默认保持原有 6 人工作流程不变，兼容历史调用。
- 为后续更复杂的业务场景（金融、企业级后台、合规审计）提供角色扩展模板。

### 关键变更

- 新增 `dev_agent_system/agents.py` 三个类：`ProductManagerAgent`、`SecurityAgent`、`DBAAgent`。
- `prompts.yaml` 新增 `product_manager`、`security`、`dba` 系统提示与输出格式规范。
- `agent_cards.json` 与 `config/model.yaml` 同步扩展。
- `Orchestrator` 支持 `enable_product_manager`、`enable_security`、`enable_dba`；工作流可扩展为：
  `ProductManager → Architect → DBA → Coder → {Tester, Docs} → Reviewer → Security → (DevOps/End)`。
- `types.py` 的 `GraphState` 增加新字段，确保状态在 LangGraph 中正确传递。
- 新增 `tests/test_new_agents.py`，41 个测试全部通过。

### 升级注意

- 无破坏性接口变更。`Orchestrator` 新增参数均为可选，默认 `False`。
- 若显式启用 `enable_security`，Security Agent 未通过时会和 Reviewer 不通过一样触发新一轮迭代。
- `config/model.yaml` 新增模型配置，建议结合业务场景调整模型温度与模型版本。

### 已知问题

- 无。

---

## v0.10.0 — 安全与沙箱加固

**发布日期**：2026-08-11

### 核心价值

- 将安全防护从“黑名单正则”升级为“扫描 + 校验 + 脱敏”三层体系，降低 LLM 生成危险命令或泄露敏感信息的风险。
- `SafetyScanner` 对命令和代码分别做危险模式检测，路径操作统一由 `PathValidator` 校验，避免目录穿越。
- `SecretRedactor` 在 LLM 调用前后自动脱敏 API Key、手机号、邮箱、密码等敏感信息。

### 关键变更

- 新增 `dev_agent_system/security.py`：`SafetyScanner`、`PathValidator`、`SecretRedactor`。
- `ToolSandbox` 命令执行前调用 `SafetyScanner.scan_command`，文件读写前调用 `PathValidator.resolve`。
- `BaseAgent.run` 对 prompt 和 output 做 `SecretRedactor.redact`。
- `CoderAgent.postprocess` 对每段生成代码做 `SafetyScanner.scan_code`，可疑模式写入 `security_issues`。
- `config.py` 新增 `safety_block_dangerous_commands()`、`safety_redact_secrets()`、`safety_code_scan()`。
- 新增 `tests/test_security.py`，37 个测试全部通过。

### 升级注意

- 无破坏性接口变更。
- 默认开启所有安全开关；如需关闭，可设置 `SAFETY_BLOCK_DANGEROUS_COMMANDS=false`、`SAFETY_REDACT_SECRETS=false`、`SAFETY_CODE_SCAN=false`。
- 命令白名单仍以 `ToolSandbox.ALLOWED_PREFIXES` 为准，`SafetyScanner` 作为额外的语义层加固。

### 已知问题

- 无。

---

## v0.9.0 — DevOps 真实闭环

**发布日期**：2026-08-11

### 核心价值

- 让 DevOps 从“生成 Dockerfile 和 CI 配置”升级为“真实构建、运行、健康检查、清理”的完整闭环。
- `DevOpsRunner` 默认 dry-run，确保安全性；关闭 `DEVOPS_DRY_RUN` 后即可在本机 Docker 环境真实部署验证。
- 为后续 CI/CD 集成、自动部署、发布流水线提供可验证的底层能力。

### 关键变更

- 新增 `dev_agent_system/devops.py`：`DevOpsRunner` 支持 `docker build -t <image> .`、`docker run -d`、`docker ps` 健康检查、`docker stop/rm` 清理。
- `Orchestrator` 在 `enable_devops=True` 路径下，Reviewer 通过后进入 `devops_node`，执行 DevOpsAgent 生成产物并调用 `DevOpsRunner`。
- `config.py` 新增 `devops_dry_run()`（默认 `True`）与 `devops_timeout()`（默认 `120s`）。
- 新增 `tests/test_devops.py`，26 个测试全部通过。

### 升级注意

- 无破坏性接口变更。旧版本命令与 API 保持兼容。
- 默认 `DEVOPS_DRY_RUN=true`，不会真正调用 docker；如需真实闭环，请确保本机已安装 Docker 并设置 `DEVOPS_DRY_RUN=false`。
- 涉及真实部署、删除容器等操作属于 L2 以下，建议在 CI 或受控环境中启用。

### 已知问题

- 无。

---

## v0.8.0 — 评估与指标体系

**发布日期**：2026-08-11

### 核心价值

- 让系统从“能跑通单个需求”升级为“可量化评估的 benchmark 平台”。
- 通过 `tests/eval_dataset.json` 中的 10 条真实需求，自动运行并产出 Review 通过率、文件召回率、测试覆盖率、迭代次数与耗时等多维指标。
- 为后续 A/B 测试模型、Prompt 调优、Agent 能力迭代提供数据依据。

### 关键变更

- 新增 `dev_agent_system/eval.py`：`EvaluationRunner`、`MetricCalculator`、`EvalSample`、`EvalReport`。
- 新增 CLI：`python -m dev_agent_system.eval --dataset tests/eval_dataset.json --max-iter 3 --output-dir eval_results`。
- 新增 `tests/test_eval.py`，用 `FakeOrchestrator` 验证指标计算与异常容错。
- `config.py` 新增 `eval_output_dir()` / `eval_max_workers()`，`.env.example` 同步补充。

### 升级注意

- 无破坏性变更。旧版本工作流命令与 API 保持不变。
- 评估默认顺序执行（`EVAL_MAX_WORKERS=1`），避免 SQLite checkpoint 并发锁；如需提速，可改用独立 checkpoint DB 后再提高并发。

### 已知问题

- 无。

---

## v0.7.0 — 状态持久化与断点续跑

**发布日期**：2026-08-11

### 🚀 核心价值

- 让工作流具备“断点续跑”能力：进程重启、容器重启后仍可从中断处继续执行。
- 以 `request_id` 作为 `thread_id` 自动持久化每一步 LangGraph checkpoint 到 SQLite。
- 为后续 Human-in-the-Loop（人工审批后继续）和故障恢复打下基础设施。

### 🔧 关键变更

- 新增 `dev_agent_system/checkpoint.py`：`SQLiteCheckpointSaver` 实现 `BaseCheckpointSaver` 全部同步/异步接口。
- `Orchestrator` 编译 LangGraph 时传入 `checkpointer`，并新增 `resume(request_id)` 方法。
- FastAPI 网关新增 `GET /tasks/{request_id}/checkpoints` 与 `POST /tasks/{request_id}/resume`。
- `config.py` 新增 `checkpoint_db()` 与 `checkpoint_enabled()`；`.env.example` 补充相关配置项。
- 新增 `tests/test_checkpoint.py` 验证 checkpoint 读写、writes 持久化、断点续跑。

### ⚠️ 升级注意

- 无破坏性接口变更；新增状态文件默认写入 `memory_store/checkpoints.sqlite`（已在 `.gitignore` 中忽略）。
- 如需禁用持久化，设置环境变量 `CHECKPOINT_ENABLED=false`，将自动降级为 `MemorySaver`。

### 🛤️ 已知问题

- 无。

---

## v0.6.0 — 文档生态与运维可观测性

**发布日期**：2026-08-11

### 🚀 核心价值

- 构建完整的项目文档矩阵：架构、贡献指南、工具规范、Prompt 管理、使用运维手册一应俱全。
- 让新用户 5 分钟读懂系统，让运维人员 10 分钟完成部署与监控配置。
- 将“发布说明”从变更清单升级为“价值 + 影响 + 操作”三维视图。

### 📦 新增文档

| 文档 | 定位 | 受众 |
|---|---|---|
| `ARCHITECTURE.md` | 系统架构图、核心数据流、模块依赖 | 架构师、新成员 |
| `CONTRIBUTE.md` | 代码规范、Git 提交格式、分支策略、PR checklist | 贡献者 |
| `docs/tools_spec.md` | MCP 工具 JSON Schema、白名单、错误码 | Agent 开发者 |
| `docs/prompt_templates.md` | System Prompt 版本管理、输出格式约定 | Prompt 工程师 |
| `docs/usage_operations.md` | 安装、部署、监控、备份、故障排查 | 用户、SRE |
| `RELEASE_NOTES.md` | 版本价值、影响矩阵、升级路径、已知问题 | 所有角色 |

### 🔧 运维增强

- `.env.example` 新增 `MEMORY_BACKEND`、`REDIS_URL`、`CONTEXT_COMPRESS_THRESHOLD`、`CONTEXT_WINDOW_LIMIT`。
- 新增每日/每周/发布前运维检查清单。

### ⚠️ 升级注意

- 无破坏性变更，纯文档与配置模板补充。
- 建议从 `docs/usage_operations.md` 开始阅读并完成 `.env` 配置。

### 🛤️ 已知问题

- 无。

---

## v0.5.0 — 可插拔记忆后端与上下文压缩

**发布日期**：2026-08-11

### 🚀 核心价值

- 让系统从“玩具级内存”升级为可落地的三层记忆架构：短期/工作/长期。
- 支持 Redis、ChromaDB、SQLite 三档后端，缺失依赖时自动降级。
- 引入上下文压缩，避免 LLM 因上下文过长导致截断或高额 Token 费用。

### 🔧 关键变更

- `memory.py` 重构：`MemoryBackend` 协议 + `SQLiteMemoryBackend` + `RedisMemoryBackend` + `ChromaMemoryBackend`。
- `ContextCompressor` 基于字符数保留头部/尾部，自动省略中间文本。
- `BaseAgent.run` 在调用 LLM 前自动压缩上下文。
- `config.py` 新增 `memory_backend()`、`context_compress_threshold()`、`context_window_limit()`。

### ⚠️ 升级注意

- 无需修改业务代码；旧 `MemoryAgentFacade` 接口仍兼容。
- 若启用 Redis/ChromaDB，需先安装对应 Python 包并启动服务。

---

## v0.4.0 — 模型路由与 LLM 流式输出

**发布日期**：2026-08-11

### 🚀 核心价值

- 实现“按 Agent + 提示长度”自动选择最合适模型，降低大模型调用成本。
- 统一网关支持 SSE 流式编排，让前端可实时观测每个 Agent 的执行进度。

### 🔧 关键变更

- 新增 `dev_agent_system/router.py`：`ModelRouter.resolve` 返回模型与生成参数。
- `LLMClient` 支持 `stream` / `astream` 流式生成。
- `server.py` 新增 `POST /orchestrate/stream` 与 `POST /{agent}/stream` SSE 端点。
- `BaseAgent` 集成 `ModelRouter`。

### ⚠️ 升级注意

- `LLMClient.chat` 签名扩展，支持 `model`、`temperature`、`max_tokens` 运行时覆盖；旧调用仍兼容。

---

## v0.3.0 — Agent 产物真正落地

**发布日期**：2026-08-11

### 🚀 核心价值

- Coder、Tester、Docs 不再是“文本生成器”，而是真正写入文件、运行测试、产出文档。
- Reviewer 输出结构化 JSON，驱动 LangGraph 条件迭代。

### 🔧 关键变更

- `CoderAgent` 解析代码块并写入 `workspace/<request_id>/`。
- `TesterAgent` 生成 `test_*.py` 并执行 `pytest -q`。
- `DocsAgent` 写入 `docs/README.md` 与 `docs/API.md`。
- `ReviewerAgent` 解析 JSON 并写入 `review_report.json`。
- `BaseAgent` 增加 `postprocess` 生命周期钩子与 `MCPToolRegistry.ainvoke` 异步调用。
- LangGraph DAG 调整为 `Architect → Coder → {Tester, Docs} → Reviewer`。

### ⚠️ 升级注意

- `BaseAgent.run` 改为 `async def`；`server.py` 与 `a2a_node.py` 已同步 `await`。

---

## v0.2.0 — 可运行、可部署、可验证的多 Agent 系统

**发布日期**：2026-08-09

### 🚀 核心价值

- 首个完整可交付版本：6 个 Agent、LangGraph DAG、A2A 网关、独立 A2A 节点、Docker 部署、CI/CD。

### 🔧 关键变更

- LangGraph `StateGraph` 编排器、统一 FastAPI 网关、独立 A2A Agent 节点。
- MCP 工具沙箱、三层记忆（内存+SQLite 降级）、LLM 客户端。
- Docker、docker-compose、GitHub Actions CI、版本管理脚本。

---

## v0.1.0 — 项目骨架

**发布日期**：2026-08-09 前

### 🚀 核心价值

- 确立 `dev_agent_system` 包结构与角色划分。

---

## 影响矩阵（Impact Matrix）

| 版本 | 用户可见 | Agent 行为 | A2A 协议 | 配置变更 | 迁移成本 |
|---|---|---|---|---|---|
| v0.6.0 | ⭐⭐ 文档 | 无变化 | 无变化 | `.env` 新增可选配置 | 低 |
| v0.5.0 | ⭐⭐ 记忆后端 | 无变化 | 无变化 | `MEMORY_BACKEND` 等 | 低 |
| v0.4.0 | ⭐⭐⭐ 流式 API | 模型选择更智能 | 新增 SSE 端点 | `config/model.yaml` 可选 `adaptive` | 中 |
| v0.3.0 | ⭐⭐⭐⭐ 产物落地 | 行为重大变化 | 返回字段扩展 | 无 | 中 |
| v0.2.0 | ⭐⭐⭐⭐⭐ 完整系统 | 首次可用 | 首次可用 | 大量新增 | 高（首次） |

---

## 升级建议

| 当前版本 | 建议升级至 | 理由 |
|---|---|---|
| v0.2.0 | v0.6.0 | 产物落地、流式、记忆后端、完整文档均值得升级 |
| v0.3.0 | v0.6.0 | 获得流式输出、记忆后端与运维手册 |
| v0.4.0 | v0.6.0 | 获得可插拔记忆与完整文档 |
| v0.5.0 | v0.6.0 | 文档与运维体验大幅提升 |

---

## 如何订阅版本通知

- Watch GitHub Releases：<https://github.com/colbertlee/dev-agent-system/releases>
- 查看 `CHANGELOG.md` 获取扁平化变更清单。
- 查看本文件获取版本价值与升级影响。
