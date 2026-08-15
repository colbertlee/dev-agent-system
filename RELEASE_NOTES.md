# Release Notes

本文件以“创新发布说明”形式记录每个版本的关键价值、影响范围、升级路径与已知问题，方便用户与运维团队快速判断是否需要升级。

---

## v0.22.1 — 文档同步与 HTML 生成（最新）

**发布日期**：2026-08-14

### 核心价值

- 把项目 Markdown 文档升级为可离线阅读、带目录、响应式暗色模式的 HTML，降低新成员与 Devin 阅读长规范的门槛。
- 建立 `scripts/sync_spec.py` 机制，让 `agent_generator_spec.md` / `agent_framework_retrospective.md` 的源码附录、版本号、行号引用随代码自动同步，避免“文档刚写完就失步”的维护负担。

### 关键变更

- 新增 `scripts/generate_docs.py`：基于 `markdown` 库生成 `*.html`，自动标题去 `¶`、自动把 `<ref_file>` / `<ref_snippet>` 转为相对链接。
- 新增 `scripts/sync_spec.py`：重抽 `docs/agent_generator_spec.md` 全部源码附录（含 `human_approval.py`），刷新版本号到 v0.22.0。
- 刷新 `docs/agent_framework_retrospective.md`：版本范围扩展到 v0.22.0，新增 v0.21/v0.22 四要素落地小节，所有 `<ref_snippet>` 行号引用改为 `<ref_file>` 文件引用。
- 更新 `README.md`、`AGENTS.md`、`ARCHITECTURE.md`、`CONTRIBUTE.md`、`docs/prompt_templates.md`、`docs/usage_operations.md` 以反映 v0.22.0 的 9 个 Agent、结构化输出、Human-in-the-Loop、状态摘要、新 Server 端点等变化。
- `requirements.txt` 增加 `markdown==3.7`。

### 升级注意

- 本次为文档/体验 PATCH，无代码接口变更。
- 发布 `v0.22.1` 后请同步执行 `python scripts/generate_docs.py <markdown>` 重新生成 HTML。

### 已知问题

- 无。

---

## v0.22.0 — 多 Agent 间状态精简传输

**发布日期**：2026-08-14

### 核心价值

- 把 Agent 间传递的“原始 LLM 输出”升级为“关键信息摘要”：既保留下游需要的状态、产物、报告字段，又避免把长段自然语言或中间产物塞进后续 prompt 和 checkpoint。
- 每个 Agent 可配置 `summary_budget`，在信息完整与 Token 消耗之间根据场景复杂度动态平衡。

### 关键变更

- `BaseAgent` 新增 `summary_budget` 与 `_summarize_result`：Agent 运行结束后把结果压缩为合法 JSON 摘要，丢弃 `output`/`workspace`/`model`/`llm_kwargs` 等内部字段。
- `_truncate_for_summary` 递归截断长字符串、长列表与嵌套 dict；`_summarize_result` 自适应调整截断粒度，保证输出始终为合法 JSON。
- `BaseAgent.run` 把 `result["output"]` 替换为摘要；记忆层 `last_output` 也存摘要。
- 为各 Agent 配置差异化预算：`Architect`/`DBA` 1500–2000，`Tester`/`Reviewer`/`Security` 1200，`Docs` 800，`DevOps` 1000 等。
- `Orchestrator._collect_artifacts` 对 `tests` 优先使用 `tester.report` 原始 stdout，方便排障。
- 新增 `tests/test_context_compression.py` 覆盖摘要过滤、递归截断与自适应压缩。

### 升级注意

- 无破坏性接口变更；`state["xxx"]["output"]` 现在存放的是摘要字符串，仍可被下游 prompt 使用，但不再包含完整原始 LLM 输出。
- 如需完整原始输出，请读取对应产物文件（如 `design.json`、`review_report.json`、`security_report.json`、`prd.md`）或 `tester.report` 字段。

### 已知问题

- 无。

---

## v0.21.0 — 结构化输出强制化与人工审批

**发布日期**：2026-08-14

### 核心价值

- 从“Prompt 层面劝说”升级到“API + Pydantic 双保险”：LLM 在 `json_mode` 下被强制输出 JSON，Agent 再用 Pydantic 校验字段。
- 为 DevOps 真实部署加入 Human-in-the-Loop：未人工批准前不会执行任何 Docker/CI/CD 写操作。

### 关键变更

- `LLMClient` / `LLMProvider` 新增 `json_mode`：
  - OpenAI 兼容接口自动注入 `response_format={"type": "json_object"}`。
  - Ollama 接口自动注入 `format="json"`。
- `BaseAgent` 新增 `_parse_json_output`：支持纯 JSON、Markdown 内嵌 JSON、dict 校验，兼容旧版 Markdown 代码块产物。
- `schemas.py` 新增 `AgentOutput`、`AgentFile`、`DesignOutput`、`DBAReport`、`PRDOutput`，并为既有 report 模型开启 `extra="ignore"`。
- 为 `Architect`、`Coder`、`Tester`、`DBA`、`Reviewer`、`Security`、`ProductManager` 配置 `report_schema`。
- `prompts.yaml` 中 `coder`/`tester`/`dba` 的系统提示改为要求“仅输出合法 JSON”。
- 新增 `dev_agent_system/human_approval.py`：`HumanApprovalStore` 基于 SQLite 记录 `pending`/`approved`/`rejected`。
- `Orchestrator` 在真实部署前检查审批；未批准返回 `awaiting_approval`，管理员可通过 `approve_devops` 或 Server 端点批准。
- `server.py` 新增 `/tasks/{request_id}/approval`、`/tasks/{request_id}/approve`、`/tasks/{request_id}/reject`。

### 升级注意

- 现有工作流默认 `DEVOPS_DRY_RUN=true`，干跑模式下不会触发人工审批。
- 若启用真实部署，请先调用 `/tasks/{request_id}/approve` 或在代码中调用 `Orchestrator.approve_devops`。

### 已知问题

- 无。

---

## v0.20.1 — Agent 生成器规范

**发布日期**：2026-08-12

### 核心价值

- 提供一份“Devin / 开发者可直接据此复现当前多 Agent 系统”的生成器规范。
- 覆盖 9 个业务 Agent 的 4-Block Framework 映射、Prompting Specification Template、输入输出格式、工具使用、异常处理与产物约定。
- 附录中给出 `prompts.yaml`、`agent_cards.json`、核心模块源码与配置文件，便于从零生成等价系统。

### 关键变更

- 新增 `docs/agent_generator_spec.md`：
  - 9 个 Agent 的 `4-Block` 映射与 `Prompting Specification Template`。
  - 全局基础设施规范：LLM、MCP、Memory、Security、Telemetry/Metrics、Orchestrator、A2A/Server。
  - 完整附录：`prompts.yaml`、`agent_cards.json`、`schemas.py`、`templates.py`、`mcp.py`、`security.py`、`memory.py`、`llm.py`、`llm_providers.py`、`config/model.yaml`、`config/mcp.yaml`、模块清单。
- 新增 `docs/agent_generator_spec.html`：
  - 响应式布局、侧边目录、锚点导航、代码块与表格样式、暗色模式支持。
- `README.md` 与 `AGENTS.md` 增加生成器规范导航链接。
- `dev_agent_system/__init__.py` 版本号更新为 `0.20.1`。

### 升级注意

- 无破坏性接口变更。
- 仅新增文档资产与导航链接，不修改核心代码与 Prompt。

### 已知问题

- 无。

---

## v0.20.0 — Agent 架构四要素与 Prompting 规范文档

**发布日期**：2026-08-11

### 核心价值

- 将“Agent 架构四要素”（角色/安全边界、上下文/IO 规范、工具/能力边界、工作流/异常处理）与 Coder Agent 的 Prompting 规范，从当前 `dev_agent_system` 实现中反推整理成可发布文档。
- 帮助新手快速理解系统约束，并据此验证、迭代与扩展 Agent。

### 关键变更

- 新增 `docs/agent_framework_retrospective.md`：
  - 四要素与 `prompts.yaml`、`agent_cards.json`、`mcp.py`、`security.py`、`orchestrator.py` 等实际代码的对应关系。
  - Coder Agent 的 `Role/Goal`、`Inputs & Format`、`Workflow (SOP)`、`Constraints & Rules`、`Exception Handling` 模板。
  - 新手验证 Agent 质量的“边界压力测试 → 精准反馈迭代 → 模块化拆解”三步法。
- 新增 `docs/agent_framework_retrospective.html`：
  - 响应式布局、侧边目录、锚点导航、代码块与表格样式、暗色模式支持。
  - 离线可用，无外部 CDN 依赖。
- `dev_agent_system/__init__.py` 版本号更新为 `0.20.0`。

### 升级注意

- 无破坏性接口变更。
- 仅新增文档资产，不修改核心代码与 Prompt。

### 已知问题

- 文档引用 `<ref_file>` / `<ref_snippet>` 在 Markdown 中以标签形式保留；HTML 版本已将其转换为文件名/行号内联 `<code>` 显示。

---

## v0.19.0 — Skill 市场协议与 Agent 自动发现

**发布日期**：2026-08-11

### 核心价值

- 把 Skill 从本地工具升级为可发现、可远程调用的市场协议，并让每个 Agent 在初始化时自动加载已安装 Skill。
- 为后续构建 Skill Store / Agent 间 Skill 共享打下基础。

### 关键变更

- `dev_agent_system/skills.py`：
  - `SkillManager.find(query, limit)`：关键词匹配 Skill。
  - `SkillManager` 可通过 `register_to_mcp` 将 Skill 注册到 MCP 工具箱。
- `dev_agent_system/agents.py`：
  - `BaseAgent.__init__` 自动调用 `SkillManager().register_to_mcp(self.tools)`，实现 Agent 自动发现。
- `dev_agent_system/server.py`：
  - `GET /skills`：列出所有已安装 Skill。
  - `GET /skills/{skill_id}`：获取 Skill 元数据。
  - `POST /skills/{skill_id}/invoke`：远程调用 Skill。
- 新增 `tests/test_server_skills.py`；99 个测试通过，2 个跳过。

### 升级注意

- 无破坏性接口变更。
- 默认 `SKILLS_ENABLED=true`，Agent 启动时会扫描 `skills/` 目录；如不需要可设置 `SKILLS_ENABLED=false`。

### 已知问题

- `/skills/{skill_id}/invoke` 当前直接执行 `skill.py` 中的 `run()`，未做输入校验与沙箱化；对外暴露时建议前置鉴权与参数校验。

---

## v0.18.0 — 最小版 Skill 管理

**发布日期**：2026-08-11

### 核心价值

- 让系统支持动态安装、卸载、调用 Skill，并为每个 Skill 自动生成标准包结构与可执行 `run()` 入口。
- Skill 可以注册为 MCP 工具，供 Agent 在工作流中调用。

### 关键变更

- 新增 `dev_agent_system/skills.py`：
  - `Skill`：元数据 + 动态模块加载 + `invoke()`。
  - `SkillStore`：扫描 `skills/` 目录，解析 `SKILL.md` YAML frontmatter，加载 `skill.py`。
  - `SkillManager`：
    - `install(source)`：支持本地目录或 `{id, name, description, prompt, code}` 字典安装。
    - `uninstall(skill_id)` / `list()` / `get(skill_id)`。
    - `invoke(skill_id, *args, **kwargs)`。
    - `register_to_mcp(registry, prefix)`：把有 `run()` 的 Skill 注册为 MCP 工具。
- `dev_agent_system/config.py` 增加 `skills_dir()`（默认 `skills/`）与 `skills_enabled()`。
- 新增 `tests/test_skills.py`；95 个测试通过，2 个跳过。

### 升级注意

- 无破坏性接口变更。
- 通过 `SkillManager` 安装的代码来自 `skills/` 目录下的 Python 文件；生产环境建议对来源做校验或沙箱化。

### 已知问题

- 当前 `SkillStore` 直接 `exec_module` 加载 `skill.py`，存在与运行环境共享全局状态的风险，后续应增加沙箱或签名机制。

---

## v0.17.0 — 安全加固进阶

**发布日期**：2026-08-11

### 核心价值

- 为 Agent 产物与运行环境增加高阶安全扫描能力：Secret 泄露检测、依赖漏洞扫描、容器沙箱执行，并在 CI 中落地。
- 降低真实使用 LLM 生成代码时引入敏感信息或依赖漏洞的风险。

### 关键变更

- 新增 `dev_agent_system/security_scanner.py`：
  - `SecretScanner`：扫描文件中的 API Key、GitHub/GitLab Token、AWS Key、私钥、硬编码密码等模式。
  - `DependencyScanner`：优先调用 `safety`，回退 `pip-audit`，对 `requirements.txt` 做依赖漏洞扫描。
  - `ContainerSandbox`：把命令包装为 `docker run --rm --network none -v workspace:/workspace ...`，提供额外隔离。
  - `SecurityPipeline`：组合 Secret 扫描、依赖扫描与命令执行，返回 `safe` 标志与详细 findings。
- 新增 `.github/workflows/security.yml`：
  - TruffleHog Secret 扫描（PR/Push + 定时每周一）。
  - Safety 依赖漏洞扫描。
  - Bandit 静态代码安全扫描，并上传报告 Artifact。
- 新增 `tests/test_security_scanner.py`；88 个测试通过，2 个跳过。

### 升级注意

- 无破坏性接口变更。
- 真实运行依赖扫描需要安装 `safety` 或 `pip-audit`；容器沙箱需要本地 Docker。

### 已知问题

- `SecretScanner` 为正则启发式扫描，可能存在误报；重要场景建议结合 TruffleHog 等专业工具。

---

## v0.16.0 — 多语言支持

**发布日期**：2026-08-11

### 核心价值

- 让同一套多 Agent 工作流支持 Python、Java、Go、TypeScript 四种语言，自动根据 `language` 字段选择文件命名、测试命令与包管理模板。
- 为后续扩展更多语言提供统一的 `LangTemplate` 抽象。

### 关键变更

- 新增 `dev_agent_system/templates.py`：`LangTemplate` 数据类 + `TEMPLATES` 注册表，覆盖 Python / Java / Go / TypeScript。
- `GraphState` / `WorkflowState` / `Task` 增加 `language: Optional[str]` 字段，默认 `python`。
- `Orchestrator.run`、`run_stream`、`EvaluationRunner._evaluate_one` 透传 `language`。
- `ArchitectAgent`、`CoderAgent`、`TesterAgent` 读取 `language` 并生成对应技术栈产物与测试。
- `ToolSandbox.ALLOWED_PREFIXES` 扩展 Java/Go/TS 工具链命令。
- `dev_agent_system/main.py` 与 `dev_agent_system/tui.py` 增加 `--language` 参数。
- `tests/eval_dataset.json` 增加 3 条 Java / Go / TypeScript 评估用例，总数达 18 条。
- 新增 `tests/test_templates.py`、`tests/test_multilang.py`；84 个测试通过，2 个跳过。

### 升级注意

- 无破坏性接口变更；未指定 `language` 时默认仍按 Python 处理。
- 真实运行 Java/Go/TS 测试需要本地安装对应工具链（maven / go / node）。

### 已知问题

- MOCK 模式仅生成占位代码，无法真正覆盖多语言语法与测试。

---

## v0.15.0 — 评估与 benchmark 调优

**发布日期**：2026-08-11

### 核心价值

- 让 benchmark 数据集更全面，支持自动回归检测，确保每次改动不会降低系统整体能力。
- 通过 `RegressionChecker` 将当前跑分与 baseline 对比，下降超过阈值即失败，便于集成到 CI。

### 关键变更

- `tests/eval_dataset.json` 从 10 条扩充到 15 条，新增 CSV 处理、LRU 缓存、邮件服务、限流器、配置中心等任务。
- `dev_agent_system/eval.py` 新增 `RegressionChecker` 类，负责加载/保存/对比 baseline。
- `python -m dev_agent_system.eval` 增加 `--baseline`、`--update-baseline`、`--tolerance` 参数。
- 默认行为：跑完后与 `output_dir/eval_baseline.json` 对比，指标回退超过 5% 时以退出码 1 报错。
- 新增 `tests/test_eval.py`：覆盖 `MetricCalculator`、回归检测、`EvaluationRunner` mock 端到端；72 个测试通过，2 个跳过。

### 升级注意

- 无破坏性接口变更。
- 首次运行可加上 `--update-baseline` 生成基准文件；后续 CI 去掉该参数即可做回归检测。

### 已知问题

- 评估数据集仍基于 MOCK LLM，接入真实模型后需更新 `expected_files` 与 `min_test_coverage`。

---

## v0.14.0 — CLI / UI 增强

**发布日期**：2026-08-11

### 核心价值

- 为工作流增加实时可观测界面：终端 TUI 进度面板与 Web Dashboard。
- `Orchestrator` 在运行期间把工作流状态写入内存追踪器，`/api/status` 与 `/dashboard` 可直接查看当前 Agent、迭代、耗时与产物。

### 关键变更

- 新增 `dev_agent_system/tracker.py`：单例 `WorkflowTracker`，线程安全，记录 `request_id` 级工作流状态。
- `Orchestrator` 集成 `WorkflowTracker`：`run`/`resume`/`_run_agent` 自动同步状态。
- 新增 `dev_agent_system/tui.py`：基于 `rich` 的 `OrchestratorTUI`，运行 `python -m dev_agent_system.tui "需求"` 可在终端实时查看进度。
- 新增 `dev_agent_system/dashboard.py`：Web Dashboard 页面与数据聚合。
- `server.py` 新增 `/dashboard`、 `/api/status`、 `/api/status/{request_id}` 三个端点。
- `requirements.txt` 增加 `rich==13.9.4`。
- 新增 `tests/test_dashboard.py` 与 `tests/test_tui.py`；68 个测试通过，2 个因未安装 `rich`/`openai` 跳过。

### 升级注意

- 无破坏性接口变更。
- 使用 TUI 前需要 `pip install -r requirements.txt` 安装 `rich`。
- `WorkflowTracker` 为内存实现，进程重启会丢失历史记录；生产可替换为 Redis 实现。

### 已知问题

- `WorkflowTracker` 当前为单进程内存存储，不支持多实例共享。

---

## v0.13.0 — 真实 LLM 联调

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
