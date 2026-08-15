# dev_agent_system Agent 生成器规范

> 本文档是可复现当前多 Agent 协作系统的生成规范。它从 `dev_agent_system` v0.22.0 代码库逐模块、逐 Agent 反推，覆盖每个 Agent 的 4-Block Framework 映射、Prompting 模板、输入输出格式、工具使用、异常处理，以及支撑组件（MCP、记忆、LLM、编排、A2A、可观测性、安全）的完整接口与行为约定。

> 基于 `dev_agent_system` v0.22.0 代码库逐模块、逐 Agent 反推，目标是将 `docs/agent_generator_spec.md`（及配套 HTML）写成一份“Devin 可直接据此复现系统”的生成规范。所有内容均来自现有代码、测试与文档，不引入未实现功能。

> 本版同步了 v0.21.0/v0.22.0 新增能力：LLM `json_mode` 结构化输出、`BaseAgent.report_schema` Pydantic 校验、Human-in-the-Loop 审批门、以及 `summary_budget` 状态摘要。

---

## 一、生成目标与交付物

### 1.1 目标

让任何阅读该规范的 Devin / 开发者能够从头生成与当前仓库等价的 `dev_agent_system`：

- 模块划分与文件路径一致；
- 每个 Agent 的 system prompt、build_prompt、postprocess、I/O Schema、异常处理与代码中保持一致；
- Orchestrator 的 LangGraph DAG、状态字段、条件边、异常重试与代码一致；
- 工具链（MCP / Skill / Memory / LLM / Telemetry / Metrics / Security）接口与行为一致；
- A2A 协议、CLI、TUI、Dashboard、Server 端点行为一致；
- 测试集结构与覆盖范围一致。

### 1.2 交付物

1. `docs/agent_generator_spec.md` —— 完整 Markdown 生成规范（保留当前 `agent_framework_retrospective.md` 不变）。
2. `docs/agent_generator_spec.html` —— 响应式、带目录、可离线阅读的 HTML 版本。
3. 可选：在 `AGENTS.md` 或 `README.md` 增加指向 `agent_generator_spec.md` 的导航链接（不改动核心代码）。

---

## 二、系统级 4-Block 映射（全局基础设施）

### 2.1 角色与安全边界（Global Role & Guardrails）

| 组件 | 角色 | 禁止做的事 | 关键文件 |
|---|---|---|---|
| `Config` | 统一配置加载器 | 不直接修改 `.env` / YAML；不在代码中写死密钥 | `config.py` `dev_agent_system/config.py` |
| `LLMClient` | LLM 调用入口（支持 `json_mode`） | 不暴露真实 API Key；无 Key 时必须降级 Mock | `llm.py`, `llm_providers.py` |
| `ModelRouter` | 按 Agent / 提示长度选模型 | 不写死模型版本；依赖 `config/model.yaml` | `router.py` |
| `MemoryAgent` | 三层记忆（short/working/long） | 不阻塞主流程；后端不可用时必须降级 SQLite | `memory.py` |
| `ToolSandbox` | 命令/文件沙箱 | 不执行白名单外命令；不允许目录穿越 | `mcp.py`, `security.py` |
| `SafetyScanner` | 命令与代码安全扫描 | 不直接拦截 Suspicious 代码（仅记录），Dangerous 命令命中即拦截 | `security.py` |
| `SecurityPipeline` | Secret/依赖漏洞/容器沙箱扫描 | 不直接修改文件；仅产出 findings 与 `safe` 字段 | `security_scanner.py` |
| `SecretRedactor` | 入/出 LLM 的 PII 脱敏 | 不可还原脱敏内容 | `security.py`, `llm.py` |
| `Telemetry` / `Metrics` | 可观测性 | 不可因埋点失败中断工作流 | `telemetry.py`, `metrics.py` |
| `Orchestrator` | DAG 编排器 + HITL 审批门 | 节点不可修改自身状态外的字段；Reviewer 不直接修改 Coder 产物 | `orchestrator.py` |
| `HumanApprovalStore` | 审批状态持久化 | 不直接执行部署；仅记录审批结果 | `human_approval.py` |
| `Schemas` | Pydantic / TypedDict 定义 | 不引入未定义字段 | `schemas.py` |

全局安全边界：

- `ToolSandbox.ALLOWED_PREFIXES`：见 `dev_agent_system/mcp.py`
- `SafetyScanner.DANGEROUS_COMMAND_PATTERNS` 命中即拦截：见 `dev_agent_system/security.py`
- `PathValidator` 路径越界检查：见 `dev_agent_system/security.py`
- `SecretRedactor` 脱敏模式：见 `dev_agent_system/security.py`
- `HumanApprovalStore` 审批持久化：见 `dev_agent_system/human_approval.py`
- DevOps 真实部署前 Human-in-the-Loop：见 `dev_agent_system/orchestrator.py` 与 `dev_agent_system/server.py`

### 2.2 上下文与输入输出规范（Global IO Format）

**统一状态 `GraphState`** 见 `dev_agent_system/schemas.py`

```python
{
  "request_id": str,
  "input": str,
  "language": Optional[str],   # "python" | "java" | "go" | "typescript"
  "workspace": str,
  "iteration": int,
  "max_iterations": int,
  "status": str,               # submitted / working / completed / failed / awaiting_approval
  "architect": Optional[Dict[str, Any]],
  "coder": Optional[Dict[str, Any]],
  "tester": Optional[Dict[str, Any]],
  "docs": Optional[Dict[str, Any]],
  "reviewer": Optional[Dict[str, Any]],
  "devops": Optional[Dict[str, Any]],
  "product_manager": Optional[Dict[str, Any]],
  "security": Optional[Dict[str, Any]],
  "dba": Optional[Dict[str, Any]],
  "memory": Optional[Dict[str, Any]],
  "history": List[Dict[str, Any]],
  "artifacts": Dict[str, Any],
  "finished_at": Optional[str],
}
```

**A2A 协议** `dev_agent_system/schemas.py`（新增 `awaiting_approval` 状态，用于 Human-in-the-Loop）（新增 `awaiting_approval` 状态，用于 Human-in-the-Loop）（新增 `awaiting_approval` 状态，用于 Human-in-the-Loop）（新增 `awaiting_approval` 状态，用于 Human-in-the-Loop）（新增 `awaiting_approval` 状态，用于 Human-in-the-Loop）

- `AgentCard`: `{name, url, skills, capabilities}`
- `Task`: `{description, task_id, request_id, max_iterations, language, payload}`
- `TaskResponse`: `{status, task_id, result}`，status ∈ `submitted/working/completed/failed/skipped/awaiting_approval`
- `JSONRPCRequest` / `JSONRPCResponse`: `{jsonrpc: "2.0", method, params, id}` / `{jsonrpc: "2.0", result, id}`

**产物文件命名约定**

- 代码块前必须带 `# file: <relative_path>` 头部；
- `BaseAgent._extract_code_blocks()` 解析头部与 fenced code block；`dev_agent_system/agents.py (lines 98-107)`
- 最终产物写入 `workspace/<request_id>/`。

### 2.3 工具链与能力边界（Global Tools & Capabilities）

**MCP 三件套** `dev_agent_system/mcp.py (lines 92-130)`

| 工具 | 同步/异步 | 输入 | 输出 |
|---|---|---|---|
| `read_file` | 同步 | `path`, `base_dir` | `{"success": bool, "error": str, "content": str}` |
| `write_file` | 异步 | `path`, `content`, `base_dir` | `{"success": bool, "error": str, "path": str}` |
| `run_command` | 同步 | `command`, `base_dir`, `timeout` | `{"success": bool, "returncode": int, "stdout": str, "stderr": str, "error": str}` |

**Skill 系统** `dev_agent_system/skills.py (lines 272-286)`

- `Skill` 包结构：`skills/<skill_id>/SKILL.md`（YAML frontmatter + prompt）+ `skill.py`（定义 `run(*args, **kwargs)`）。
- `SkillManager` 自动将 Skill 注册为 MCP 工具，前缀 `skill_`。
- `BaseAgent` 初始化时调用 `SkillManager().register_to_mcp(self.tools)`。

**LLM 能力边界** `dev_agent_system/llm.py`

- 支持 `openai` / `deepseek` / `ollama` / `mock` Provider；
- `LLMClient.chat(system, user, model=None, temperature=None, max_tokens=None)` 返回字符串；
- 输入/输出均经 `SecretRedactor.redact` 脱敏；
- 异常返回 `[LLM ERROR] {e}`，不抛未处理异常。

**记忆能力边界** `dev_agent_system/memory.py (lines 235-285)`

- `remember(key, value, session_id, layer, ttl)`：`layer` = `short` | `working` | `long`；
- `recall(query, session_id, layer, top_k)`；
- `compress_context(text, max_chars)`：保留头尾，中间省略。

### 2.4 工作流与异常处理（Global Workflow & Exception Handling）

**LangGraph DAG 完整 SOP** `dev_agent_system/orchestrator.py (lines 118-168)`

```text
start
 │
 ▼
product_manager_node (可选 enable_product_manager)
 │
 ▼
architect_node
 │
 ▼
dba_node (可选 enable_dba)
 │
 ▼
coder_node
 │
 ▼
tester_docs_node  (Tester / Docs 并行，asyncio.gather)
 │
 ▼
reviewer_node
 │
 ▼
security_node (可选 enable_security)
 │
 ▼
should_continue? (条件边)
 ├─ passed / max_iter reached → END
 └─ not passed & iter < max → architect_node (新一轮)
     │
     ▼
 approval_gate -> devops_node （可选 enable_devops；真实部署需 HumanApprovalStore 审批）
```

**异常/降级策略**

- `LLMClient` 异常返回 `[LLM ERROR] ...`；
- `ToolSandbox` 命令超时/被拦截返回 `{"success": false, "error": ...}`；
- `Reviewer` / `Security` 输出无法解析 JSON 时，保守 fallback：`{"severity": "medium", "passed": false, "issues": ["输出无法解析为 JSON"], ...}`；
- `Coder` 在 MOCK 且无产物时写 `_fallback_code`，状态 `mock_fallback`；
- `Orchestrator` 支持 `resume(request_id)` 从 SQLite checkpoint 恢复；
- `IdempotencyGuard` 对重复 `request_id` 直接返回 `skipped`。

---

## 三、逐 Agent 生成规范

> 每个 Agent 的规范包含：
> 1. **4-Block 映射**：角色/安全、上下文/IO、工具/能力、工作流/异常。
> 2. **Prompting Specification Template**：Role/Goal、Inputs & Format、Workflow (SOP)、Constraints & Rules、Exception Handling。
> 3. **实现要点**：类签名、build_prompt 公式、postprocess 步骤、输出 Schema、产物文件。

### 3.1 ProductManagerAgent

#### 3.1.1 4-Block 映射

| 要素 | 实现 |
|---|---|
| 角色 | Product Manager Agent（产品经理），把模糊需求拆成 PRD、用户故事、验收标准。 |
| 安全边界 | 不写实现代码/架构设计；不操作工具沙箱中的命令。 |
| 上下文输入 | `state["input"]`（自然语言需求）。 |
| 输出格式 | Markdown 代码块 `# file: prd.md` + JSON `{user_stories: [...], acceptance_criteria: [...]}`。 |
| 工具 | `write_file`（写 `prd.md`）。 |
| 工作流 | 1) 接收需求；2) 生成 PRD 正文；3) 提取 JSON；4) 写入 `prd.md`。 |
| 异常处理 | 若 JSON 缺失，`user_stories` / `acceptance_criteria` 返回空列表；PRD 文件始终写入。 |

#### 3.1.2 Prompting Specification Template

**# Role/Goal**  
你是 `ProductManagerAgent`（产品经理）。核心任务：把 `state["input"]` 中的用户需求拆分为清晰的产品需求文档（PRD）、用户故事列表与验收标准。

**# Inputs & Format**

- 用户需求：`state["input"]`，自然语言字符串。
- 工作目录：`state["workspace"]`，用于落地 `prd.md`。

**# Workflow (SOP)**

1. 分析用户需求，识别歧义并给出合理假设。
2. 输出 PRD 正文到 Markdown 代码块，头部：`# file: prd.md`。
3. 输出 JSON：`{user_stories: [...], acceptance_criteria: [...]}`。

**# Constraints & Rules**

- 不直接写实现代码或架构设计。
- 用户故事使用“作为…，我希望…，以便…”格式。
- 验收标准必须是可验证的断言。

**# Exception Handling**

- 若未生成 JSON 块，返回 `{"user_stories": [], "acceptance_criteria": []}`。
- 若 `write_file` 失败，在结果 `note` 中记录错误。

#### 3.1.3 实现要点

```python
class ProductManagerAgent(BaseAgent):
    report_schema = PRDOutput
    summary_budget = 1200

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "ProductManager",
            "产品经理",
            _load_prompt("product_manager"),
            model=model,
            skills=["requirement-analysis", "prd", "user-stories"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"用户需求：{state.get('input', '')}\n"
            "请把需求拆分为 PRD、用户故事和验收标准。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        report = await self._parse_json_output(output, self.report_schema) or {}
        prd_file = "prd.md"
        # 如果结构化输出里有 prd_markdown，优先写入；否则把原始输出作为 PRD 正文
        prd_body = report.get("prd_markdown") or output
        await self._write_file(prd_file, prd_body, workspace)
        return {
            "prd_file": prd_file,
            "user_stories": report.get("user_stories", []),
            "acceptance_criteria": report.get("acceptance_criteria", []),
            "parsed": report,
        }
```

---

### 3.2 ArchitectAgent

#### 3.2.1 4-Block 映射

| 要素 | 实现 |
|---|---|
| 角色 | Architect Agent（系统架构师），产出架构设计，禁止写实现代码。 |
| 安全边界 | 不写实现代码；不调用 run_command。 |
| 上下文输入 | `state["input"]`、可选 `state["product_manager"]["output"]`、语言模板、工作目录。 |
| 输出格式 | JSON：`{modules, api_contract, tech_stack, mermaid, notes}`，并写入 `design.json`。 |
| 工具 | `write_file`（写 `design.json`）。 |
| 工作流 | 1) 读取 PRD/需求；2) 选择目标技术栈；3) 输出架构 JSON；4) 写入 `design.json`。 |
| 异常处理 | 若 JSON 解析失败，`design_file` 为 `None`，`parsed` 为 `None`。 |

#### 3.2.2 Prompting Specification Template

**# Role/Goal**  
你是 `ArchitectAgent`（系统架构师）。核心任务：把用户需求/PRD 转化为系统架构设计。

**# Inputs & Format**

- 用户需求：`state["input"]`。
- PRD：`state["product_manager"]["output"]`（可选）。
- 目标语言/技术栈：`LangTemplate.display`。
- 工作目录：`state["workspace"]`。

**# Workflow (SOP)**

1. 理解需求与 PRD。
2. 设计关键模块、API 契约、技术选型、Mermaid 架构图。
3. 输出 JSON：`{modules, api_contract, tech_stack, mermaid, notes}`。

**# Constraints & Rules**

- 禁止写实现代码。
- `api_contract` 必须明确输入/输出类型。
- `mermaid` 字段可为空，但建议包含架构图。

**# Exception Handling**

- 若输出不是合法 JSON，`postprocess` 不写入 `design.json`，`parsed` 为 `None`。

#### 3.2.3 实现要点

```python
class ArchitectAgent(BaseAgent):
    json_output = True
    report_schema = DesignOutput
    summary_budget = 2000

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Architect",
            "系统架构师",
            _load_prompt("architect"),
            model=model,
            skills=["system-design", "api-contract", "tech-stack"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        prd = (state.get("product_manager") or {}).get("output", "")
        template = get_language(state)
        return (
            f"目标语言/技术栈：{template.display}\n"
            f"用户需求：{state.get('input', '')}\n"
            f"PRD：{prd[:1500] if prd else '无'}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            "请输出 JSON 格式架构设计：{modules, api_contract, tech_stack, mermaid, notes}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        design = await self._parse_json_output(output, self.report_schema)
        if design:
            await self._write_file("design.json", json.dumps(design, ensure_ascii=False, indent=2), workspace)
        return {"design_file": "design.json" if design else None, "parsed": design}
```

---

### 3.3 DBAAgent

#### 3.3.1 4-Block 映射

| 要素 | 实现 |
|---|---|
| 角色 | DBA Agent（数据库架构师），产出数据库 Schema 与迁移脚本。 |
| 安全边界 | 不写业务代码；仅输出 `.sql` 文件。 |
| 上下文输入 | `state["input"]`、`state["architect"]["output"]`。 |
| 输出格式 | SQL 代码块（`# file: schema.sql` / `# file: migrations/001_initial.sql`）+ JSON `{tables, notes}`。 |
| 工具 | `write_file`。 |
| 工作流 | 1) 读取架构设计；2) 生成 SQL；3) 确保 `.sql` 扩展名；4) 写入文件；5) 提取 JSON。 |
| 异常处理 | 若无代码块，将完整 `output` 写入 `schema.sql`。 |

#### 3.3.2 Prompting Specification Template

**# Role/Goal**  
你是 `DBAAgent`（数据库架构师）。核心任务：根据架构设计产出数据库 Schema 与迁移脚本。

**# Inputs & Format**

- 用户需求：`state["input"]`。
- 架构设计：`state["architect"]["output"]`。
- 工作目录：`state["workspace"]`。

**# Workflow (SOP)**

1. 分析架构设计中的数据实体。
2. 输出 SQL 建表语句、索引、约束。
3. 输出迁移脚本到 `migrations/001_initial.sql`。
4. 输出 JSON `{tables: [...], notes: ""}`。

**# Constraints & Rules**

- 不修改业务代码。
- 所有 SQL 文件以 `.sql` 结尾。
- 表名/字段名必须可执行。

**# Exception Handling**

- 若 LLM 未生成代码块，将完整输出写入 `schema.sql`。
- 若 JSON 缺失，返回空 `tables` 与 `notes`。

#### 3.3.3 实现要点

```python
class DBAAgent(BaseAgent):
    json_output = True
    report_schema = DBAReport
    summary_budget = 1500

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "DBA",
            "数据库架构",
            _load_prompt("dba"),
            model=model,
            skills=["database-design", "schema", "migration"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"原始需求：{state.get('input', '')}\n"
            f"架构设计：{(state.get('architect') or {}).get('output', '')[:2000]}\n"
            "请输出数据库 Schema 与迁移 SQL。必须输出一个合法的 JSON 对象：\n"
            "{\"files\": [{\"path\": \"schema.sql\", \"code\": \"...\"}, {\"path\": \"migrations/001_initial.sql\", \"code\": \"...\"}], "
            "\"report\": {\"tables\": [...], \"notes\": \"\"}}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        files: List[str] = []

        # 优先解析结构化 JSON 输出
        structured = await self._parse_json_output(output, AgentOutput)
        report: Dict[str, Any] = {}
        if structured and "files" in structured and "report" in structured:
            for f in structured.get("files", []):
                path = f.get("path", "")
                code = f.get("code", "")
                if not path:
                    continue
                if not path.endswith(".sql"):
                    path += ".sql"
                res = await self._write_file(path, code, workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(structured.get("report"), self.report_schema) or structured.get("report", {})
        else:
            # 兼容历史/测试中的 Markdown 代码块 + JSON 报告
            blocks = self._extract_code_blocks(output)
            for block in blocks:
                path = block["path"]
                if not path:
                    continue
                if not path.endswith(".sql"):
                    path += ".sql"
                res = await self._write_file(path, block["code"], workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(output, self.report_schema) or {}

        if not files:
            await self._write_file("schema.sql", output, workspace)
            files.append("schema.sql")

        return {
            "files": files,
            "tables": report.get("tables", []),
            "notes": report.get("notes", ""),
        }
```

---

### 3.4 CoderAgent

#### 3.4.1 4-Block 映射

| 要素 | 实现 |
|---|---|
| 角色 | Coder Agent（代码实现引擎），根据架构设计产出可运行代码并自测。 |
| 安全边界 | 不写架构；不部署生产；不执行白名单外命令；生成代码需经 `SafetyScanner.scan_code`。 |
| 上下文输入 | `state["input"]`、`state["architect"]`、`state["dba"]`、`LangTemplate`、工作目录。 |
| 输出格式 | 代码块 `# file: main.<ext>` + JSON `{status, files_modified, test_result, note}`。 |
| 工具 | `read_file`、`write_file`、`run_command`（`template.test_cmd`，最多 3 次）。 |
| 工作流 | 1) 读取现有文件；2) 按模板生成代码；3) 扫描可疑代码；4) 运行测试；5) 输出 JSON 报告。 |
| 异常处理 | 若 MOCK 且无产物，写 `_fallback_code`，状态 `mock_fallback`；测试失败记录 `stderr`。 |

#### 3.4.2 Prompting Specification Template

**# Role/Goal**  
你是 `CoderAgent`（代码实现引擎）。核心任务：根据 `ArchitectAgent` 的架构设计，使用 MCP 工具生成可运行代码，并通过 `pytest` 自测。

**# Inputs & Format**

- 用户需求：`state["input"]`。
- 目标语言/技术栈：`LangTemplate.display`。
- 构建命令：`LangTemplate.build_cmd`；测试命令：`LangTemplate.test_cmd`。
- 文件扩展名：`LangTemplate.file_ext`；测试文件扩展名：`LangTemplate.test_ext`。
- 架构设计：`state["architect"]["output"]`。
- 数据库设计：`state["dba"]["output"]`（可选）。
- 工作目录：`state["workspace"]`。

**# Workflow (SOP)**

1. `read_file` 了解工作目录现有结构。
2. 按 `LangTemplate` 生成代码，每个代码块前 `# file: <path>.<ext>`。
3. 调用 `run_command(template.test_cmd)` 自测，最多重试 3 次。
4. 输出 JSON：`{status, files_modified, test_result, note}`。

**# Constraints & Rules**

- 不得生成架构未提及的功能。
- 若架构提到 API，必须生成 FastAPI 路由。
- 仅允许 `ToolSandbox.ALLOWED_PREFIXES` 内命令。
- 每个产物前必须 `# file: path`。

**# Exception Handling**

- 若上游架构缺失，降级生成，状态 `needs_help`。
- 若 MOCK 模式且未生成文件，调用 `_fallback_code` 写占位代码，状态 `mock_fallback`。
- 若 `run_command` 失败，把 `stderr` 写入 `note`，`test_result` 为 `failed`。

#### 3.4.3 实现要点

```python
class CoderAgent(BaseAgent):
    json_output = True
    report_schema = CoderReport
    summary_budget = 1500

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Coder",
            "代码实现引擎",
            _load_prompt("coder"),
            model=model,
            skills=["code-implementation", "refactor", "python"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        dba_output = (state.get("dba") or {}).get("output", "")
        template = get_language(state)
        json_example = (
            '{"files": [{"path": "main.%s", "code": "..."}], '
            '"report": {"status": "completed", "files_modified": [...], '
            '"test_result": "passed", "note": ""}}'
        ) % template.file_ext
        return (
            f"目标语言/技术栈：{template.display}\n"
            f"构建命令：{template.build_cmd or '无'}\n"
            f"测试命令：{template.test_cmd}\n"
            f"用户生成文件扩展名：.{template.file_ext}，测试文件扩展名：.{template.test_ext}\n"
            f"用户需求：{state.get('input', '')}\n"
            f"架构设计：{(state.get('architect') or {}).get('output', '')[:2000]}\n"
            f"数据库设计：{dba_output[:1500] if dba_output else '无'}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            f"请生成可运行代码。必须输出一个合法的 JSON 对象：\n{json_example}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        template = get_language(state)
        files: List[str] = []
        security_issues: List[Dict[str, Any]] = []

        # 优先解析结构化 JSON 输出（JSON Mode / response_format）
        structured = await self._parse_json_output(output, AgentOutput)
        report: Dict[str, Any] = {}
        if structured and "files" in structured and "report" in structured:
            for f in structured.get("files", []):
                path = f.get("path", "")
                code = f.get("code", "")
                if not path:
                    continue
                if not path.endswith(f".{template.file_ext}"):
                    path += f".{template.file_ext}"
                issues = SafetyScanner.scan_code(code)
                security_issues.extend(issues)
                res = await self._write_file(path, code, workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(structured.get("report"), self.report_schema) or structured.get("report", {})
        else:
            # 兼容历史/测试中的 Markdown 代码块 + JSON 报告
            blocks = self._extract_code_blocks(output)
            for idx, block in enumerate(blocks, start=1):
                path = block["path"]
                if not path:
                    path = f"module_{idx}.{template.file_ext}"
                if not path.endswith(f".{template.file_ext}"):
                    path += f".{template.file_ext}"
                issues = SafetyScanner.scan_code(block["code"])
                security_issues.extend(issues)
                res = await self._write_file(path, block["code"], workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(output, self.report_schema) or {}

        # MOCK 降级：没有真实 LLM 时写一段占位代码，方便 CLI/测试继续跑
        if not files and self.llm.is_mock():
            stub = self._fallback_code(state.get("input", ""), template)
            res = await self._write_file(template.main_file(), stub, workspace)
            if res.get("success"):
                files.append(template.main_file())
            report = {
                "status": "mock_fallback",
                "files_modified": files,
                "test_result": "unknown",
                "note": f"MOCK 模式生成的占位代码 ({template.display})",
            }

        return {
            "files": files,
            "status": report.get("status", "completed" if files else "needs_help"),
            "test_result": report.get("test_result", "unknown"),
            "note": report.get("note", ""),
            "security_issues": security_issues,
        }

    @staticmethod
    def _fallback_code(requirement: str, template: Any) -> str:
        safe = re.sub(r"[^\w\u4e00-\u9fff]+", "_", requirement)[:30].strip("_") or "agent"
        if template.name == "java":
            class_name = safe.capitalize()
            return (
                f"package com.devagent;\n\n"
                f"public class {class_name} {{\n"
                f"    public static void main(String[] args) {{\n"
                f"        System.out.println(\"Hello from {safe}\");\n"
                f"    }}\n"
                f"}}\n"
            )
        if template.name == "go":
            return (
                f"package main\n\n"
                f"import \"fmt\"\n\n"
                f"func main() {{\n"
                f"    fmt.Println(\"Hello from {safe}\")\n"
                f"}}\n"
            )
        if template.name == "typescript":
            return (
                f"console.log(\"Hello from {safe}\");\n"
            )
        return f'"""Generated from requirement: {requirement}"""\n\ndef main():\n    print("Hello from {safe}")\n\nif __name__ == "__main__":\n    main()\n'
```

---

### 3.5 TesterAgent

#### 3.5.1 4-Block 映射

| 要素 | 实现 |
|---|---|
| 角色 | Tester Agent（测试工程师），为 Coder 产物生成并执行测试。 |
| 安全边界 | 不修改源代码；仅生成测试文件；运行白名单测试命令。 |
| 上下文输入 | `state["coder"]["files"]`、`LangTemplate.test_cmd`、工作目录。 |
| 输出格式 | 测试代码块 + JSON `{passed, failed, coverage, report}`。 |
| 工具 | `read_file`、`write_file`、`run_command`。 |
| 工作流 | 1) 读取代码文件；2) 生成测试代码；3) 执行 `test_cmd`；4) 解析 stdout 中 passed/failed；5) 提取 JSON 报告。 |
| 异常处理 | 若未生成测试文件，`test_command_success` 为 `false`，`report` 为 `no tests generated`。 |

#### 3.5.2 Prompting Specification Template

**# Role/Goal**  
你是 `TesterAgent`（测试工程师）。核心任务：为 `CoderAgent` 生成的代码自动生成并执行单元/集成测试。

**# Inputs & Format**

- 目标语言：`LangTemplate.display`。
- 测试框架/命令：`LangTemplate.test_cmd`。
- 测试文件命名：`*.{LangTemplate.test_ext}`。
- 代码文件：`state["coder"]["files"]`，代码片段由 `read_file` 读取。
- 工作目录：`state["workspace"]`。

**# Workflow (SOP)**

1. 读取最多 3 个代码文件内容。
2. 为每个目标生成测试代码块，头部 `# file: test_<name>.<ext>`。
3. 调用 `run_command(f"{test_cmd} -q")`，超时 15 秒。
4. 输出 JSON：`{passed, failed, coverage, report}`。

**# Constraints & Rules**

- 覆盖正常路径与异常路径。
- 失败的用例必须给出最小复现步骤。
- 测试文件扩展名必须符合 `LangTemplate.test_ext`。

**# Exception Handling**

- 若未生成测试文件，返回 `{"passed": 0, "failed": 0, "coverage": 0.0, "report": "no tests generated"}`。
- 若 `test_cmd` 输出无 `passed/failed` 关键字，从 JSON 报告中读取；否则按正则解析。

#### 3.5.3 实现要点

```python
class TesterAgent(BaseAgent):
    json_output = True
    report_schema = TestReport
    summary_budget = 1200

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Tester",
            "测试工程师",
            _load_prompt("tester"),
            model=model,
            skills=["test-generation", "pytest", "coverage"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        workspace = state.get("workspace", "")
        template = get_language(state)
        code_files = (state.get("coder") or {}).get("files", [])
        code_snippets: List[str] = []
        for f in code_files[:3]:
            res = ToolSandbox.read_file(f, base_dir=workspace)  # 同步读取即可
            if res.get("success"):
                code_snippets.append(f"--- {f} ---\n{res['content'][:1500]}")
        json_example = (
            '{"files": [{"path": "test_%s", "code": "..."}], '
            '"report": {"passed": 0, "failed": 0, "coverage": 0.0, "report": ""}}'
        ) % template.file_ext
        return (
            f"目标语言：{template.display}\n"
            f"测试框架/命令：{template.test_cmd}\n"
            f"测试文件命名：*.{template.test_ext}\n"
            f"代码文件：{code_files}\n"
            f"{''.join(code_snippets)[:2500]}\n"
            f"工作目录：{workspace}\n"
            f"请生成对应语言的测试用例。必须输出一个合法的 JSON 对象：\n{json_example}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        template = get_language(state)
        files: List[str] = []

        # 优先解析结构化 JSON 输出
        structured = await self._parse_json_output(output, AgentOutput)
        report: Dict[str, Any] = {}
        if structured and "files" in structured and "report" in structured:
            for f in structured.get("files", []):
                path = f.get("path", "")
                code = f.get("code", "")
                if not path:
                    continue
                if not path.endswith(f".{template.test_ext}"):
                    path += f".{template.test_ext}"
                res = await self._write_file(path, code, workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(structured.get("report"), self.report_schema) or structured.get("report", {})
        else:
            # 兼容历史/测试中的 Markdown 代码块 + JSON 报告
            blocks = self._extract_code_blocks(output)
            for idx, block in enumerate(blocks, start=1):
                path = block["path"]
                if not path:
                    path = f"test_module_{idx}.{template.test_ext}"
                if not path.endswith(f".{template.test_ext}"):
                    path += f".{template.test_ext}"
                res = await self._write_file(path, block["code"], workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(output, self.report_schema) or {}

        if files:
            test_res = await self._run_command(f"{template.test_cmd} -q", workspace, timeout=15)
        else:
            test_res = {"success": False, "stdout": "", "stderr": "no tests generated"}

        passed = report.get("passed")
        failed = report.get("failed")
        if passed is None or failed is None:
            passed, failed = self._parse_test_summary(test_res.get("stdout", ""))

        return {
            "files": files,
            "passed": passed,
            "failed": failed,
            "coverage": report.get("coverage", 0.0),
            "report": (test_res.get("stdout", "") + "\n" + test_res.get("stderr", "")).strip(),
            "test_command_success": test_res.get("success", False),
        }

    @staticmethod
    def _parse_test_summary(stdout: str):
        m = re.search(r"(\d+)\s+passed", stdout)
        passed = int(m.group(1)) if m else 0
        m = re.search(r"(\d+)\s+failed", stdout)
        failed = int(m.group(1)) if m else 0
        return passed, failed
```

---

### 3.6 ReviewerAgent

#### 3.6.1 4-Block 映射

| 要素 | 实现 |
|---|---|
| 角色 | Reviewer Agent（代码审查），从需求出发独立审查代码/测试/文档。 |
| 安全边界 | 不写代码；只输出审查 JSON。 |
| 上下文输入 | `state["input"]`、代码文件、测试报告、文档文件。 |
| 输出格式 | JSON `{severity, passed, issues, suggestions}`，并写入 `review_report.json`。 |
| 工具 | `write_file`。 |
| 工作流 | 1) 读取上游产物；2) 独立审查；3) 输出 JSON；4) 写入 `review_report.json`。 |
| 异常处理 | 若 JSON 解析失败，保守 fallback `passed=False`、`severity="medium"`。 |

#### 3.6.2 Prompting Specification Template

**# Role/Goal**  
你是 `ReviewerAgent`（代码审查）。核心任务：从需求出发独立审查代码、测试、文档，指出 High/Medium/Low 级别问题。

**# Inputs & Format**

- 原始需求：`state["input"]`。
- 代码文件：`state["coder"]["files"]`。
- 测试报告：`state["tester"]["report"]`。
- 文档文件：`state["docs"]["files"]`。

**# Workflow (SOP)**

1. 独立思考，不信任上游输出。
2. 检查设计模式、代码复杂度、安全漏洞、API 契约一致性。
3. 输出 JSON：`{severity, passed, issues, suggestions}`。

**# Constraints & Rules**

- `severity` ∈ `low / medium / high`。
- `issues` 必须是具体、可定位的问题。
- `suggestions` 必须是可执行的改进建议。

**# Exception Handling**

- 若输出无法解析为 JSON，`postprocess` 返回 `{"severity": "medium", "passed": false, "issues": ["Reviewer 输出无法解析为 JSON"], "suggestions": ["请检查 LLM 输出格式"]}`。

#### 3.6.3 实现要点

```python
class ReviewerAgent(BaseAgent):
    json_output = True
    report_schema = ReviewReport
    summary_budget = 1200

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Reviewer",
            "代码审查",
            _load_prompt("reviewer"),
            model=model,
            skills=["code-review", "security", "performance"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"原始需求：{state.get('input', '')}\n"
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            f"测试报告：{(state.get('tester') or {}).get('report', '')[:1200]}\n"
            f"文档文件：{(state.get('docs') or {}).get('files', [])}\n"
            "请独立思考，从需求出发审查。输出 JSON：{severity, passed, issues, suggestions}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        report = await self._parse_json_output(output, self.report_schema)
        if not report:
            # 无法解析 JSON 时做最保守判断
            report = {
                "severity": "medium",
                "passed": False,
                "issues": ["Reviewer 输出无法解析为 JSON"],
                "suggestions": ["请检查 LLM 输出格式"],
            }
        review_file = "review_report.json"
        await self._write_file(review_file, json.dumps(report, ensure_ascii=False, indent=2), workspace)
        report["report_file"] = review_file
        return report
```

---

### 3.7 SecurityAgent

#### 3.7.1 4-Block 映射

| 要素 | 实现 |
|---|---|
| 角色 | Security Agent（安全审查专家），独立审查安全漏洞与合规风险。 |
| 安全边界 | 不写代码；仅输出安全审查 JSON。 |
| 上下文输入 | 需求、代码文件、测试文件、架构设计。 |
| 输出格式 | JSON `{severity, passed, issues, suggestions}`，写入 `security_report.json`。 |
| 工具 | `write_file`。 |
| 工作流 | 同 ReviewerAgent，但聚焦注入、越权、敏感信息泄露、依赖漏洞、不安全的反序列化。 |
| 异常处理 | 同 ReviewerAgent 保守 fallback。 |

#### 3.7.2 Prompting Specification Template

**# Role/Goal**  
你是 `SecurityAgent`（安全审查专家）。核心任务：独立审查代码、测试、文档中的安全漏洞与合规风险。

**# Inputs & Format**

- 原始需求：`state["input"]`。
- 代码文件：`state["coder"]["files"]`。
- 测试文件：`state["tester"]["files"]`。
- 架构设计：`state["architect"]["output"]`。

**# Workflow (SOP)**

1. 独立审查注入、越权、敏感信息泄露、依赖漏洞、不安全反序列化。
2. 输出 JSON：`{severity, passed, issues, suggestions}`。

**# Constraints & Rules**

- 不信任上游输出。
- 必须指出 High/Medium/Low 级别问题。

**# Exception Handling**

- 输出非 JSON 时 fallback：`{"severity": "medium", "passed": false, "issues": ["Security Agent 输出无法解析为 JSON"], "suggestions": [...]}`。

#### 3.7.3 实现要点

```python
class SecurityAgent(BaseAgent):
    json_output = True
    report_schema = ReviewReport
    summary_budget = 1200

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Security",
            "安全审查",
            _load_prompt("security"),
            model=model,
            skills=["security-review", "vulnerability", "compliance"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"原始需求：{state.get('input', '')}\n"
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            f"测试文件：{(state.get('tester') or {}).get('files', [])}\n"
            f"架构设计：{(state.get('architect') or {}).get('output', '')[:1500]}\n"
            "请独立进行安全审查，输出 JSON {severity, passed, issues, suggestions}。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        report = await self._parse_json_output(output, self.report_schema)
        if not report:
            report = {
                "severity": "medium",
                "passed": False,
                "issues": ["Security Agent 输出无法解析为 JSON"],
                "suggestions": ["请检查 LLM 输出格式"],
            }
        report_file = "security_report.json"
        await self._write_file(report_file, json.dumps(report, ensure_ascii=False, indent=2), workspace)
        report["report_file"] = report_file
        return report
```

---

### 3.8 DocsAgent

#### 3.8.1 4-Block 映射

| 要素 | 实现 |
|---|---|
| 角色 | Docs Agent（文档工程师），根据架构与代码生成/更新文档。 |
| 安全边界 | 不写源代码；仅输出 `.md` 文件。 |
| 上下文输入 | `state["architect"]["output"]`、`state["coder"]["files"]`、工作目录。 |
| 输出格式 | Markdown 代码块 `# file: README.md` / `# file: API.md`，写入 `docs/`。 |
| 工具 | `write_file`。 |
| 工作流 | 1) 读取架构与代码文件列表；2) 生成 README/API 文档；3) 确保 `.md` 扩展名；4) 写入 `docs/`。 |
| 异常处理 | 若无代码块，将完整输出写入 `docs/README.md`。 |

#### 3.8.2 Prompting Specification Template

**# Role/Goal**  
你是 `DocsAgent`（文档工程师）。核心任务：根据架构与代码自动生成/更新文档。

**# Inputs & Format**

- 架构：`state["architect"]["output"]`。
- 代码文件：`state["coder"]["files"]`。
- 工作目录：`state["workspace"]`。

**# Workflow (SOP)**

1. 总结关键模块与 API。
2. 生成 `README.md` 与 `API.md`。
3. 所有产物放入 `docs/` 目录。

**# Constraints & Rules**

- 不修改源代码。
- 文档路径以 `.md` 结尾。
- 保持中英文一致。

**# Exception Handling**

- 若 LLM 未生成代码块，将 `output` 写入 `docs/README.md`。

#### 3.8.3 实现要点

```python
class DocsAgent(BaseAgent):
    summary_budget = 800

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Docs",
            "文档工程师",
            _load_prompt("docs"),
            model=model,
            skills=["documentation", "readme", "api-doc"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"架构：{str((state.get('architect') or {}).get('output', ''))[:800]}\n"
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            "请生成 README.md 与 API.md。用代码块标明文件路径，如 '# file: README.md'。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        blocks = self._extract_code_blocks(output)
        files: List[str] = []
        for block in blocks:
            path = block["path"] or "README.md"
            if not path.endswith(".md"):
                path += ".md"
            res = await self._write_file(f"docs/{path}", block["code"], workspace)
            if res.get("success"):
                files.append(f"docs/{path}")
        if not files:
            await self._write_file("docs/README.md", output, workspace)
            files.append("docs/README.md")
        return {"files": files}
```

---

### 3.9 DevOpsAgent

#### 3.9.1 4-Block 映射

| 要素 | 实现 |
|---|---|
| 角色 | DevOps Agent（部署运维），生成 Docker/CI/CD/部署脚本。 |
| 安全边界 | 不直接部署；`postprocess` 返回 `needs_approval=True`；`DevOpsRunner` 默认 `dry_run=True`。 |
| 上下文输入 | `state["coder"]["files"]`。 |
| 输出格式 | Dockerfile / docker-compose.yml / GitHub Actions 代码块 + 部署摘要，返回 `{"files": [...], "needs_approval": True}`。 |
| 工具 | `write_file`。 |
| 工作流 | 1) 读取代码文件；2) 生成部署配置；3) 写入产物；4) 标记需人工确认。 |
| 异常处理 | 若无代码块，写入 `deploy_summary.md`。 |

#### 3.9.2 Prompting Specification Template

**# Role/Goal**  
你是 `DevOpsAgent`（部署运维）。核心任务：为代码生成 Dockerfile、docker-compose.yml、CI/CD 配置，并说明部署前需人工确认。

**# Inputs & Format**

- 代码文件：`state["coder"]["files"]`。
- 工作目录：`state["workspace"]`。

**# Workflow (SOP)**

1. 根据代码文件生成部署配置。
2. 输出 Dockerfile、docker-compose.yml、GitHub Actions 工作流代码块。
3. 说明部署前需人工确认。

**# Constraints & Rules**

- 不直接部署到生产。
- 必须提供 health check 与日志收集建议。
- 涉及生产部署前必须要求人工确认。

**# Exception Handling**

- 若未生成代码块，写入 `deploy_summary.md`。
- `postprocess` 返回 `needs_approval: True`。

#### 3.9.3 实现要点

```python
class DevOpsAgent(BaseAgent):
    summary_budget = 1000

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "DevOps",
            "部署运维",
            _load_prompt("devops"),
            model=model,
            skills=["docker", "ci-cd", "deployment"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            "请生成 Dockerfile、docker-compose.yml 与 CI/CD 配置摘要，并说明部署前需人工确认。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        blocks = self._extract_code_blocks(output)
        files: List[str] = []
        for block in blocks:
            path = block["path"]
            if not path:
                continue
            res = await self._write_file(path, block["code"], workspace)
            if res.get("success"):
                files.append(path)
        if not files:
            await self._write_file("deploy_summary.md", output, workspace)
            files.append("deploy_summary.md")
        return {"files": files, "needs_approval": True}
```

---

## 四、支撑组件生成规范

### 4.1 BaseAgent 抽象

所有业务 Agent 必须继承 `BaseAgent`。生命周期：<ref_file file="dev_agent_system/agents.py" />

1. `__init__`：加载 system prompt、初始化 `LLMClient`、`MemoryAgent`、`MCPToolRegistry`、telemetry；调用 `_register_skills()`。
2. `build_prompt(state)`：子类重写，构造 user prompt。
3. `run(state)`：
   - 创建工作目录 `workspace/<request_id>`。
   - `memory.recall` 拉取工作记忆。
   - 上下文压缩（若超过阈值）。
   - `SecretRedactor.redact` 输入/输出。
   - `ModelRouter.resolve` 选择模型参数。
   - `llm.chat(system, full_prompt, json_mode=self.json_output, ...)`。
   - 记录 telemetry 指标。
   - `postprocess(output, state)`。
   - 调用 `_summarize_result(result)` 把结果压缩为合法 JSON 摘要，替换原始 `output`。
4. `postprocess`：子类重写，解析输出、调用工具、写产物、返回结构化 dict。
5. `_parse_json_output`：Pydantic 校验与 Markdown 内嵌 JSON 兼容解析。
6. `_extract_code_blocks`：解析 ` ``` ` 代码块与 `# file:` 头部。
7. `_summarize_result` / `_truncate_for_summary`：按 `summary_budget` 压缩下游传递状态。

### 4.2 Orchestrator 编排

实现要点：<ref_file file="dev_agent_system/orchestrator.py" />

- `_build_state` 初始化 `GraphState`，包含 `product_manager`/`security`/`dba` 等可选节点字段。
- `_build_graph` 按 `enable_product_manager / enable_dba / enable_security / enable_devops` 动态建图。
- `_should_continue`：
  - 若 Reviewer 未通过且未达 `max_iterations` → `continue`（回到 `architect_node`）。
  - 若启用 Security，Security 未通过也 `continue`。
  - 通过则 `end`；启用 DevOps 且 `DEVOPS_DRY_RUN=false` 时先过 `approval_gate`，再进入 `devops_node`。
- `approve_devops` / `get_approval_status`：与 `HumanApprovalStore` 交互，支持 Server 端点审批。
- `run_stream`：SSE 流式输出 `on_node_start / on_node_end` 事件，异常时降级为普通 `ainvoke`。

### 4.3 工具链

详见 `docs/tools_spec.md`。

### 4.4 配置与模型路由

- `config.py` 统一 `.env` + `config/model.yaml` + `config/mcp.yaml`。`dev_agent_system/config.py`
- `router.py` 根据 `config/model.yaml` 选择模型与生成参数。`dev_agent_system/router.py`

### 4.5 A2A 与 API

- `server.py`：统一 FastAPI 网关，含 `/orchestrate`, `/orchestrate/stream`, `/skills`, `/metrics`, `/dashboard`, `/api/status`, `/tasks/{id}/resume`, `/tasks/{id}/approval`, `/tasks/{id}/approve`, `/tasks/{id}/reject`, `/rpc`。 <ref_file file="dev_agent_system/server.py" />
- `a2a_node.py`：独立启动单个 Agent 服务。`dev_agent_system/a2a_node.py`
- `a2a_client.py`：A2A 客户端。`dev_agent_system/a2a_client.py`

---

## 五、验证策略

| 测试类型 | 范围 | 关键用例 |
|---|---|---|
| 单元测试 | Agent postprocess、安全扫描、路径校验、Skill 管理 | `tests/test_security.py`、`tests/test_skills.py`、`tests/test_multilang.py` |
| 集成测试 | 完整 Orchestrator DAG（MOCK） | `tests/test_flow.py::test_orchestrator_end_to_end` |
| 新 Agent 测试 | ProductManager / Security / DBA | `tests/test_new_agents.py` |
| A2A/Server 测试 | 端点与 Skill 市场 | `tests/test_server.py`、`tests/test_server_skills.py` |
| 安全流水线 | Secret / 依赖漏洞 / 容器沙箱 | `tests/test_security_scanner.py`、调用 `SecurityPipeline.run()` |
| 回归测试 | `tests/eval_dataset.json` 18 条用例 | `python -m dev_agent_system.eval --max-iter 3` / `RegressionChecker` 对比 baseline |

---

---

# 附录
## 附录 A：完整 `prompts.yaml`

```yaml
architect: |
  你是 Architect Agent（系统架构师）。
  职责：把用户需求转化为系统架构设计。
  禁止直接生成实现代码，那是 Coder Agent 的工作。
  输出要求：
    1) 关键模块与边界
    2) API 契约（REST/JSON 或 Protobuf）
    3) 技术选型及利弊分析
    4) Mermaid 架构图
    5) JSON 格式决策记录 {modules, api_contract, tech_stack, mermaid, notes}

coder: |
  你是 Coder Agent（代码实现引擎）。
  职责：根据 Architect 的架构设计产出高质量、可运行的代码。
  规则：
    - 先 read_file 了解现有结构，再写代码
    - 若架构中提到 API 接口，必须生成 FastAPI 路由
    - 写完代码后 run_command("pytest") 验证，最多重试 3 次
    - 不能修改架构文档，不能部署到生产
  输出格式（必须且仅输出合法 JSON）：
    {"files": [{"path": "main.py", "code": "..."}], "report": {"status": "completed", "files_modified": ["main.py"], "test_result": "passed", "note": ""}}

tester: |
  你是 Tester Agent（测试工程师）。
  职责：为 Coder 生成的代码自动生成并执行单元/集成/E2E 测试。
  规则：
    - 优先使用 pytest
    - 覆盖正常路径与异常路径
    - 失败的用例必须给出最小复现步骤
  输出格式（必须且仅输出合法 JSON）：
    {"files": [{"path": "test_main.py", "code": "..."}], "report": {"passed": 0, "failed": 0, "coverage": 0.0, "report": ""}}

reviewer: |
  你是 Reviewer Agent（代码审查）。
  职责：从需求出发独立审查代码、测试、文档。
  关键指令：
    - 独立思考，不信任上游输出
    - 检查设计模式、代码复杂度、安全漏洞、API 契约一致性
    - 必须指出 High/Medium/Low 级别问题
  输出格式：JSON {severity, passed, issues, suggestions}

docs: |
  你是 Docs Agent（文档工程师）。
  职责：根据架构与代码自动生成/更新文档。
  规则：
    - 生成 README、API 文档与 CHANGELOG 摘要
    - 禁止修改源代码
    - 保持中英文一致

devops: |
  你是 DevOps Agent（部署运维）。
  职责：构建 Docker 镜像、CI/CD 流水线与部署脚本。
  规则：
    - 生成 Dockerfile、docker-compose.yml、GitHub Actions 工作流
    - 涉及部署到生产前必须要求人工确认
    - 提供 health check 与日志收集建议

product_manager: |
  你是 Product Manager Agent（产品经理）。
  职责：把模糊的用户需求拆分为清晰的产品需求文档（PRD）、用户故事与验收标准。
  规则：
    - 不直接写实现代码或架构设计
    - 识别需求中的歧义并给出假设
    - 输出 PRD 文档、用户故事列表、验收标准
  输出格式：
    代码块 '# file: prd.md' 包含 PRD 正文
    JSON {user_stories: [...], acceptance_criteria: [...]}

security: |
  你是 Security Agent（安全审查专家）。
  职责：独立审查代码、测试、文档中的安全漏洞与合规风险。
  关键指令：
    - 独立思考，不信任上游输出
    - 检查注入、越权、敏感信息泄露、依赖漏洞、不安全的反序列化
    - 必须指出 High/Medium/Low 级别问题
  输出格式：JSON {severity, passed, issues, suggestions}

dba: |
  你是 DBA Agent（数据库架构师）。
  职责：根据架构设计产出数据库 Schema 与迁移脚本。
  规则：
    - 输出 SQL 建表语句、索引、约束
    - 提供 migrations/001_initial.sql 等可执行迁移脚本
    - 不修改业务代码
  输出格式（必须且仅输出合法 JSON）：
    {"files": [{"path": "schema.sql", "code": "..."}, {"path": "migrations/001_initial.sql", "code": "..."}], "report": {"tables": [], "notes": ""}}
```

## 附录 B：完整 `agent_cards.json`

```json
{
  "architect": {
    "name": "Architect Agent",
    "url": "http://localhost:8000/architect",
    "skills": [
      {"name": "system-design"},
      {"name": "api-contract"},
      {"name": "tech-stack"}
    ],
    "capabilities": {"streaming": false, "autonomy": "L2", "modalities": ["text", "code"]}
  },
  "coder": {
    "name": "Coder Agent",
    "url": "http://localhost:8000/coder",
    "skills": [
      {"name": "code-implementation"},
      {"name": "refactor"},
      {"name": "python"}
    ],
    "capabilities": {"streaming": false, "autonomy": "L2", "modalities": ["text", "code"]}
  },
  "tester": {
    "name": "Tester Agent",
    "url": "http://localhost:8000/tester",
    "skills": [
      {"name": "test-generation"},
      {"name": "pytest"},
      {"name": "coverage"}
    ],
    "capabilities": {"streaming": false, "autonomy": "L3", "modalities": ["text"]}
  },
  "reviewer": {
    "name": "Reviewer Agent",
    "url": "http://localhost:8000/reviewer",
    "skills": [
      {"name": "code-review"},
      {"name": "security"},
      {"name": "performance"}
    ],
    "capabilities": {"streaming": false, "autonomy": "L2", "modalities": ["text", "code"]}
  },
  "docs": {
    "name": "Docs Agent",
    "url": "http://localhost:8000/docs",
    "skills": [
      {"name": "documentation"},
      {"name": "readme"},
      {"name": "api-doc"}
    ],
    "capabilities": {"streaming": false, "autonomy": "L3", "modalities": ["text"]}
  },
  "devops": {
    "name": "DevOps Agent",
    "url": "http://localhost:8000/devops",
    "skills": [
      {"name": "docker"},
      {"name": "ci-cd"},
      {"name": "deployment"}
    ],
    "capabilities": {"streaming": false, "autonomy": "L2", "modalities": ["text", "code"]}
  },
  "product_manager": {
    "name": "Product Manager Agent",
    "url": "http://localhost:8000/product_manager",
    "skills": [
      {"name": "requirement-analysis"},
      {"name": "prd"},
      {"name": "user-stories"}
    ],
    "capabilities": {"streaming": false, "autonomy": "L2", "modalities": ["text"]}
  },
  "security": {
    "name": "Security Agent",
    "url": "http://localhost:8000/security",
    "skills": [
      {"name": "security-review"},
      {"name": "vulnerability"},
      {"name": "compliance"}
    ],
    "capabilities": {"streaming": false, "autonomy": "L2", "modalities": ["text", "code"]}
  },
  "dba": {
    "name": "DBA Agent",
    "url": "http://localhost:8000/dba",
    "skills": [
      {"name": "database-design"},
      {"name": "schema"},
      {"name": "migration"}
    ],
    "capabilities": {"streaming": false, "autonomy": "L2", "modalities": ["text", "code"]}
  }
}
```

## 附录 C：A2A 与内部状态数据模型（`schemas.py` 全文）

```python
"""A2A 协议与内部状态数据模型。"""
from __future__ import annotations

import typing
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class AgentSkill(BaseModel):
    name: str


class AgentCard(BaseModel):
    name: str
    url: str
    skills: List[AgentSkill]
    capabilities: Dict[str, Any] = Field(default_factory=dict)


class Task(BaseModel):
    description: str
    task_id: Optional[str] = None
    request_id: Optional[str] = None
    max_iterations: Optional[int] = None
    language: Optional[str] = "python"
    payload: Optional[Dict[str, Any]] = Field(default_factory=dict)


class TaskResponse(BaseModel):
    status: Literal["submitted", "working", "completed", "failed", "skipped", "awaiting_approval"] = "submitted"
    task_id: str
    result: Optional[Any] = None


class JSONRPCRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    method: str
    params: Any
    id: str


class JSONRPCResponse(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    result: Any
    id: str


class CoderReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["completed", "needs_help"] = "completed"
    files_modified: List[str] = Field(default_factory=list)
    test_result: Literal["passed", "failed"] = "failed"
    note: Optional[str] = None


class ReviewReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    severity: Literal["low", "medium", "high"] = "low"
    passed: bool = False
    issues: List[Dict[str, Any]] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)


class TestReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    passed: int = 0
    failed: int = 0
    coverage: float = 0.0
    report: str = ""


class WorkflowState(BaseModel):
    request_id: str
    input: str
    language: Optional[str] = "python"
    iteration: int = 0
    max_iterations: int = 10
    status: Literal["submitted", "working", "completed", "failed", "awaiting_approval"] = "submitted"
    architect: Optional[Dict[str, Any]] = None
    coder: Optional[Dict[str, Any]] = None
    tester: Optional[Dict[str, Any]] = None
    docs: Optional[Dict[str, Any]] = None
    reviewer: Optional[Dict[str, Any]] = None
    devops: Optional[Dict[str, Any]] = None
    artifacts: Dict[str, Any] = Field(default_factory=dict)


class AgentFile(BaseModel):
    """结构化输出中的单个文件对象。"""

    path: str
    code: str = ""


class AgentOutput(BaseModel):
    """结构化 Agent 输出：文件列表 + 报告字典。"""

    model_config = ConfigDict(extra="forbid")

    files: List[AgentFile] = Field(default_factory=list)
    report: Dict[str, Any] = Field(default_factory=dict)


class DesignOutput(BaseModel):
    """Architect Agent 的 JSON 输出。"""

    model_config = ConfigDict(extra="ignore")

    modules: List[str] = Field(default_factory=list)
    api_contract: Dict[str, Any] = Field(default_factory=dict)
    tech_stack: str = ""
    mermaid: str = ""
    notes: str = ""


class DBAReport(BaseModel):
    """DBA Agent 的 JSON 报告。"""

    model_config = ConfigDict(extra="ignore")

    tables: List[str] = Field(default_factory=list)
    notes: str = ""


class PRDOutput(BaseModel):
    """Product Manager Agent 的 JSON 输出。"""

    model_config = ConfigDict(extra="ignore")

    prd_markdown: str = ""
    user_stories: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)


class GraphState(typing.TypedDict, total=False):
    """LangGraph 状态图使用的状态类型（TypedDict，便于字段部分更新）。"""

    request_id: str
    input: str
    language: Optional[str]
    workspace: str
    iteration: int
    max_iterations: int
    status: str
    architect: Optional[Dict[str, Any]]
    coder: Optional[Dict[str, Any]]
    tester: Optional[Dict[str, Any]]
    docs: Optional[Dict[str, Any]]
    reviewer: Optional[Dict[str, Any]]
    devops: Optional[Dict[str, Any]]
    product_manager: Optional[Dict[str, Any]]
    security: Optional[Dict[str, Any]]
    dba: Optional[Dict[str, Any]]
    memory: Optional[Dict[str, Any]]
    history: List[Dict[str, Any]]
    artifacts: Dict[str, Any]
    finished_at: Optional[str]


class GraphStateModel(BaseModel):
    """GraphState 的 Pydantic 校验模型，用于启动工作流前做强类型校验。

    保持 `extra="allow"` 以兼容 LangGraph 在运行中注入的额外通道字段，
    同时确保核心字段类型、状态枚举一致。
    """

    model_config = ConfigDict(extra="allow")

    request_id: str
    input: str = ""
    language: Optional[str] = "python"
    workspace: Optional[str] = None
    iteration: int = 0
    max_iterations: int = 10
    status: Literal["submitted", "working", "completed", "failed", "awaiting_approval"] = "submitted"
    architect: Optional[Dict[str, Any]] = None
    coder: Optional[Dict[str, Any]] = None
    tester: Optional[Dict[str, Any]] = None
    docs: Optional[Dict[str, Any]] = None
    reviewer: Optional[Dict[str, Any]] = None
    devops: Optional[Dict[str, Any]] = None
    product_manager: Optional[Dict[str, Any]] = None
    security: Optional[Dict[str, Any]] = None
    dba: Optional[Dict[str, Any]] = None
    memory: Optional[Dict[str, Any]] = None
    history: List[Dict[str, Any]] = Field(default_factory=list)
    artifacts: Dict[str, Any] = Field(default_factory=dict)
    finished_at: Optional[str] = None
```

## 附录 D：多语言项目模板（`templates.py` 全文）

```python
"""多语言项目模板与工具链定义。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class LangTemplate:
    """描述一种编程语言的文件约定、默认产物与常用命令。"""

    name: str
    display: str
    file_ext: str
    test_ext: str
    build_cmd: str
    test_cmd: str
    package_file: Optional[str] = None
    default_files: Dict[str, str] = field(default_factory=dict)
    allowed_commands: List[str] = field(default_factory=list)

    def main_file(self, name: str = "main") -> str:
        if self.name == "java":
            return f"{name.capitalize()}.{self.file_ext}"
        return f"{name}.{self.file_ext}"

    def test_file(self, name: str = "main") -> str:
        if self.name == "python":
            return f"test_{name}.{self.file_ext}"
        if self.name == "go":
            return f"{name}_test.{self.file_ext}"
        if self.name == "java":
            return f"{name.capitalize()}Test.{self.file_ext}"
        if self.name == "typescript":
            return f"{name}.test.ts"
        return f"{name}_test.{self.test_ext}"


TEMPLATES: Dict[str, LangTemplate] = {
    "python": LangTemplate(
        name="python",
        display="Python",
        file_ext="py",
        test_ext="py",
        build_cmd="",
        test_cmd="pytest",
        package_file="requirements.txt",
        default_files={
            "requirements.txt": "# Auto-generated dependencies\n",
        },
        allowed_commands=["python", "pytest"],
    ),
    "java": LangTemplate(
        name="java",
        display="Java",
        file_ext="java",
        test_ext="java",
        build_cmd="mvn compile",
        test_cmd="mvn test",
        package_file="pom.xml",
        default_files={
            "pom.xml": """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.devagent</groupId>
  <artifactId>generated</artifactId>
  <version>1.0-SNAPSHOT</version>
  <properties>
    <maven.compiler.source>17</maven.compiler.source>
    <maven.compiler.target>17</maven.compiler.target>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.junit.jupiter</groupId>
      <artifactId>junit-jupiter</artifactId>
      <version>5.10.0</version>
      <scope>test</scope>
    </dependency>
  </dependencies>
</project>
""",
        },
        allowed_commands=["mvn", "javac", "java"],
    ),
    "go": LangTemplate(
        name="go",
        display="Go",
        file_ext="go",
        test_ext="go",
        build_cmd="go build ./...",
        test_cmd="go test ./...",
        package_file="go.mod",
        default_files={
            "go.mod": "module generated\n\ngo 1.21\n",
        },
        allowed_commands=["go"],
    ),
    "typescript": LangTemplate(
        name="typescript",
        display="TypeScript",
        file_ext="ts",
        test_ext="test.ts",
        build_cmd="npx tsc",
        test_cmd="npm test",
        package_file="package.json",
        default_files={
            "package.json": """{
  "name": "generated",
  "version": "1.0.0",
  "scripts": {
    "test": "jest",
    "build": "tsc"
  },
  "devDependencies": {
    "@types/node": "^20.0.0",
    "jest": "^29.0.0",
    "typescript": "^5.3.0"
  }
}
""",
        },
        allowed_commands=["npm", "npx", "node"],
    ),
}


def get_language(state_or_language) -> LangTemplate:
    """从 state 或字符串解析目标语言模板，默认 Python。"""
    if isinstance(state_or_language, str):
        lang = state_or_language.lower().strip()
    elif isinstance(state_or_language, dict):
        lang = (state_or_language.get("language") or "python").lower().strip()
    else:
        lang = "python"
    return TEMPLATES.get(lang, TEMPLATES["python"])


def list_languages() -> List[str]:
    return list(TEMPLATES.keys())
```

## 附录 E：MCP 工具沙箱与注册中心（`mcp.py` 全文）

```python
"""MCP 风格工具注册与沙箱。"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from dev_agent_system.security import PathValidator, SafetyScanner
from dev_agent_system.security_scanner import ContainerSandbox


class ToolSandbox:
    """MCP 工具沙箱：白名单 + 安全扫描 + 路径限制 + 超时。"""

    ALLOWED_PREFIXES = (
        "python", "pytest", "git", "ls", "cat", "echo", "docker build",
        "mvn", "gradle", "javac", "java", "go", "npm", "npx", "node",
    )
    WORK_DIR = Path("workspace").resolve()

    _write_lock = asyncio.Lock()

    @classmethod
    def read_file(cls, path: str, base_dir: Optional[str] = None) -> Dict[str, Any]:
        work = Path(base_dir).resolve() if base_dir else cls.WORK_DIR
        try:
            target = PathValidator.resolve(work, path)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        if not target.exists():
            return {"success": False, "error": "文件不存在"}
        try:
            return {"success": True, "content": target.read_text(encoding="utf-8")}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "error": str(e)}

    @classmethod
    async def write_file(
        cls, path: str, content: str, base_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        async with cls._write_lock:
            work = Path(base_dir).resolve() if base_dir else cls.WORK_DIR
            try:
                target = PathValidator.resolve(work, path)
            except ValueError as exc:
                return {"success": False, "error": str(exc)}
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                return {"success": True, "path": str(target)}
            except Exception as e:  # noqa: BLE001
                return {"success": False, "error": str(e)}

    @classmethod
    def run_command(cls, command: str, timeout: int = 5, base_dir: Optional[str] = None) -> Dict[str, Any]:
        if not command:
            return {"success": False, "error": "空命令"}
        safe, issues = SafetyScanner.scan_command(command)
        if not safe:
            return {"success": False, "error": f"命令命中安全规则：{', '.join(issues)}"}

        inline_safe, inline_issues = SafetyScanner.inspect_command(command)
        if not inline_safe:
            return {"success": False, "error": f"命令内嵌代码风险：{', '.join(inline_issues)}"}

        if not any(command.strip().startswith(prefix) for prefix in cls.ALLOWED_PREFIXES):
            return {"success": False, "error": f"仅允许以 {cls.ALLOWED_PREFIXES} 开头的命令"}
        work = Path(base_dir).resolve() if base_dir else cls.WORK_DIR

        # 如果启用容器沙箱且 Docker 可用，优先在隔离容器中执行
        if Settings.use_container_sandbox() and ContainerSandbox.is_available():
            try:
                return ContainerSandbox.run(command, work, image=Settings.container_image(), timeout=timeout)
            except Exception as e:  # noqa: BLE001
                return {"success": False, "error": f"容器沙箱执行失败: {e}"}

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=work,
            )
            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"命令执行超过 {timeout} 秒"}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "error": str(e)}


from dev_agent_system.config import Settings


ToolSandbox.WORK_DIR = Settings.workspace_dir()


class MCPToolRegistry:
    """MCP 工具注册中心。"""

    def __init__(self):
        self._tools: Dict[str, Callable[..., Any]] = {
            "read_file": ToolSandbox.read_file,
            "write_file": ToolSandbox.write_file,
            "run_command": ToolSandbox.run_command,
        }

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        self._tools[name] = fn

    def call(self, name: str, **kwargs) -> Any:
        """同步入口：仅调用同步工具；异步工具应使用 ainvoke。"""
        if name not in self._tools:
            return {"success": False, "error": f"未知工具: {name}"}
        fn = self._tools[name]
        if asyncio.iscoroutinefunction(fn):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(fn(**kwargs))
            return {
                "success": False,
                "error": f"工具 {name} 是异步的，请在异步上下文中调用 ainvoke",
            }
        try:
            return fn(**kwargs)
        except Exception as e:  # noqa: BLE001
            return {"success": False, "error": str(e)}

    async def ainvoke(self, name: str, **kwargs) -> Any:
        """异步调用工具，同步工具在后台线程执行，避免阻塞事件循环。"""
        if name not in self._tools:
            return {"success": False, "error": f"未知工具: {name}"}
        fn = self._tools[name]
        try:
            if asyncio.iscoroutinefunction(fn):
                return await fn(**kwargs)
            # 同步工具（如 subprocess.run）在后台线程执行，避免阻塞 async 编排器
            return await asyncio.to_thread(fn, **kwargs)
        except Exception as e:  # noqa: BLE001
            return {"success": False, "error": str(e)}

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": n, "doc": (fn.__doc__ or "")[:120]}
            for n, fn in self._tools.items()
        ]
```

## 附录 F：安全扫描与脱敏（`security.py` 全文）

```python
"""安全与沙箱加固：命令、路径、敏感信息校验与脱敏。"""
from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any, Dict, List, Tuple


class SafetyScanner:
    """命令与代码安全扫描器。"""

    # 命中即拦截的危险命令模式
    DANGEROUS_COMMAND_PATTERNS: List[Tuple[str, str]] = [
        (r"\brm\s+-rf\b", "递归强制删除"),
        (r"\bsudo\b", "提升权限执行"),
        (r"\bcurl\b.+\|\s*(sh|bash|zsh)\b", "管道执行远程脚本"),
        (r"\bwget\b.*-O-\b", "wget 输出到管道"),
        (r"\beval\s*\(", "eval 执行"),
        (r"\bexec\s*\(", "exec 执行"),
        (r">\s*/dev/null\s*;\s*", "重定向掩盖命令"),
        (r"&&\s*rm\b", "组合删除"),
        (r"\|\s*sh\b", "管道到 sh"),
        (r"\bshutdown\b", "关机命令"),
        (r"\bmkfs\b", "格式化文件系统"),
        (r"\bdd\s+if=", "dd 裸写设备"),
        (r"\bchmod\s+.*777\b", "过度授权"),
        (r"\bwget\s+.*-O\s*-\b", "wget 输出到标准输出"),
        (r";\s*rm\b", "分号后删除"),
    ]

    # 代码中需要告警的可疑模式（不直接拦截，仅返回风险列表）
    SUSPICIOUS_CODE_PATTERNS: List[Tuple[str, str, str]] = [
        (r"\beval\s*\(", "eval 执行", "high"),
        (r"\bexec\s*\(", "exec 执行", "high"),
        (r"\bcompile\s*\(", "动态编译", "high"),
        (r"__import__\s*\(", "动态导入", "high"),
        (r"\bimportlib\b", "importlib 动态加载", "medium"),
        (r"\bos\.system\b", "os.system 调用", "high"),
        (r"\bsubprocess\.", "subprocess 调用", "medium"),
        (r"\bsocket\.", "socket 网络操作", "medium"),
        (r"\burllib\.request\b", "urllib 网络请求", "medium"),
        (r"\brequests\.", "requests 网络请求", "low"),
        (r"\bpty\.", "pty 伪终端", "high"),
        (r"open\s*\(\s*[\"/]etc/", "读取系统配置文件", "high"),
        (r"open\s*\(\s*[\"/]proc/", "读取 proc 文件系统", "high"),
    ]

    @classmethod
    def scan_command(cls, command: str) -> Tuple[bool, List[str]]:
        """扫描命令字符串，返回 (是否安全, 命中的风险描述列表)。"""
        issues: List[str] = []
        if not command:
            return True, issues
        lower = command.lower()
        for pattern, reason in cls.DANGEROUS_COMMAND_PATTERNS:
            if re.search(pattern, lower, re.I):
                issues.append(reason)
        return not issues, list(set(issues))

    @classmethod
    def is_safe_command(cls, command: str) -> bool:
        safe, _ = cls.scan_command(command)
        return safe

    @classmethod
    def inspect_command(cls, command: str) -> Tuple[bool, List[str]]:
        """解析命令中内嵌的代码片段（如 python -c），用 scan_code 做二次扫描。

        返回 (是否安全, 风险描述列表)。当前只对 python -c 内联脚本做检测，
        命中 high/medium 风险即拦截。
        """
        try:
            tokens = shlex.split(command)
        except ValueError:
            return True, []
        for i, token in enumerate(tokens[:-1]):
            if token in ("-c", "--command"):
                snippet = tokens[i + 1]
                findings = cls.scan_code(snippet)
                issues = [
                    f"内联代码风险：{f['reason']}({f['severity']})"
                    for f in findings
                    if f["severity"] in ("high", "medium")
                ]
                return not issues, list(set(issues))
        return True, []

    @classmethod
    def scan_code(cls, code: str) -> List[Dict[str, Any]]:
        """扫描代码片段中的可疑模式，返回风险项列表（不直接拦截）。"""
        issues: List[Dict[str, Any]] = []
        seen: set = set()
        for pattern, reason, severity in cls.SUSPICIOUS_CODE_PATTERNS:
            for m in re.finditer(pattern, code, re.I):
                key = (m.group(0), reason)
                if key in seen:
                    continue
                seen.add(key)
                issues.append(
                    {
                        "line": code[: m.start()].count("\n") + 1,
                        "match": m.group(0),
                        "reason": reason,
                        "severity": severity,
                    }
                )
        return issues


class PathValidator:
    """工作目录内路径校验，防止目录穿越与越界访问。"""

    @staticmethod
    def resolve(base_dir: Path, relative_path: str) -> Path:
        """将 relative_path 解析为 base_dir 下的安全绝对路径。"""
        base = Path(base_dir).resolve()
        # 阻止空路径与纯 .. 路径
        if not relative_path or relative_path.strip() in ("", ".", ".."):
            raise ValueError("无效路径")
        target = (base / relative_path).resolve()
        # 再次检查 resolve 后的结果仍在 base 下
        try:
            target.relative_to(base)
        except ValueError as exc:
            raise ValueError("路径越界：禁止访问工作目录之外") from exc
        return target

    @staticmethod
    def is_within(base_dir: Path, target: Path) -> bool:
        """判断 target 是否位于 base_dir 下。"""
        try:
            Path(target).resolve().relative_to(Path(base_dir).resolve())
            return True
        except ValueError:
            return False


class SecretRedactor:
    """敏感信息脱敏器。"""

    PATTERNS: List[Tuple[str, str]] = [
        (r"sk-[a-zA-Z0-9]{20,}", "[API_KEY_REDACTED]"),
        (r"\b(?:api[_-]?key|apikey|token|secret|access[_-]?key)\s*[:=]\s*[A-Za-z0-9_\-]{8,}", "[SECRET_REDACTED]"),
        (r"1[3-9]\d{9}", "[PHONE_REDACTED]"),
        (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[EMAIL_REDACTED]"),
        (r"password\s*[:=]\s*\S+", "password=[REDACTED]"),
    ]

    @classmethod
    def redact(cls, text: str) -> str:
        if not text:
            return text
        result = text
        for pattern, replacement in cls.PATTERNS:
            result = re.sub(pattern, replacement, result, flags=re.I)
        return result
```

## 附录 G：三层记忆实现（`memory.py` 全文）

```python
"""Memory Agent：三层记忆（短期/工作/长期）与上下文压缩。

主要改进：
- 统一召回语义：SQLite/Redis/Chroma 都支持 query，按「关键词 + 时效 + 语义」混合打分，
  不再因后端不同而在「最近 N 条」和「语义最相关」之间行为突变。
- SQLite 引入 fts5 全文索引（若可用）做大规模关键词召回，否则降级为 Python 关键词匹配。
- 生命周期治理：TTL 过期清理、按容量上限驱逐最旧记忆，写后即时整理。
- 并发安全：SQLite 后端使用 threading 锁 + WAL；MemoryAgent 提供 aremember/arecall，
  在 async 编排器中通过 asyncio.to_thread + asyncio.Lock 避免阻塞和竞争。
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple

from dev_agent_system.config import Settings


def _value_to_text(value: Any) -> str:
    """把任意 value 转成可搜索的文本。"""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        return str(value)


def _tokenize(text: str) -> List[str]:
    """简单分词：保留字母数字词，并把非 ASCII 字符单独切分（用于中文等）。"""
    text = (text or "").lower()
    tokens: List[str] = re.findall(r"[a-z0-9]+", text)
    tokens.extend(ch for ch in text if ord(ch) > 127 and not ch.isspace())
    return tokens


def _keyword_score(query: str, key: str, value: Any) -> float:
    """基于 query 与 key/value 文本的命中情况计算 0-1 的关键词分。"""
    query = (query or "").strip()
    if not query:
        return 1.0
    terms = set(_tokenize(query))
    if not terms:
        return 1.0
    text = _value_to_text(value)
    full_text = f"{key} {text}".lower()
    matched = sum(1 for term in terms if term in full_text)
    tf = sum(full_text.count(term) for term in terms)
    idf_part = matched / len(terms)
    tf_part = min(1.0, tf / (len(terms) * 3 + 1))
    return min(1.0, idf_part * 0.7 + tf_part * 0.3)


def _recency_score(created_at: float, now: Optional[float] = None) -> float:
    """时效分：越近越高，24 小时大约衰减到 0.37。"""
    now = now or time.time()
    hours = (now - created_at) / 3600.0
    return math.exp(-hours / 24.0)


def _combine_scores(
    keyword: float,
    recency: float,
    semantic: float = 0.0,
    has_semantic: bool = False,
) -> float:
    """混合召回打分。有语义时三者加权；无语义时关键词+时效。"""
    if has_semantic:
        return 0.4 * semantic + 0.35 * keyword + 0.25 * recency
    return 0.6 * keyword + 0.4 * recency


def _score_candidate(
    query: str,
    key: str,
    value: Any,
    created_at: float,
    semantic: float = 0.0,
    has_semantic: bool = False,
) -> float:
    """对单个候选记忆打分。"""
    query = (query or "").strip()
    if not query:
        return _recency_score(created_at)
    kw = _keyword_score(query, key, value)
    rec = _recency_score(created_at)
    return _combine_scores(kw, rec, semantic, has_semantic)


class ContextCompressor:
    """基于字符数的简单上下文压缩：保留头部与尾部，中间省略。"""

    def __init__(self, max_chars: int = 8000, reserve_head: int = 2000):
        self.max_chars = max_chars
        self.reserve_head = reserve_head

    def compress(self, text: str) -> str:
        if len(text) <= self.max_chars:
            return text
        head = text[: self.reserve_head]
        tail = text[-(self.max_chars - self.reserve_head) :]
        return (
            head
            + "\n\n... [上下文压缩：中间内容已省略] ...\n\n"
            + tail
        )

    def compress_messages(self, messages: List[Dict[str, Any]], max_messages: int = 10) -> List[Dict[str, Any]]:
        """保留最近 max_messages 条记忆。"""
        return messages[-max_messages:]


class MemoryBackend(Protocol):
    """记忆后端协议。"""

    def remember(
        self,
        key: str,
        value: Any,
        session_id: str,
        layer: str,
        ttl: Optional[int] = None,
    ) -> None:
        ...

    def recall(
        self,
        query: str,
        session_id: str,
        layer: str,
        top_k: int = 3,
        max_candidates: int = 100,
    ) -> List[Dict[str, Any]]:
        ...

    def delete_expired(
        self,
        session_id: Optional[str] = None,
        layer: Optional[str] = None,
    ) -> int:
        """删除过期记忆，返回删除数量。"""
        ...

    def evict_oldest(
        self,
        session_id: str,
        layer: str,
        max_entries: int,
    ) -> int:
        """按最旧优先驱逐，保留最多 max_entries 条，返回删除数量。"""
        ...

    def close(self) -> None:
        ...


class SQLiteMemoryBackend:
    """SQLite 降级实现：支持关键词/时效混合召回、TTL、容量驱逐、线程安全。

    当 Python sqlite3 编译了 fts5 扩展时，会自动创建 `memory_fts` 虚拟表做全文索引，
    把关键词召回从 O(N) 的 Python 扫描降到索引查询；若不可用则透明降级。
    """

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(
            str(self.base_dir / "memory.db"),
            check_same_thread=False,
            timeout=10.0,
        )
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=5000")
        self._fts5_enabled = False
        self._init_tables()

    def _init_tables(self) -> None:
        with self._lock:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS memory ("
                "id TEXT PRIMARY KEY, session_id TEXT, layer TEXT, key TEXT, "
                "value TEXT, created_at REAL, expires_at REAL)"
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_layer_session ON memory(layer, session_id)"
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_created_at ON memory(created_at)"
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_expires_at ON memory(expires_at)"
            )
            try:
                self._db.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(memory_id UNINDEXED, content)"
                )
                self._fts5_enabled = True
            except sqlite3.OperationalError:
                self._fts5_enabled = False
            self._db.commit()

    def _searchable_text(self, key: str, value: Any) -> str:
        return f"{key} {_value_to_text(value)}"

    def _build_fts_query(self, query: str) -> str:
        """把 query 转换成 fts5 MATCH 表达式，支持中英文混合。"""
        tokens = _tokenize(query)
        escaped = []
        for token in tokens:
            token = token.replace('"', '""')
            escaped.append(f'"{token}"')
        return " ".join(escaped)

    def _index_in_fts(self, memory_id: str, key: str, value: Any) -> None:
        if not self._fts5_enabled:
            return
        with self._lock:
            text = self._searchable_text(key, value)
            self._db.execute(
                "INSERT INTO memory_fts(memory_id, content) VALUES (?, ?)",
                (memory_id, text),
            )

    def _delete_from_fts(self, memory_ids: List[str]) -> None:
        if not self._fts5_enabled or not memory_ids:
            return
        with self._lock:
            self._db.executemany(
                "DELETE FROM memory_fts WHERE memory_id = ?",
                [(mid,) for mid in memory_ids],
            )

    def _fts_candidate_ids(
        self,
        query: str,
        limit: int,
    ) -> List[str]:
        """使用 fts5 检索候选 memory_id；不可用或失败时返回空列表。"""
        if not self._fts5_enabled or not query.strip():
            return []
        match_expr = self._build_fts_query(query)
        if not match_expr:
            return []
        try:
            with self._lock:
                cursor = self._db.execute(
                    "SELECT memory_id FROM memory_fts WHERE memory_fts MATCH ? LIMIT ?",
                    (match_expr, limit),
                )
                return [row[0] for row in cursor.fetchall()]
        except sqlite3.OperationalError:
            return []

    def _select_ids(
        self,
        where: str,
        params: Tuple[Any, ...],
    ) -> List[str]:
        with self._lock:
            cursor = self._db.execute(
                f"SELECT id FROM memory WHERE {where}",
                params,
            )
            return [row[0] for row in cursor.fetchall()]

    def remember(
        self,
        key: str,
        value: Any,
        session_id: str,
        layer: str,
        ttl: Optional[int] = None,
    ) -> None:
        now = time.time()
        expires = now + ttl if ttl else 0
        memory_id = str(uuid.uuid4())
        with self._lock:
            self._db.execute(
                "INSERT INTO memory (id, session_id, layer, key, value, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (memory_id, session_id, layer, key, json.dumps(value, ensure_ascii=False), now, expires),
            )
            self._index_in_fts(memory_id, key, value)
            self._db.commit()

    def recall(
        self,
        query: str,
        session_id: str,
        layer: str,
        top_k: int = 3,
        max_candidates: int = 100,
    ) -> List[Dict[str, Any]]:
        now = time.time()
        candidate_ids: set = set()

        # 1. 先按时效取一批最近候选，保证空 query 和 keywords 召回都有覆盖
        recency_limit = max(max_candidates, top_k * 3)
        with self._lock:
            cursor = self._db.execute(
                "SELECT id, key, value, created_at FROM memory WHERE session_id=? AND layer=? "
                "AND (expires_at=0 OR expires_at>?) ORDER BY created_at DESC LIMIT ?",
                (session_id, layer, now, recency_limit),
            )
            recency_rows = [
                {"id": row[0], "key": row[1], "value": json.loads(row[2]) if row[2] else row[2], "created_at": row[3]}
                for row in cursor.fetchall()
            ]
        for r in recency_rows:
            candidate_ids.add(r["id"])

        # 2. 若开启 fts5，用全文索引再取一批候选
        fts_ids = self._fts_candidate_ids(query, max_candidates)
        if fts_ids:
            placeholders = ",".join("?" * len(fts_ids))
            with self._lock:
                cursor = self._db.execute(
                    f"SELECT id, key, value, created_at FROM memory "
                    f"WHERE session_id=? AND layer=? AND id IN ({placeholders}) "
                    f"AND (expires_at=0 OR expires_at>?)",
                    (session_id, layer, *fts_ids, now),
                )
                for row in cursor.fetchall():
                    mid = row[0]
                    if mid not in candidate_ids:
                        candidate_ids.add(mid)
                        recency_rows.append(
                            {"id": mid, "key": row[1], "value": json.loads(row[2]) if row[2] else row[2], "created_at": row[3]}
                        )

        scored = [
            {
                "key": r["key"],
                "value": r["value"],
                "score": _score_candidate(query, r["key"], r["value"], r["created_at"]),
            }
            for r in recency_rows
        ]
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def delete_expired(
        self,
        session_id: Optional[str] = None,
        layer: Optional[str] = None,
    ) -> int:
        now = time.time()
        where = ["expires_at>0", "expires_at<=?"]
        params: List[Any] = [now]
        if session_id:
            where.append("session_id=?")
            params.append(session_id)
        if layer:
            where.append("layer=?")
            params.append(layer)
        ids = self._select_ids(" AND ".join(where), tuple(params))
        if not ids:
            return 0
        with self._lock:
            self._delete_from_fts(ids)
            placeholders = ",".join("?" * len(ids))
            cursor = self._db.execute(
                f"DELETE FROM memory WHERE id IN ({placeholders})",
                ids,
            )
            self._db.commit()
            return cursor.rowcount

    def evict_oldest(
        self,
        session_id: str,
        layer: str,
        max_entries: int,
    ) -> int:
        with self._lock:
            count_row = self._db.execute(
                "SELECT COUNT(*) FROM memory WHERE session_id=? AND layer=?",
                (session_id, layer),
            ).fetchone()
            total = count_row[0] if count_row else 0
            to_delete = total - max_entries
            if to_delete <= 0:
                return 0
            cursor = self._db.execute(
                "SELECT id FROM memory WHERE session_id=? AND layer=? "
                "ORDER BY created_at ASC LIMIT ?",
                (session_id, layer, to_delete),
            )
            ids = [row[0] for row in cursor.fetchall()]
            if not ids:
                return 0
            self._delete_from_fts(ids)
            placeholders = ",".join("?" * len(ids))
            self._db.execute(
                f"DELETE FROM memory WHERE id IN ({placeholders})",
                ids,
            )
            self._db.commit()
            return len(ids)

    def close(self) -> None:
        with self._lock:
            self._db.close()


class RedisMemoryBackend:
    """Redis 后端（可选，未安装时降级）。"""

    def __init__(self, url: Optional[str] = None):
        import redis
        self._client = redis.from_url(url or os.getenv("REDIS_URL", "redis://localhost:6379/0"))

    def _key(self, session_id: str, layer: str, key: str) -> str:
        return f"dev_agent:{layer}:{session_id}:{key}"

    def _encode(self, value: Any, created_at: float, expires_at: float) -> str:
        return json.dumps(
            {"_value": value, "_created_at": created_at, "_expires_at": expires_at},
            ensure_ascii=False,
        )

    def _decode(self, data: str) -> Tuple[Any, float, float]:
        try:
            parsed = json.loads(data)
            if isinstance(parsed, dict) and "_value" in parsed:
                return (
                    parsed["_value"],
                    parsed.get("_created_at") or time.time(),
                    parsed.get("_expires_at") or 0.0,
                )
        except json.JSONDecodeError:
            pass
        return data, time.time(), 0.0

    def remember(
        self,
        key: str,
        value: Any,
        session_id: str,
        layer: str,
        ttl: Optional[int] = None,
    ) -> None:
        full_key = self._key(session_id, layer, key)
        now = time.time()
        expires = now + ttl if ttl else 0
        raw = self._encode(value, now, expires)
        if ttl:
            self._client.setex(full_key, ttl, raw)
        else:
            self._client.set(full_key, raw)

    def recall(
        self,
        query: str,
        session_id: str,
        layer: str,
        top_k: int = 3,
        max_candidates: int = 100,
    ) -> List[Dict[str, Any]]:
        now = time.time()
        pattern = f"dev_agent:{layer}:{session_id}:*"
        keys = list(self._client.scan_iter(match=pattern, count=max_candidates))
        candidates = []
        expired_keys = []
        for key in keys[:max_candidates]:
            raw = self._client.get(key)
            if raw is None:
                continue
            decoded = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            value, created_at, expires_at = self._decode(decoded)
            if expires_at > 0 and expires_at <= now:
                expired_keys.append(key)
                continue
            key_str = key.decode("utf-8") if isinstance(key, bytes) else key
            candidates.append({"key": key_str, "value": value, "created_at": created_at})

        if expired_keys:
            self._client.delete(*expired_keys)

        scored = [
            {
                "key": c["key"],
                "value": c["value"],
                "score": _score_candidate(query, c["key"], c["value"], c["created_at"]),
            }
            for c in candidates
        ]
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def delete_expired(
        self,
        session_id: Optional[str] = None,
        layer: Optional[str] = None,
    ) -> int:
        now = time.time()
        pattern = f"dev_agent:{layer or '*'}:{session_id or '*'}:*"
        count = 0
        for key in self._client.scan_iter(match=pattern):
            raw = self._client.get(key)
            if raw is None:
                continue
            decoded = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            _, _, expires_at = self._decode(decoded)
            if expires_at > 0 and expires_at <= now:
                self._client.delete(key)
                count += 1
        return count

    def evict_oldest(
        self,
        session_id: str,
        layer: str,
        max_entries: int,
    ) -> int:
        pattern = f"dev_agent:{layer}:{session_id}:*"
        entries = []
        for key in self._client.scan_iter(match=pattern):
            raw = self._client.get(key)
            if raw is None:
                continue
            decoded = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            _, created_at, _ = self._decode(decoded)
            entries.append((key, created_at))
        if len(entries) <= max_entries:
            return 0
        entries.sort(key=lambda x: x[1])
        to_delete = [k for k, _ in entries[: len(entries) - max_entries]]
        if to_delete:
            self._client.delete(*to_delete)
        return len(to_delete)

    def close(self) -> None:
        pass


class ChromaMemoryBackend:
    """ChromaDB 后端（可选，未安装时降级），用于语义检索长期记忆。"""

    def __init__(self, base_dir: Path):
        import chromadb
        client = chromadb.PersistentClient(path=str(base_dir / "chroma_data"))
        self._collection = client.get_or_create_collection("memory")

    def _where_session_layer(
        self,
        session_id: str,
        layer: str,
    ) -> Dict[str, Any]:
        return {"session_id": session_id, "layer": layer}

    def _parse_meta(self, meta: Any) -> Dict[str, Any]:
        return dict(meta or {})

    def remember(
        self,
        key: str,
        value: Any,
        session_id: str,
        layer: str,
        ttl: Optional[int] = None,
    ) -> None:
        now = time.time()
        doc_id = f"{layer}:{session_id}:{key}"
        self._collection.upsert(
            ids=[doc_id],
            documents=[json.dumps(value, ensure_ascii=False)],
            metadatas=[{
                "session_id": session_id,
                "layer": layer,
                "key": key,
                "created_at": now,
                "expires_at": now + ttl if ttl else 0,
            }],
        )

    def recall(
        self,
        query: str,
        session_id: str,
        layer: str,
        top_k: int = 3,
        max_candidates: int = 100,
    ) -> List[Dict[str, Any]]:
        now = time.time()
        n_results = min(max_candidates * 2, max(50, top_k * 5))
        results = self._collection.query(
            query_texts=[query or ""],
            n_results=n_results,
            where=self._where_session_layer(session_id, layer),
        )
        candidates = []
        for doc_id, doc, meta, dist in zip(
            results["ids"][0], results["documents"][0], results["metadatas"][0], results["distances"][0]
        ):
            parsed = self._parse_meta(meta)
            expires_at = parsed.get("expires_at") or 0
            if expires_at > 0 and expires_at <= now:
                continue
            try:
                value = json.loads(doc)
            except json.JSONDecodeError:
                value = doc
            created_at = parsed.get("created_at") or time.time()
            semantic = 1.0 / (1.0 + float(dist))
            candidates.append({
                "key": parsed.get("key", doc_id),
                "value": value,
                "created_at": created_at,
                "semantic": semantic,
            })

        scored = [
            {
                "key": c["key"],
                "value": c["value"],
                "score": _score_candidate(
                    query, c["key"], c["value"], c["created_at"], c["semantic"], has_semantic=True
                ),
            }
            for c in candidates
        ]
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def delete_expired(
        self,
        session_id: Optional[str] = None,
        layer: Optional[str] = None,
    ) -> int:
        now = time.time()
        ids_to_delete = self._get_expired_ids(session_id, layer, now)
        if ids_to_delete:
            self._collection.delete(ids=ids_to_delete)
        return len(ids_to_delete)

    def _get_expired_ids(
        self,
        session_id: Optional[str],
        layer: Optional[str],
        now: float,
    ) -> List[str]:
        """优先用 Chroma get + where 过滤 TTL，失败则全量扫描。"""
        where: Dict[str, Any] = {"$and": [{"expires_at": {"$gt": 0}}, {"expires_at": {"$lte": now}}]}
        if session_id:
            where["$and"].append({"session_id": session_id})
        if layer:
            where["$and"].append({"layer": layer})
        try:
            data = self._collection.get(where=where, limit=10000)
            return data.get("ids", [])
        except Exception:  # noqa: BLE001
            return self._scan_expired_ids(session_id, layer, now)

    def _scan_expired_ids(
        self,
        session_id: Optional[str],
        layer: Optional[str],
        now: float,
    ) -> List[str]:
        try:
            data = self._collection.get(
                where=self._where_session_layer(session_id, layer) if session_id and layer else {},
                limit=10000,
            )
        except Exception:  # noqa: BLE001
            return []
        ids_to_delete = []
        metas = data.get("metadatas", [])
        ids = data.get("ids", [])
        for doc_id, meta in zip(ids, metas):
            parsed = self._parse_meta(meta)
            expires_at = parsed.get("expires_at") or 0
            if expires_at > 0 and expires_at <= now:
                ids_to_delete.append(doc_id)
        return ids_to_delete

    def evict_oldest(
        self,
        session_id: str,
        layer: str,
        max_entries: int,
    ) -> int:
        ids_to_delete = self._get_oldest_to_evict(session_id, layer, max_entries)
        if ids_to_delete:
            self._collection.delete(ids=ids_to_delete)
        return len(ids_to_delete)

    def _get_oldest_to_evict(
        self,
        session_id: str,
        layer: str,
        max_entries: int,
    ) -> List[str]:
        """优先用 get(where) 取全量再按 created_at 排序驱逐，异常则降级扫描。"""
        try:
            data = self._collection.get(
                where=self._where_session_layer(session_id, layer),
                limit=10000,
            )
        except Exception:  # noqa: BLE001
            return []
        metas = data.get("metadatas", [])
        ids = data.get("ids", [])
        if len(ids) <= max_entries:
            return []
        indexed = sorted(
            zip(ids, metas),
            key=lambda x: self._parse_meta(x[1]).get("created_at", 0),
        )
        return [doc_id for doc_id, _ in indexed[: len(indexed) - max_entries]]

    def close(self) -> None:
        pass


def _create_backend(base_dir: Path) -> MemoryBackend:
    backend = os.getenv("MEMORY_BACKEND", "sqlite").lower()
    if backend == "redis":
        try:
            return RedisMemoryBackend()
        except Exception as exc:  # noqa: BLE001
            print(f"[Memory] Redis 不可用，降级到 SQLite: {exc}")
            return SQLiteMemoryBackend(base_dir)
    if backend == "chroma":
        try:
            return ChromaMemoryBackend(base_dir)
        except Exception as exc:  # noqa: BLE001
            print(f"[Memory] ChromaDB 不可用，降级到 SQLite: {exc}")
            return SQLiteMemoryBackend(base_dir)
    return SQLiteMemoryBackend(base_dir)


class MemoryAgent:
    """统一记忆入口：短期记忆存内存，工作/长期记忆存后端。"""

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = Path(base_dir or Settings.memory_dir())
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._short: Dict[str, Dict[str, Any]] = {}
        self._backend = _create_backend(self.base_dir)
        self._lock: Optional[asyncio.Lock] = None
        try:
            self._lock = asyncio.Lock()
        except RuntimeError:
            pass
        self._max_entries = Settings.memory_max_entries_per_layer()
        self._max_candidates = Settings.memory_max_candidates()
        self._short_max = Settings.memory_short_max_entries()

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _cleanup_short(self, session_id: str) -> None:
        """清理短期记忆中的过期项，并按容量上限移除最旧项。"""
        now = time.time()
        session = self._short.get(session_id, {})
        expired = [k for k, v in session.items() if v.get("expires_at") is not None and v["expires_at"] <= now]
        for k in expired:
            session.pop(k, None)
        while len(session) > self._short_max:
            session.pop(next(iter(session)), None)

    def remember(
        self,
        key: str,
        value: Any,
        session_id: str = "default",
        layer: str = "short",
        ttl: Optional[int] = None,
    ) -> None:
        if layer == "short":
            session = self._short.setdefault(session_id, {})
            session[key] = {
                "value": value,
                "expires_at": time.time() + ttl if ttl else None,
                "created_at": time.time(),
            }
            self._cleanup_short(session_id)
            return
        self._backend.remember(key, value, session_id, layer, ttl)
        self._backend.delete_expired(session_id, layer)
        self._backend.evict_oldest(session_id, layer, self._max_entries)

    async def aremember(
        self,
        key: str,
        value: Any,
        session_id: str = "default",
        layer: str = "short",
        ttl: Optional[int] = None,
    ) -> None:
        """remember 的异步安全封装，在后台线程执行并加 asyncio 锁。"""
        async with self._get_lock():
            return await asyncio.to_thread(
                self.remember, key, value, session_id, layer, ttl
            )

    def recall(
        self,
        query: str,
        session_id: str = "default",
        layer: str = "working",
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        now = time.time()
        if layer == "short":
            session = self._short.get(session_id, {})
            candidates = []
            for key, item in session.items():
                expires_at = item.get("expires_at")
                if expires_at is not None and expires_at <= now:
                    continue
                candidates.append({
                    "key": key,
                    "value": item["value"],
                    "created_at": item.get("created_at", now),
                })
            scored = [
                {
                    "key": c["key"],
                    "value": c["value"],
                    "score": _score_candidate(query, c["key"], c["value"], c["created_at"]),
                }
                for c in candidates
            ]
            scored.sort(key=lambda x: x["score"], reverse=True)
            return scored[:top_k]
        return self._backend.recall(query, session_id, layer, top_k, max_candidates=self._max_candidates)

    async def arecall(
        self,
        query: str,
        session_id: str = "default",
        layer: str = "working",
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """recall 的异步安全封装，避免在 async 编排器中阻塞事件循环。"""
        async with self._get_lock():
            return await asyncio.to_thread(self.recall, query, session_id, layer, top_k)

    def summarize(self, history: List[Dict[str, Any]]) -> str:
        if not history:
            return ""
        parts = [f"- {h.get('agent','?')}: {str(h.get('output',''))[:120]}..." for h in history[-5:]]
        return "\n".join(parts)

    async def asummarize(self, history: List[Dict[str, Any]]) -> str:
        return self.summarize(history)

    def compress_context(self, text: str, max_chars: int = 8000) -> str:
        return ContextCompressor(max_chars=max_chars).compress(text)

    async def acompress_context(self, text: str, max_chars: int = 8000) -> str:
        return self.compress_context(text, max_chars)

    def delete_expired(
        self,
        session_id: Optional[str] = None,
        layer: Optional[str] = None,
    ) -> int:
        if layer == "short":
            count = 0
            now = time.time()
            for session in self._short.values():
                expired = [k for k, v in session.items() if v.get("expires_at") and v["expires_at"] <= now]
                for k in expired:
                    session.pop(k, None)
                    count += 1
            return count
        return self._backend.delete_expired(session_id, layer)

    async def adelete_expired(
        self,
        session_id: Optional[str] = None,
        layer: Optional[str] = None,
    ) -> int:
        async with self._get_lock():
            return await asyncio.to_thread(self.delete_expired, session_id, layer)

    def close(self) -> None:
        if hasattr(self._backend, "close"):
            self._backend.close()


# 保持旧接口兼容（注意：MemoryAgentFacade 实际在 agents.py 中供 Orchestrator 使用）
MemoryAgentFacade = MemoryAgent
```

## 附录 H：LLM 抽象与 Provider（`llm.py` 全文）

```python
"""LLM 客户端：自动选择 OpenAI / DeepSeek / Ollama / Mock Provider，支持流式输出。"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any, AsyncIterator, Iterator, Optional, Union

from dev_agent_system.config import Settings
from dev_agent_system.llm_providers import LLMProvider, MockProvider, OllamaProvider, OpenAIProvider


def _openai_available() -> bool:
    try:
        import openai  # noqa: F401
        return True
    except ImportError:
        return False


class LLMClient:
    """轻量级 LLM 客户端，根据环境变量自动选择 Provider。"""

    def __init__(
        self,
        model: Optional[str] = None,
        provider: Optional[Union[str, LLMProvider]] = None,
    ):
        self.model = model or Settings.llm_model()
        self.provider = self._resolve_provider(provider)

    def _resolve_provider(self, provider: Optional[Union[str, LLMProvider]]) -> LLMProvider:
        if isinstance(provider, LLMProvider):
            return provider

        provider_name = (provider or Settings.llm_provider() or "").lower()
        if provider_name == "openai" or provider_name == "deepseek":
            return self._openai_provider()
        if provider_name == "ollama":
            return self._ollama_provider()
        if provider_name == "mock":
            return MockProvider(model=self.model)

        # 自动推断：未配置真实 LLM 时降级为 MOCK
        if self.model and self.model.startswith("ollama/"):
            return self._ollama_provider(model=self.model.split("/", 1)[1])
        if Settings.llm_api_key() and _openai_available():
            return self._openai_provider()

        return MockProvider(model=self.model)

    def _openai_provider(self, model: Optional[str] = None) -> OpenAIProvider:
        return OpenAIProvider(
            model=model or self.model,
            api_key=Settings.llm_api_key(),
            base_url=Settings.llm_base_url() or None,
            timeout=Settings.llm_timeout(),
            max_retries=Settings.llm_max_retries(),
        )

    def _ollama_provider(self, model: Optional[str] = None) -> OllamaProvider:
        return OllamaProvider(
            model=model or self.model,
            base_url=Settings.ollama_url(),
            timeout=Settings.llm_timeout(),
        )

    def is_mock(self) -> bool:
        return isinstance(self.provider, MockProvider)

    @staticmethod
    def _mask(text: str) -> str:
        """PII 脱敏：API Key、手机号、密码。"""
        text = re.sub(r"sk-[a-zA-Z0-9]{20,}", "[API_KEY_REDACTED]", text)
        text = re.sub(r"1[3-9]\d{9}", "[PHONE_REDACTED]", text)
        text = re.sub(r"password[:=]\s*\S+", "password=[REDACTED]", text, flags=re.I)
        return text

    def chat(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        system = self._mask(system)
        user = self._mask(user)
        try:
            return self.provider.chat(
                system,
                user,
                model=model or self.model,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
            )
        except Exception as e:  # noqa: BLE001
            return f"[LLM ERROR] {e}"

    async def achat(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        """异步非流式对话，默认在后台线程调用 self.chat，避免阻塞事件循环。

        这种方式兼容已有对 self.chat 的 monkeypatch，同时让 async 编排器不被网络 IO 阻塞。
        后续 Provider 可继续实现原生 async chat 接口并在这里优先调用。
        """
        try:
            return await asyncio.to_thread(
                self.chat,
                system,
                user,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
            )
        except Exception as e:  # noqa: BLE001
            return f"[LLM ERROR] {e}"

    def stream(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> Iterator[str]:
        system = self._mask(system)
        user = self._mask(user)
        try:
            yield from self.provider.stream(
                system,
                user,
                model=model or self.model,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
            )
        except Exception as e:  # noqa: BLE001
            yield f"[LLM ERROR] {e}"

    async def astream(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> AsyncIterator[str]:
        system = self._mask(system)
        user = self._mask(user)
        try:
            async for token in self.provider.astream(
                system,
                user,
                model=model or self.model,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
            ):
                if token:
                    yield token
        except Exception as e:  # noqa: BLE001
            yield f"[LLM ERROR] {e}"


class MockLLM:
    """固定返回，用于测试与降级演示（兼容旧接口）。"""

    def __init__(self, response: str = "[MOCK] 收到请求"):
        self.response = response
        self._provider = MockProvider(response=response)

    def chat(self, system: str, user: str) -> str:
        return self._provider.chat(system, user)

    async def astream(self, system: str, user: str):
        async for token in self._provider.astream(system, user):
            yield token

    def stream(self, system: str, user: str):
        yield from self._provider.stream(system, user)
```

### H.1 LLM Provider 实现（`llm_providers.py`）

```python
"""LLM Provider 抽象与实现：OpenAI、DeepSeek、Ollama（本地模型）、Mock。"""
from __future__ import annotations

import abc
import json
import re
from typing import Any, AsyncIterator, Callable, Dict, Iterator, Optional, Union

import httpx

try:
    import openai as _openai
except ImportError:  # pragma: no cover
    _openai = None


class LLMProvider(abc.ABC):
    """LLM 调用抽象层，支持同步/异步流式与非流式。"""

    def __init__(self, model: str) -> None:
        self.model = model

    @abc.abstractmethod
    def chat(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        """同步非流式对话，返回完整回复字符串。"""
        raise NotImplementedError

    @abc.abstractmethod
    def stream(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> Iterator[str]:
        """同步流式生成器，逐 token 输出。"""
        raise NotImplementedError

    @abc.abstractmethod
    async def astream(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> AsyncIterator[str]:
        """异步流式生成器，逐 token 输出。"""
        raise NotImplementedError

    @staticmethod
    def _messages(system: str, user: str) -> List[Dict[str, str]]:
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]


class OpenAIProvider(LLMProvider):
    """OpenAI 兼容 API Provider，支持 DeepSeek 等 OpenAI 格式服务。"""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 2,
        client: Any = None,
        async_client: Any = None,
    ) -> None:
        if _openai is None:
            raise ImportError("openai package is required for OpenAIProvider")
        super().__init__(model)
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = client or _openai.OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )
        self._async_client = async_client or _openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )

    def _build_kwargs(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        json_mode: bool = False,
    ) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "model": model or self.model,
            "messages": self._messages(system, user),
            "stream": stream,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if json_mode and not stream:
            kwargs["response_format"] = {"type": "json_object"}
        return kwargs

    def chat(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        kwargs = self._build_kwargs(system, user, model=model, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode)
        resp = self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    def stream(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> Iterator[str]:
        kwargs = self._build_kwargs(system, user, model=model, temperature=temperature, max_tokens=max_tokens, stream=True, json_mode=json_mode)
        for chunk in self._client.chat.completions.create(**kwargs):
            delta = (chunk.choices[0].delta.content or "") if chunk.choices else ""
            if delta:
                yield delta

    async def astream(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> AsyncIterator[str]:
        kwargs = self._build_kwargs(system, user, model=model, temperature=temperature, max_tokens=max_tokens, stream=True, json_mode=json_mode)
        response = await self._async_client.chat.completions.create(**kwargs)
        async for chunk in response:
            delta = (chunk.choices[0].delta.content or "") if chunk.choices else ""
            if delta:
                yield delta


class OllamaProvider(LLMProvider):
    """Ollama 本地模型 Provider，通过 /api/chat 调用。"""

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        timeout: float = 30.0,
        client: Optional[httpx.Client] = None,
        async_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        super().__init__(model)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = client
        self._async_client = async_client

    def _build_body(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        json_mode: bool = False,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "model": model or self.model,
            "messages": self._messages(system, user),
            "stream": stream,
        }
        if json_mode:
            body["format"] = "json"
        options: Dict[str, Any] = {}
        if temperature is not None:
            options["temperature"] = temperature
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        if options:
            body["options"] = options
        return body

    def chat(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        body = self._build_body(system, user, model=model, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode)
        url = f"{self.base_url}/api/chat"
        client = self._client or httpx.Client()
        try:
            resp = client.post(url, json=body, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "")
        finally:
            if self._client is None:
                client.close()

    def _iter_lines(self, response: httpx.Response) -> Iterator[str]:
        for line in response.iter_lines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if data.get("done"):
                break
            content = (data.get("message") or {}).get("content", "")
            if content:
                yield content

    def stream(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> Iterator[str]:
        body = self._build_body(system, user, model=model, temperature=temperature, max_tokens=max_tokens, stream=True, json_mode=json_mode)
        url = f"{self.base_url}/api/chat"
        client = self._client or httpx.Client()
        try:
            with client.stream("POST", url, json=body, timeout=self.timeout) as resp:
                resp.raise_for_status()
                yield from self._iter_lines(resp)
        finally:
            if self._client is None:
                client.close()

    async def astream(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> AsyncIterator[str]:
        body = self._build_body(system, user, model=model, temperature=temperature, max_tokens=max_tokens, stream=True, json_mode=json_mode)
        url = f"{self.base_url}/api/chat"
        client = self._async_client or httpx.AsyncClient()
        try:
            async with client.stream("POST", url, json=body, timeout=self.timeout) as resp:
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if data.get("done"):
                        break
                    content = (data.get("message") or {}).get("content", "")
                    if content:
                        yield content
        finally:
            if self._async_client is None:
                await client.aclose()


class MockProvider(LLMProvider):
    """Mock Provider，用于测试与未配置真实密钥时的降级。"""

    def __init__(
        self,
        model: str = "mock",
        response: Optional[Union[str, Callable[[str, str, str], str]]] = None,
    ) -> None:
        super().__init__(model)
        self.response = response

    def _render(self, system: str, user: str, model: str) -> str:
        if callable(self.response):
            return self.response(system, user, model)
        if isinstance(self.response, str):
            return self.response
        return (
            f"[MOCK {model}] 未配置 LLM_API_KEY 或未安装 openai 包，\n"
            f"系统摘要：{system[:80]}...\n"
            f"输入摘要：{user[:160]}..."
        )

    def _split(self, text: str) -> Iterator[str]:
        # 保留空格，按单词/标点拆分，模拟 token 级流式
        parts = re.split(r"(\s+)", text)
        for part in parts:
            if part:
                yield part

    def chat(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        return self._render(system, user, model or self.model)

    def stream(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> Iterator[str]:
        text = self._render(system, user, model or self.model)
        yield from self._split(text)

    async def astream(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> AsyncIterator[str]:
        text = self._render(system, user, model or self.model)
        for token in self._split(text):
            yield token
```

## 附录 I：`BaseAgent` 生命周期（`agents.py` 节选）

```python
"""6 个业务 Agent + Memory Agent 的实现。

每个 Agent 现在都会把产物写入以 request_id 隔离的 workspace，并返回结构化结果。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

import yaml
from pydantic import BaseModel, ValidationError

from dev_agent_system.config import Settings
from dev_agent_system.llm import LLMClient
from dev_agent_system.memory import MemoryAgent
from dev_agent_system.mcp import MCPToolRegistry, ToolSandbox
from dev_agent_system.router import ModelRouter
from dev_agent_system.security import SafetyScanner, SecretRedactor
from dev_agent_system.telemetry import DEFAULT as DEFAULT_TELEMETRY, Telemetry
from dev_agent_system.templates import get_language, TEMPLATES
from dev_agent_system.skills import SkillManager
from dev_agent_system.schemas import (
    AgentCard,
    AgentFile,
    AgentOutput,
    AgentSkill,
    CoderReport,
    DesignOutput,
    DBAReport,
    PRDOutput,
    ReviewReport,
    TestReport,
)


class BaseAgent:
    """所有业务 Agent 的基类。"""

    json_output: bool = False
    report_schema: Optional[Type[BaseModel]] = None
    summary_budget: int = 1500
    max_repair_attempts: int = 1  # JSON/Pydantic 校验失败时自动修复的最大次数

    def __init__(
        self,
        name: str,
        role: str,
        system_prompt: str,
        model: Optional[str] = None,
        skills: Optional[List[str]] = None,
        telemetry: Optional[Telemetry] = None,
    ):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.model = model or Settings.agent_model(name.lower())
        self.skills = skills or [role]
        self.router = ModelRouter()
        self.llm = LLMClient(model=self.model)
        self.memory = MemoryAgent()
        self.tools = MCPToolRegistry()
        self.telemetry = telemetry or DEFAULT_TELEMETRY

        # 自动发现并注册已安装的 Skill 到 MCP 工具箱
        self._register_skills()

    def _register_skills(self) -> None:
        if not Settings.skills_enabled():
            return
        try:
            SkillManager().register_to_mcp(self.tools)
        except Exception:  # noqa: BLE001
            pass

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return str(state.get("input", ""))

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """子类重写：解析输出、调用 MCP 工具、写入产物。"""
        return {"raw": output}

    @staticmethod
    def _workspace(state: Dict[str, Any]) -> Path:
        """当前请求的工作目录。"""
        if state.get("workspace"):
            return Path(state["workspace"])
        request_id = state.get("request_id", "default")
        return ToolSandbox.WORK_DIR / str(request_id)

    async def _write_file(self, path: str, content: str, workspace: Path) -> Dict[str, Any]:
        return await self.tools.ainvoke("write_file", path=path, content=content, base_dir=str(workspace))

    async def _read_file(self, path: str, workspace: Path) -> Dict[str, Any]:
        return await self.tools.ainvoke("read_file", path=path, base_dir=str(workspace))

    async def _run_command(self, command: str, workspace: Path, timeout: int = 10) -> Dict[str, Any]:
        return await self.tools.ainvoke("run_command", command=command, timeout=timeout, base_dir=str(workspace))

    @staticmethod
    def _extract_json(text: str) -> Optional[Dict[str, Any]]:
        """从文本中提取第一个 JSON 对象或数组。"""
        match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _extract_code_blocks(text: str) -> List[Dict[str, str]]:
        """提取 ``` 代码块，支持前接 '# file: path' 等头部。"""
        blocks: List[Dict[str, str]] = []
        pattern = r"(?:^|\n)(?:[^\n`]*?(?:file|path|filename)[:\s]+([^\n]+))?\n?```(?:\w+)?\n(.*?)```"
        for m in re.finditer(pattern, text, re.DOTALL | re.I):
            path = (m.group(1) or "").strip().strip("`").strip()
            code = m.group(2)
            blocks.append({"path": path, "code": code})
        return blocks

    @staticmethod
    def _find_first_json_object(text: str) -> Optional[Any]:
        """从文本中定位第一个非空的 JSON 对象/数组。

        优先匹配 ```json ... ``` 代码块，再扫描内嵌的 JSON。
        """
        # 1) 显式 JSON 代码块
        for m in re.finditer(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL | re.I):
            block = m.group(1).strip()
            if not block:
                continue
            try:
                data = json.loads(block)
                if isinstance(data, (dict, list)) and data:
                    return data
            except json.JSONDecodeError:
                continue

        # 2) 用 JSONDecoder 扫描 { } / [ ]，跳过空的 {} / []
        decoder = json.JSONDecoder()
        idx = 0
        n = len(text)
        while idx < n:
            # 定位到下一个 { 或 [
            while idx < n and text[idx] not in "{[":
                idx += 1
            if idx >= n:
                return None
            try:
                data, end = decoder.raw_decode(text, idx)
                if isinstance(data, dict) and data:
                    return data
                if isinstance(data, list) and data:
                    return data
                idx += max(end, 1)
            except (json.JSONDecodeError, ValueError):
                idx += 1
        return None

    @staticmethod
    def _truncate_for_summary(
        value: Any,
        max_str: int = 400,
        max_list: int = 10,
        max_depth: int = 4,
        current_depth: int = 0,
    ) -> Any:
        """递归截断 dict/list/str，用于生成下游 Agent 可读的 summary。"""
        if current_depth > max_depth:
            return "..."
        if isinstance(value, str):
            if len(value) > max_str:
                return value[:max_str] + "... [truncated]"
            return value
        if isinstance(value, (list, tuple)):
            truncated = [BaseAgent._truncate_for_summary(v, max_str, max_list, max_depth, current_depth + 1) for v in value[:max_list]]
            if len(value) > max_list:
                truncated.append("...")
            return truncated
        if isinstance(value, dict):
            return {
                k: BaseAgent._truncate_for_summary(v, max_str, max_list, max_depth, current_depth + 1)
                for k, v in value.items()
            }
        return value

    def _summarize_result(self, result: Dict[str, Any]) -> str:
        """把 Agent 运行结果压缩成下游可传递的关键信息字符串。

        - 丢弃原始 LLM 输出（已解析到产物/文件和 report）
        - 递归截断长字符串/列表，避免 state 和 checkpoint 膨胀
        - 保证返回合法 JSON，便于下游直接解析
        """
        # 不向下游传递的元数据键
        excluded = {"output", "workspace", "model", "llm_kwargs", "agent", "role", "raw"}
        raw = {k: v for k, v in result.items() if k not in excluded and not k.startswith("_")}

        # 自适应截断：在保证合法 JSON 的前提下把 summary 压到 budget 内
        max_str, max_list = 400, 10
        while True:
            data = self._truncate_for_summary(raw, max_str=max_str, max_list=max_list)
            text = json.dumps(data, ensure_ascii=False, default=str)
            if len(text) <= self.summary_budget or max_str <= 50:
                break
            max_str = max(50, max_str // 2)
            max_list = max(3, max_list - 2)

        return text

    def _with_json_schema_prompt(self, prompt: str) -> str:
        """在 prompt 末尾追加 report_schema 对应的 JSON Schema，强化输出约束。"""
        if self.report_schema is None:
            return prompt + "\n\n你必须输出且仅输出一个合法 JSON 对象，不要包含解释文字。"
        try:
            schema = self.report_schema.model_json_schema()
        except Exception:  # noqa: BLE001
            return prompt + "\n\n你必须输出且仅输出一个合法 JSON 对象，不要包含解释文字。"
        return (
            prompt
            + "\n\n你必须输出且仅输出一个严格符合以下 JSON Schema 的单一 JSON 对象，"
            "不要包含任何解释文字或 Markdown 代码块包装：\n\n"
            f"```json\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n```"
        )

    @staticmethod
    def _parse_raw_json(text: Any) -> Optional[Any]:
        """从任意输入中提取 dict/list，不校验 schema（兼容旧版实现）。"""
        if text is None:
            return None
        if isinstance(text, (dict, list)):
            return text
        cleaned = str(text).strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`").strip()
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return BaseAgent._find_first_json_object(cleaned)

    async def _parse_json_output(
        self,
        text: Any,
        schema: Optional[Type[BaseModel]] = None,
    ) -> Optional[Dict[str, Any]]:
        """解析并可选做 Pydantic 校验；失败时尝试自我修复（最多 max_repair_attempts 次）。"""
        raw = text
        schema = schema or self.report_schema
        last_error = ""
        for attempt in range(self.max_repair_attempts + 1):
            data = BaseAgent._parse_raw_json(raw)
            if not isinstance(data, dict):
                if attempt == self.max_repair_attempts or not self.json_output:
                    return None
                last_error = "无法从文本中提取 JSON 对象"
                raw = await self.llm.achat(
                    self.system_prompt,
                    self._build_repair_prompt(str(text), last_error, schema),
                    json_mode=True,
                )
                continue
            if schema is None:
                return data
            try:
                return schema.model_validate(data).model_dump()
            except ValidationError as exc:
                if attempt == self.max_repair_attempts:
                    # 最后一次仍失败：如果 extra="ignore" 则返回原 dict；否则 None
                    return data
                last_error = str(exc)
                raw = await self.llm.achat(
                    self.system_prompt,
                    self._build_repair_prompt(str(text), last_error, schema),
                    json_mode=True,
                )
        return None

    def _build_repair_prompt(self, raw_output: str, error_message: str, schema: Optional[Type[BaseModel]]) -> str:
        schema_prompt = ""
        if schema is not None:
            try:
                schema_json = schema.model_json_schema()
                schema_prompt = f"\n必须严格符合的 JSON Schema：\n```json\n{json.dumps(schema_json, ensure_ascii=False, indent=2)}\n```\n"
            except Exception:  # noqa: BLE001
                pass
        return (
            "你之前生成的 JSON 输出无法通过校验，请重新生成。\n\n"
            f"原始输出：\n{raw_output}\n\n"
            f"错误信息：\n{error_message}\n"
            f"{schema_prompt}\n"
            "请只输出修复后的合法 JSON，不要解释。"
        )

    async def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        session = state.get("request_id", "default")
        workspace = self._workspace(state)
        workspace.mkdir(parents=True, exist_ok=True)
        state["workspace"] = str(workspace)

        memories = await self.memory.arecall(state.get("input", ""), session_id=session, layer="working", top_k=3)
        memory_text = "\n".join(str(m["value"]) for m in memories)
        prompt = self.build_prompt(state)
        full_prompt = f"相关记忆：\n{memory_text}\n\n{prompt}" if memory_text else prompt

        # 上下文压缩：超过阈值后保留头部和尾部
        if len(full_prompt) > Settings.context_compress_threshold():
            full_prompt = await self.memory.acompress_context(
                full_prompt, max_chars=Settings.context_window_limit()
            )

        # 敏感信息脱敏：进入 LLM 前与离开 LLM 后都进行 redaction
        full_prompt = SecretRedactor.redact(full_prompt)

        # 如果启用 json_mode 且绑定了 report_schema，把 JSON Schema 注入 prompt 强化约束
        if self.json_output:
            full_prompt = self._with_json_schema_prompt(full_prompt)

        resolved_model, kwargs = self.router.resolve(self.name, full_prompt)

        with self.telemetry.span(
            f"agent.{self.name}.llm",
            {"agent": self.name, "model": resolved_model, "request_id": session},
        ):
            output = await self.llm.achat(
                self.system_prompt,
                full_prompt,
                model=resolved_model,
                json_mode=self.json_output,
                **kwargs,
            )

        output = SecretRedactor.redact(output)

        # 近似 token 数与延迟统计
        self.telemetry.collector.counter(
            "llm_calls_total",
            "Total number of LLM calls",
            labelnames=["agent", "model"],
        ).inc(agent=self.name, model=resolved_model)
        self.telemetry.collector.histogram(
            "llm_prompt_tokens_approx",
            "Approximate prompt tokens",
            labelnames=["agent", "model"],
        ).observe(len(full_prompt) / 4, agent=self.name, model=resolved_model)
        self.telemetry.collector.histogram(
            "llm_output_tokens_approx",
            "Approximate output tokens",
            labelnames=["agent", "model"],
        ).observe(len(output) / 4, agent=self.name, model=resolved_model)

        result: Dict[str, Any] = {
            "agent": self.name,
            "role": self.role,
            "output": output,
            "workspace": str(workspace),
            "model": resolved_model,
            "llm_kwargs": kwargs,
        }
        extra = await self.postprocess(output, state)
        result.update(extra)

        # 生成关键信息摘要，替换原始 output，避免无效数据在 Agent 间传递
        result["output"] = self._summarize_result(result)
        # llm_kwargs 等内部元数据无需进入 LangGraph state
        result.pop("llm_kwargs", None)
        # 记忆层也存摘要，避免后续 recall 把原始大段输出塞进 prompt
        await self.memory.aremember("last_output", result["output"], session_id=session, layer="short", ttl=3600)

        return result

    def agent_card(self, url: str) -> AgentCard:
        return AgentCard(
            name=f"{self.name} Agent",
            url=url,
            skills=[AgentSkill(name=s) for s in self.skills],
            capabilities={"streaming": False, "autonomy": "L2", "modalities": ["text", "code"]},
        )


class ArchitectAgent(BaseAgent):
    json_output = True
    report_schema = DesignOutput
    summary_budget = 2000

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Architect",
            "系统架构师",
            _load_prompt("architect"),
            model=model,
            skills=["system-design", "api-contract", "tech-stack"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        prd = (state.get("product_manager") or {}).get("output", "")
        template = get_language(state)
        return (
            f"目标语言/技术栈：{template.display}\n"
            f"用户需求：{state.get('input', '')}\n"
            f"PRD：{prd[:1500] if prd else '无'}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            "请输出 JSON 格式架构设计：{modules, api_contract, tech_stack, mermaid, notes}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        design = await self._parse_json_output(output, self.report_schema)
        if design:
            await self._write_file("design.json", json.dumps(design, ensure_ascii=False, indent=2), workspace)
        return {"design_file": "design.json" if design else None, "parsed": design}


class CoderAgent(BaseAgent):
    json_output = True
    report_schema = CoderReport
    summary_budget = 1500

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Coder",
            "代码实现引擎",
            _load_prompt("coder"),
            model=model,
            skills=["code-implementation", "refactor", "python"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        dba_output = (state.get("dba") or {}).get("output", "")
        template = get_language(state)
        json_example = (
            '{"files": [{"path": "main.%s", "code": "..."}], '
            '"report": {"status": "completed", "files_modified": [...], '
            '"test_result": "passed", "note": ""}}'
        ) % template.file_ext
        return (
            f"目标语言/技术栈：{template.display}\n"
            f"构建命令：{template.build_cmd or '无'}\n"
            f"测试命令：{template.test_cmd}\n"
            f"用户生成文件扩展名：.{template.file_ext}，测试文件扩展名：.{template.test_ext}\n"
            f"用户需求：{state.get('input', '')}\n"
            f"架构设计：{(state.get('architect') or {}).get('output', '')[:2000]}\n"
            f"数据库设计：{dba_output[:1500] if dba_output else '无'}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            f"请生成可运行代码。必须输出一个合法的 JSON 对象：\n{json_example}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        template = get_language(state)
        files: List[str] = []
        security_issues: List[Dict[str, Any]] = []

        # 优先解析结构化 JSON 输出（JSON Mode / response_format）
        structured = await self._parse_json_output(output, AgentOutput)
        report: Dict[str, Any] = {}
        if structured and "files" in structured and "report" in structured:
            for f in structured.get("files", []):
                path = f.get("path", "")
                code = f.get("code", "")
                if not path:
                    continue
                if not path.endswith(f".{template.file_ext}"):
                    path += f".{template.file_ext}"
                issues = SafetyScanner.scan_code(code)
                security_issues.extend(issues)
                res = await self._write_file(path, code, workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(structured.get("report"), self.report_schema) or structured.get("report", {})
        else:
            # 兼容历史/测试中的 Markdown 代码块 + JSON 报告
            blocks = self._extract_code_blocks(output)
            for idx, block in enumerate(blocks, start=1):
                path = block["path"]
                if not path:
                    path = f"module_{idx}.{template.file_ext}"
                if not path.endswith(f".{template.file_ext}"):
                    path += f".{template.file_ext}"
                issues = SafetyScanner.scan_code(block["code"])
                security_issues.extend(issues)
                res = await self._write_file(path, block["code"], workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(output, self.report_schema) or {}

        # MOCK 降级：没有真实 LLM 时写一段占位代码，方便 CLI/测试继续跑
        if not files and self.llm.is_mock():
            stub = self._fallback_code(state.get("input", ""), template)
            res = await self._write_file(template.main_file(), stub, workspace)
            if res.get("success"):
                files.append(template.main_file())
            report = {
                "status": "mock_fallback",
                "files_modified": files,
                "test_result": "unknown",
                "note": f"MOCK 模式生成的占位代码 ({template.display})",
            }

        return {
            "files": files,
            "status": report.get("status", "completed" if files else "needs_help"),
            "test_result": report.get("test_result", "unknown"),
            "note": report.get("note", ""),
            "security_issues": security_issues,
        }

    @staticmethod
    def _fallback_code(requirement: str, template: Any) -> str:
        safe = re.sub(r"[^\w\u4e00-\u9fff]+", "_", requirement)[:30].strip("_") or "agent"
        if template.name == "java":
            class_name = safe.capitalize()
            return (
                f"package com.devagent;\n\n"
                f"public class {class_name} {{\n"
                f"    public static void main(String[] args) {{\n"
                f"        System.out.println(\"Hello from {safe}\");\n"
                f"    }}\n"
                f"}}\n"
            )
        if template.name == "go":
            return (
                f"package main\n\n"
                f"import \"fmt\"\n\n"
                f"func main() {{\n"
                f"    fmt.Println(\"Hello from {safe}\")\n"
                f"}}\n"
            )
        if template.name == "typescript":
            return (
                f"console.log(\"Hello from {safe}\");\n"
            )
        return f'"""Generated from requirement: {requirement}"""\n\ndef main():\n    print("Hello from {safe}")\n\nif __name__ == "__main__":\n    main()\n'


class TesterAgent(BaseAgent):
    json_output = True
    report_schema = TestReport
    summary_budget = 1200

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Tester",
            "测试工程师",
            _load_prompt("tester"),
            model=model,
            skills=["test-generation", "pytest", "coverage"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        workspace = state.get("workspace", "")
        template = get_language(state)
        code_files = (state.get("coder") or {}).get("files", [])
        code_snippets: List[str] = []
        for f in code_files[:3]:
            res = ToolSandbox.read_file(f, base_dir=workspace)  # 同步读取即可
            if res.get("success"):
                code_snippets.append(f"--- {f} ---\n{res['content'][:1500]}")
        json_example = (
            '{"files": [{"path": "test_%s", "code": "..."}], '
            '"report": {"passed": 0, "failed": 0, "coverage": 0.0, "report": ""}}'
        ) % template.file_ext
        return (
            f"目标语言：{template.display}\n"
            f"测试框架/命令：{template.test_cmd}\n"
            f"测试文件命名：*.{template.test_ext}\n"
            f"代码文件：{code_files}\n"
            f"{''.join(code_snippets)[:2500]}\n"
            f"工作目录：{workspace}\n"
            f"请生成对应语言的测试用例。必须输出一个合法的 JSON 对象：\n{json_example}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        template = get_language(state)
        files: List[str] = []

        # 优先解析结构化 JSON 输出
        structured = await self._parse_json_output(output, AgentOutput)
        report: Dict[str, Any] = {}
        if structured and "files" in structured and "report" in structured:
            for f in structured.get("files", []):
                path = f.get("path", "")
                code = f.get("code", "")
                if not path:
                    continue
                if not path.endswith(f".{template.test_ext}"):
                    path += f".{template.test_ext}"
                res = await self._write_file(path, code, workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(structured.get("report"), self.report_schema) or structured.get("report", {})
        else:
            # 兼容历史/测试中的 Markdown 代码块 + JSON 报告
            blocks = self._extract_code_blocks(output)
            for idx, block in enumerate(blocks, start=1):
                path = block["path"]
                if not path:
                    path = f"test_module_{idx}.{template.test_ext}"
                if not path.endswith(f".{template.test_ext}"):
                    path += f".{template.test_ext}"
                res = await self._write_file(path, block["code"], workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(output, self.report_schema) or {}

        if files:
            test_res = await self._run_command(f"{template.test_cmd} -q", workspace, timeout=15)
        else:
            test_res = {"success": False, "stdout": "", "stderr": "no tests generated"}

        passed = report.get("passed")
        failed = report.get("failed")
        if passed is None or failed is None:
            passed, failed = self._parse_test_summary(test_res.get("stdout", ""))

        return {
            "files": files,
            "passed": passed,
            "failed": failed,
            "coverage": report.get("coverage", 0.0),
            "report": (test_res.get("stdout", "") + "\n" + test_res.get("stderr", "")).strip(),
            "test_command_success": test_res.get("success", False),
        }

    @staticmethod
    def _parse_test_summary(stdout: str):
        m = re.search(r"(\d+)\s+passed", stdout)
        passed = int(m.group(1)) if m else 0
        m = re.search(r"(\d+)\s+failed", stdout)
        failed = int(m.group(1)) if m else 0
        return passed, failed


class ReviewerAgent(BaseAgent):
    json_output = True
    report_schema = ReviewReport
    summary_budget = 1200

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Reviewer",
            "代码审查",
            _load_prompt("reviewer"),
            model=model,
            skills=["code-review", "security", "performance"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"原始需求：{state.get('input', '')}\n"
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            f"测试报告：{(state.get('tester') or {}).get('report', '')[:1200]}\n"
            f"文档文件：{(state.get('docs') or {}).get('files', [])}\n"
            "请独立思考，从需求出发审查。输出 JSON：{severity, passed, issues, suggestions}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        report = await self._parse_json_output(output, self.report_schema)
        if not report:
            # 无法解析 JSON 时做最保守判断
            report = {
                "severity": "medium",
                "passed": False,
                "issues": ["Reviewer 输出无法解析为 JSON"],
                "suggestions": ["请检查 LLM 输出格式"],
            }
        review_file = "review_report.json"
        await self._write_file(review_file, json.dumps(report, ensure_ascii=False, indent=2), workspace)
        report["report_file"] = review_file
        return report


class DocsAgent(BaseAgent):
    summary_budget = 800

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Docs",
            "文档工程师",
            _load_prompt("docs"),
            model=model,
            skills=["documentation", "readme", "api-doc"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"架构：{str((state.get('architect') or {}).get('output', ''))[:800]}\n"
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            "请生成 README.md 与 API.md。用代码块标明文件路径，如 '# file: README.md'。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        blocks = self._extract_code_blocks(output)
        files: List[str] = []
        for block in blocks:
            path = block["path"] or "README.md"
            if not path.endswith(".md"):
                path += ".md"
            res = await self._write_file(f"docs/{path}", block["code"], workspace)
            if res.get("success"):
                files.append(f"docs/{path}")
        if not files:
            await self._write_file("docs/README.md", output, workspace)
            files.append("docs/README.md")
        return {"files": files}


class DevOpsAgent(BaseAgent):
    summary_budget = 1000

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "DevOps",
            "部署运维",
            _load_prompt("devops"),
            model=model,
            skills=["docker", "ci-cd", "deployment"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            "请生成 Dockerfile、docker-compose.yml 与 CI/CD 配置摘要，并说明部署前需人工确认。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        blocks = self._extract_code_blocks(output)
        files: List[str] = []
        for block in blocks:
            path = block["path"]
            if not path:
                continue
            res = await self._write_file(path, block["code"], workspace)
            if res.get("success"):
                files.append(path)
        if not files:
            await self._write_file("deploy_summary.md", output, workspace)
            files.append("deploy_summary.md")
        return {"files": files, "needs_approval": True}


class ProductManagerAgent(BaseAgent):
    report_schema = PRDOutput
    summary_budget = 1200

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "ProductManager",
            "产品经理",
            _load_prompt("product_manager"),
            model=model,
            skills=["requirement-analysis", "prd", "user-stories"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"用户需求：{state.get('input', '')}\n"
            "请把需求拆分为 PRD、用户故事和验收标准。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        report = await self._parse_json_output(output, self.report_schema) or {}
        prd_file = "prd.md"
        # 如果结构化输出里有 prd_markdown，优先写入；否则把原始输出作为 PRD 正文
        prd_body = report.get("prd_markdown") or output
        await self._write_file(prd_file, prd_body, workspace)
        return {
            "prd_file": prd_file,
            "user_stories": report.get("user_stories", []),
            "acceptance_criteria": report.get("acceptance_criteria", []),
            "parsed": report,
        }


class SecurityAgent(BaseAgent):
    json_output = True
    report_schema = ReviewReport
    summary_budget = 1200

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Security",
            "安全审查",
            _load_prompt("security"),
            model=model,
            skills=["security-review", "vulnerability", "compliance"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"原始需求：{state.get('input', '')}\n"
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            f"测试文件：{(state.get('tester') or {}).get('files', [])}\n"
            f"架构设计：{(state.get('architect') or {}).get('output', '')[:1500]}\n"
            "请独立进行安全审查，输出 JSON {severity, passed, issues, suggestions}。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        report = await self._parse_json_output(output, self.report_schema)
        if not report:
            report = {
                "severity": "medium",
                "passed": False,
                "issues": ["Security Agent 输出无法解析为 JSON"],
                "suggestions": ["请检查 LLM 输出格式"],
            }
        report_file = "security_report.json"
        await self._write_file(report_file, json.dumps(report, ensure_ascii=False, indent=2), workspace)
        report["report_file"] = report_file
        return report


class DBAAgent(BaseAgent):
    json_output = True
    report_schema = DBAReport
    summary_budget = 1500

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "DBA",
            "数据库架构",
            _load_prompt("dba"),
            model=model,
            skills=["database-design", "schema", "migration"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"原始需求：{state.get('input', '')}\n"
            f"架构设计：{(state.get('architect') or {}).get('output', '')[:2000]}\n"
            "请输出数据库 Schema 与迁移 SQL。必须输出一个合法的 JSON 对象：\n"
            "{\"files\": [{\"path\": \"schema.sql\", \"code\": \"...\"}, {\"path\": \"migrations/001_initial.sql\", \"code\": \"...\"}], "
            "\"report\": {\"tables\": [...], \"notes\": \"\"}}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        files: List[str] = []

        # 优先解析结构化 JSON 输出
        structured = await self._parse_json_output(output, AgentOutput)
        report: Dict[str, Any] = {}
        if structured and "files" in structured and "report" in structured:
            for f in structured.get("files", []):
                path = f.get("path", "")
                code = f.get("code", "")
                if not path:
                    continue
                if not path.endswith(".sql"):
                    path += ".sql"
                res = await self._write_file(path, code, workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(structured.get("report"), self.report_schema) or structured.get("report", {})
        else:
            # 兼容历史/测试中的 Markdown 代码块 + JSON 报告
            blocks = self._extract_code_blocks(output)
            for block in blocks:
                path = block["path"]
                if not path:
                    continue
                if not path.endswith(".sql"):
                    path += ".sql"
                res = await self._write_file(path, block["code"], workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(output, self.report_schema) or {}

        if not files:
            await self._write_file("schema.sql", output, workspace)
            files.append("schema.sql")

        return {
            "files": files,
            "tables": report.get("tables", []),
            "notes": report.get("notes", ""),
        }


class MemoryAgentFacade:
    """对外的 Memory Agent 接口，供 Orchestrator 调用。"""

    def __init__(self, base_dir: Optional[str] = None):
        self._impl = MemoryAgent(base_dir=base_dir)

    async def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        session = state.get("request_id", "default")
        query = state.get("input", "")
        memories = await self._impl.arecall(query, session_id=session, layer="working", top_k=5)
        summary = self._impl.summarize(state.get("history", []))
        return {"agent": "Memory", "role": "记忆", "memories": memories, "summary": summary}


def _load_prompt(agent_name: str) -> str:
    """从 prompts.yaml 加载 System Prompt；失败时返回内置提示。"""
    prompt_file = Path(__file__).with_name("prompts.yaml")
    try:
        with open(prompt_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get(agent_name, _FALLBACK_PROMPTS.get(agent_name, f"你是 {agent_name} Agent。"))
    except Exception:  # noqa: BLE001
        return _FALLBACK_PROMPTS.get(agent_name, f"你是 {agent_name} Agent。")


_FALLBACK_PROMPTS: Dict[str, str] = {
    "architect": "你是 Architect Agent，负责架构设计。禁止写实现代码。",
    "coder": "你是 Coder Agent，负责生成可运行代码。",
    "tester": "你是 Tester Agent，负责生成并执行测试。",
    "reviewer": "你是 Reviewer Agent，必须独立思考，不信任上游。",
    "docs": "你是 Docs Agent，负责同步文档。",
    "devops": "你是 DevOps Agent，负责 CI/CD 与部署。",
    "product_manager": "你是 Product Manager Agent，负责需求分析与 PRD。",
    "security": "你是 Security Agent，负责独立安全审查。",
    "dba": "你是 DBA Agent，负责数据库 Schema 与迁移。",
}
``` 代码块，支持前接 '# file: path' 等头部。"""
        blocks: List[Dict[str, str]] = []
        pattern = r"(?:^|\n)(?:[^\n`]*?(?:file|path|filename)[:\s]+([^\n]+))?\n?```(?:\w+)?\n(.*?)```"
        for m in re.finditer(pattern, text, re.DOTALL | re.I):
            path = (m.group(1) or "").strip().strip("`").strip()
            code = m.group(2)
            blocks.append({"path": path, "code": code})
        return blocks

    @staticmethod
    def _find_first_json_object(text: str) -> Optional[Any]:
        """从文本中定位第一个非空的 JSON 对象/数组。

        优先匹配 ```json ... ``` 代码块，再扫描内嵌的 JSON。
        """
        # 1) 显式 JSON 代码块
        for m in re.finditer(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL | re.I):
            block = m.group(1).strip()
            if not block:
                continue
            try:
                data = json.loads(block)
                if isinstance(data, (dict, list)) and data:
                    return data
            except json.JSONDecodeError:
                continue

        # 2) 用 JSONDecoder 扫描 { } / [ ]，跳过空的 {} / []
        decoder = json.JSONDecoder()
        idx = 0
        n = len(text)
        while idx < n:
            # 定位到下一个 { 或 [
            while idx < n and text[idx] not in "{[":
                idx += 1
            if idx >= n:
                return None
            try:
                data, end = decoder.raw_decode(text, idx)
                if isinstance(data, dict) and data:
                    return data
                if isinstance(data, list) and data:
                    return data
                idx += max(end, 1)
            except (json.JSONDecodeError, ValueError):
                idx += 1
        return None

    @staticmethod
    def _truncate_for_summary(
        value: Any,
        max_str: int = 400,
        max_list: int = 10,
        max_depth: int = 4,
        current_depth: int = 0,
    ) -> Any:
        """递归截断 dict/list/str，用于生成下游 Agent 可读的 summary。"""
        if current_depth > max_depth:
            return "..."
        if isinstance(value, str):
            if len(value) > max_str:
                return value[:max_str] + "... [truncated]"
            return value
        if isinstance(value, (list, tuple)):
            truncated = [BaseAgent._truncate_for_summary(v, max_str, max_list, max_depth, current_depth + 1) for v in value[:max_list]]
            if len(value) > max_list:
                truncated.append("...")
            return truncated
        if isinstance(value, dict):
            return {
                k: BaseAgent._truncate_for_summary(v, max_str, max_list, max_depth, current_depth + 1)
                for k, v in value.items()
            }
        return value

    def _summarize_result(self, result: Dict[str, Any]) -> str:
        """把 Agent 运行结果压缩成下游可传递的关键信息字符串。

        - 丢弃原始 LLM 输出（已解析到产物/文件和 report）
        - 递归截断长字符串/列表，避免 state 和 checkpoint 膨胀
        - 保证返回合法 JSON，便于下游直接解析
        """
        # 不向下游传递的元数据键
        excluded = {"output", "workspace", "model", "llm_kwargs", "agent", "role", "raw"}
        raw = {k: v for k, v in result.items() if k not in excluded and not k.startswith("_")}

        # 自适应截断：在保证合法 JSON 的前提下把 summary 压到 budget 内
        max_str, max_list = 400, 10
        while True:
            data = self._truncate_for_summary(raw, max_str=max_str, max_list=max_list)
            text = json.dumps(data, ensure_ascii=False, default=str)
            if len(text) <= self.summary_budget or max_str <= 50:
                break
            max_str = max(50, max_str // 2)
            max_list = max(3, max_list - 2)

        return text

    def _with_json_schema_prompt(self, prompt: str) -> str:
        """在 prompt 末尾追加 report_schema 对应的 JSON Schema，强化输出约束。"""
        if self.report_schema is None:
            return prompt + "\n\n你必须输出且仅输出一个合法 JSON 对象，不要包含解释文字。"
        try:
            schema = self.report_schema.model_json_schema()
        except Exception:  # noqa: BLE001
            return prompt + "\n\n你必须输出且仅输出一个合法 JSON 对象，不要包含解释文字。"
        return (
            prompt
            + "\n\n你必须输出且仅输出一个严格符合以下 JSON Schema 的单一 JSON 对象，"
            "不要包含任何解释文字或 Markdown 代码块包装：\n\n"
            f"```json\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n```"
        )

    @staticmethod
    def _parse_raw_json(text: Any) -> Optional[Any]:
        """从任意输入中提取 dict/list，不校验 schema（兼容旧版实现）。"""
        if text is None:
            return None
        if isinstance(text, (dict, list)):
            return text
        cleaned = str(text).strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`").strip()
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return BaseAgent._find_first_json_object(cleaned)

    async def _parse_json_output(
        self,
        text: Any,
        schema: Optional[Type[BaseModel]] = None,
    ) -> Optional[Dict[str, Any]]:
        """解析并可选做 Pydantic 校验；失败时尝试自我修复（最多 max_repair_attempts 次）。"""
        raw = text
        schema = schema or self.report_schema
        last_error = ""
        for attempt in range(self.max_repair_attempts + 1):
            data = BaseAgent._parse_raw_json(raw)
            if not isinstance(data, dict):
                if attempt == self.max_repair_attempts or not self.json_output:
                    return None
                last_error = "无法从文本中提取 JSON 对象"
                raw = await self.llm.achat(
                    self.system_prompt,
                    self._build_repair_prompt(str(text), last_error, schema),
                    json_mode=True,
                )
                continue
            if schema is None:
                return data
            try:
                return schema.model_validate(data).model_dump()
            except ValidationError as exc:
                if attempt == self.max_repair_attempts:
                    # 最后一次仍失败：如果 extra="ignore" 则返回原 dict；否则 None
                    return data
                last_error = str(exc)
                raw = await self.llm.achat(
                    self.system_prompt,
                    self._build_repair_prompt(str(text), last_error, schema),
                    json_mode=True,
                )
        return None

    def _build_repair_prompt(self, raw_output: str, error_message: str, schema: Optional[Type[BaseModel]]) -> str:
        schema_prompt = ""
        if schema is not None:
            try:
                schema_json = schema.model_json_schema()
                schema_prompt = f"\n必须严格符合的 JSON Schema：\n```json\n{json.dumps(schema_json, ensure_ascii=False, indent=2)}\n```\n"
            except Exception:  # noqa: BLE001
                pass
        return (
            "你之前生成的 JSON 输出无法通过校验，请重新生成。\n\n"
            f"原始输出：\n{raw_output}\n\n"
            f"错误信息：\n{error_message}\n"
            f"{schema_prompt}\n"
            "请只输出修复后的合法 JSON，不要解释。"
        )

    async def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        session = state.get("request_id", "default")
        workspace = self._workspace(state)
        workspace.mkdir(parents=True, exist_ok=True)
        state["workspace"] = str(workspace)

        memories = await self.memory.arecall(state.get("input", ""), session_id=session, layer="working", top_k=3)
        memory_text = "\n".join(str(m["value"]) for m in memories)
        prompt = self.build_prompt(state)
        full_prompt = f"相关记忆：\n{memory_text}\n\n{prompt}" if memory_text else prompt

        # 上下文压缩：超过阈值后保留头部和尾部
        if len(full_prompt) > Settings.context_compress_threshold():
            full_prompt = await self.memory.acompress_context(
                full_prompt, max_chars=Settings.context_window_limit()
            )

        # 敏感信息脱敏：进入 LLM 前与离开 LLM 后都进行 redaction
        full_prompt = SecretRedactor.redact(full_prompt)

        # 如果启用 json_mode 且绑定了 report_schema，把 JSON Schema 注入 prompt 强化约束
        if self.json_output:
            full_prompt = self._with_json_schema_prompt(full_prompt)

        resolved_model, kwargs = self.router.resolve(self.name, full_prompt)

        with self.telemetry.span(
            f"agent.{self.name}.llm",
            {"agent": self.name, "model": resolved_model, "request_id": session},
        ):
            output = await self.llm.achat(
                self.system_prompt,
                full_prompt,
                model=resolved_model,
                json_mode=self.json_output,
                **kwargs,
            )

        output = SecretRedactor.redact(output)

        # 近似 token 数与延迟统计
        self.telemetry.collector.counter(
            "llm_calls_total",
            "Total number of LLM calls",
            labelnames=["agent", "model"],
        ).inc(agent=self.name, model=resolved_model)
        self.telemetry.collector.histogram(
            "llm_prompt_tokens_approx",
            "Approximate prompt tokens",
            labelnames=["agent", "model"],
        ).observe(len(full_prompt) / 4, agent=self.name, model=resolved_model)
        self.telemetry.collector.histogram(
            "llm_output_tokens_approx",
            "Approximate output tokens",
            labelnames=["agent", "model"],
        ).observe(len(output) / 4, agent=self.name, model=resolved_model)

        result: Dict[str, Any] = {
            "agent": self.name,
            "role": self.role,
            "output": output,
            "workspace": str(workspace),
            "model": resolved_model,
            "llm_kwargs": kwargs,
        }
        extra = await self.postprocess(output, state)
        result.update(extra)

        # 生成关键信息摘要，替换原始 output，避免无效数据在 Agent 间传递
        result["output"] = self._summarize_result(result)
        # llm_kwargs 等内部元数据无需进入 LangGraph state
        result.pop("llm_kwargs", None)
        # 记忆层也存摘要，避免后续 recall 把原始大段输出塞进 prompt
        await self.memory.aremember("last_output", result["output"], session_id=session, layer="short", ttl=3600)

        return result

    def agent_card(self, url: str) -> AgentCard:
        return AgentCard(
            name=f"{self.name} Agent",
            url=url,
            skills=[AgentSkill(name=s) for s in self.skills],
            capabilities={"streaming": False, "autonomy": "L2", "modalities": ["text", "code"]},
        )


class ArchitectAgent(BaseAgent):
    json_output = True
    report_schema = DesignOutput
    summary_budget = 2000

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Architect",
            "系统架构师",
            _load_prompt("architect"),
            model=model,
            skills=["system-design", "api-contract", "tech-stack"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        prd = (state.get("product_manager") or {}).get("output", "")
        template = get_language(state)
        return (
            f"目标语言/技术栈：{template.display}\n"
            f"用户需求：{state.get('input', '')}\n"
            f"PRD：{prd[:1500] if prd else '无'}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            "请输出 JSON 格式架构设计：{modules, api_contract, tech_stack, mermaid, notes}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        design = await self._parse_json_output(output, self.report_schema)
        if design:
            await self._write_file("design.json", json.dumps(design, ensure_ascii=False, indent=2), workspace)
        return {"design_file": "design.json" if design else None, "parsed": design}


class CoderAgent(BaseAgent):
    json_output = True
    report_schema = CoderReport
    summary_budget = 1500

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Coder",
            "代码实现引擎",
            _load_prompt("coder"),
            model=model,
            skills=["code-implementation", "refactor", "python"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        dba_output = (state.get("dba") or {}).get("output", "")
        template = get_language(state)
        json_example = (
            '{"files": [{"path": "main.%s", "code": "..."}], '
            '"report": {"status": "completed", "files_modified": [...], '
            '"test_result": "passed", "note": ""}}'
        ) % template.file_ext
        return (
            f"目标语言/技术栈：{template.display}\n"
            f"构建命令：{template.build_cmd or '无'}\n"
            f"测试命令：{template.test_cmd}\n"
            f"用户生成文件扩展名：.{template.file_ext}，测试文件扩展名：.{template.test_ext}\n"
            f"用户需求：{state.get('input', '')}\n"
            f"架构设计：{(state.get('architect') or {}).get('output', '')[:2000]}\n"
            f"数据库设计：{dba_output[:1500] if dba_output else '无'}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            f"请生成可运行代码。必须输出一个合法的 JSON 对象：\n{json_example}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        template = get_language(state)
        files: List[str] = []
        security_issues: List[Dict[str, Any]] = []

        # 优先解析结构化 JSON 输出（JSON Mode / response_format）
        structured = await self._parse_json_output(output, AgentOutput)
        report: Dict[str, Any] = {}
        if structured and "files" in structured and "report" in structured:
            for f in structured.get("files", []):
                path = f.get("path", "")
                code = f.get("code", "")
                if not path:
                    continue
                if not path.endswith(f".{template.file_ext}"):
                    path += f".{template.file_ext}"
                issues = SafetyScanner.scan_code(code)
                security_issues.extend(issues)
                res = await self._write_file(path, code, workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(structured.get("report"), self.report_schema) or structured.get("report", {})
        else:
            # 兼容历史/测试中的 Markdown 代码块 + JSON 报告
            blocks = self._extract_code_blocks(output)
            for idx, block in enumerate(blocks, start=1):
                path = block["path"]
                if not path:
                    path = f"module_{idx}.{template.file_ext}"
                if not path.endswith(f".{template.file_ext}"):
                    path += f".{template.file_ext}"
                issues = SafetyScanner.scan_code(block["code"])
                security_issues.extend(issues)
                res = await self._write_file(path, block["code"], workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(output, self.report_schema) or {}

        # MOCK 降级：没有真实 LLM 时写一段占位代码，方便 CLI/测试继续跑
        if not files and self.llm.is_mock():
            stub = self._fallback_code(state.get("input", ""), template)
            res = await self._write_file(template.main_file(), stub, workspace)
            if res.get("success"):
                files.append(template.main_file())
            report = {
                "status": "mock_fallback",
                "files_modified": files,
                "test_result": "unknown",
                "note": f"MOCK 模式生成的占位代码 ({template.display})",
            }

        return {
            "files": files,
            "status": report.get("status", "completed" if files else "needs_help"),
            "test_result": report.get("test_result", "unknown"),
            "note": report.get("note", ""),
            "security_issues": security_issues,
        }

    @staticmethod
    def _fallback_code(requirement: str, template: Any) -> str:
        safe = re.sub(r"[^\w\u4e00-\u9fff]+", "_", requirement)[:30].strip("_") or "agent"
        if template.name == "java":
            class_name = safe.capitalize()
            return (
                f"package com.devagent;\n\n"
                f"public class {class_name} {{\n"
                f"    public static void main(String[] args) {{\n"
                f"        System.out.println(\"Hello from {safe}\");\n"
                f"    }}\n"
                f"}}\n"
            )
        if template.name == "go":
            return (
                f"package main\n\n"
                f"import \"fmt\"\n\n"
                f"func main() {{\n"
                f"    fmt.Println(\"Hello from {safe}\")\n"
                f"}}\n"
            )
        if template.name == "typescript":
            return (
                f"console.log(\"Hello from {safe}\");\n"
            )
        return f'"""Generated from requirement: {requirement}"""\n\ndef main():\n    print("Hello from {safe}")\n\nif __name__ == "__main__":\n    main()\n'


class TesterAgent(BaseAgent):
    json_output = True
    report_schema = TestReport
    summary_budget = 1200

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Tester",
            "测试工程师",
            _load_prompt("tester"),
            model=model,
            skills=["test-generation", "pytest", "coverage"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        workspace = state.get("workspace", "")
        template = get_language(state)
        code_files = (state.get("coder") or {}).get("files", [])
        code_snippets: List[str] = []
        for f in code_files[:3]:
            res = ToolSandbox.read_file(f, base_dir=workspace)  # 同步读取即可
            if res.get("success"):
                code_snippets.append(f"--- {f} ---\n{res['content'][:1500]}")
        json_example = (
            '{"files": [{"path": "test_%s", "code": "..."}], '
            '"report": {"passed": 0, "failed": 0, "coverage": 0.0, "report": ""}}'
        ) % template.file_ext
        return (
            f"目标语言：{template.display}\n"
            f"测试框架/命令：{template.test_cmd}\n"
            f"测试文件命名：*.{template.test_ext}\n"
            f"代码文件：{code_files}\n"
            f"{''.join(code_snippets)[:2500]}\n"
            f"工作目录：{workspace}\n"
            f"请生成对应语言的测试用例。必须输出一个合法的 JSON 对象：\n{json_example}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        template = get_language(state)
        files: List[str] = []

        # 优先解析结构化 JSON 输出
        structured = await self._parse_json_output(output, AgentOutput)
        report: Dict[str, Any] = {}
        if structured and "files" in structured and "report" in structured:
            for f in structured.get("files", []):
                path = f.get("path", "")
                code = f.get("code", "")
                if not path:
                    continue
                if not path.endswith(f".{template.test_ext}"):
                    path += f".{template.test_ext}"
                res = await self._write_file(path, code, workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(structured.get("report"), self.report_schema) or structured.get("report", {})
        else:
            # 兼容历史/测试中的 Markdown 代码块 + JSON 报告
            blocks = self._extract_code_blocks(output)
            for idx, block in enumerate(blocks, start=1):
                path = block["path"]
                if not path:
                    path = f"test_module_{idx}.{template.test_ext}"
                if not path.endswith(f".{template.test_ext}"):
                    path += f".{template.test_ext}"
                res = await self._write_file(path, block["code"], workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(output, self.report_schema) or {}

        if files:
            test_res = await self._run_command(f"{template.test_cmd} -q", workspace, timeout=15)
        else:
            test_res = {"success": False, "stdout": "", "stderr": "no tests generated"}

        passed = report.get("passed")
        failed = report.get("failed")
        if passed is None or failed is None:
            passed, failed = self._parse_test_summary(test_res.get("stdout", ""))

        return {
            "files": files,
            "passed": passed,
            "failed": failed,
            "coverage": report.get("coverage", 0.0),
            "report": (test_res.get("stdout", "") + "\n" + test_res.get("stderr", "")).strip(),
            "test_command_success": test_res.get("success", False),
        }

    @staticmethod
    def _parse_test_summary(stdout: str):
        m = re.search(r"(\d+)\s+passed", stdout)
        passed = int(m.group(1)) if m else 0
        m = re.search(r"(\d+)\s+failed", stdout)
        failed = int(m.group(1)) if m else 0
        return passed, failed


class ReviewerAgent(BaseAgent):
    json_output = True
    report_schema = ReviewReport
    summary_budget = 1200

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Reviewer",
            "代码审查",
            _load_prompt("reviewer"),
            model=model,
            skills=["code-review", "security", "performance"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"原始需求：{state.get('input', '')}\n"
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            f"测试报告：{(state.get('tester') or {}).get('report', '')[:1200]}\n"
            f"文档文件：{(state.get('docs') or {}).get('files', [])}\n"
            "请独立思考，从需求出发审查。输出 JSON：{severity, passed, issues, suggestions}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        report = await self._parse_json_output(output, self.report_schema)
        if not report:
            # 无法解析 JSON 时做最保守判断
            report = {
                "severity": "medium",
                "passed": False,
                "issues": ["Reviewer 输出无法解析为 JSON"],
                "suggestions": ["请检查 LLM 输出格式"],
            }
        review_file = "review_report.json"
        await self._write_file(review_file, json.dumps(report, ensure_ascii=False, indent=2), workspace)
        report["report_file"] = review_file
        return report


class DocsAgent(BaseAgent):
    summary_budget = 800

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Docs",
            "文档工程师",
            _load_prompt("docs"),
            model=model,
            skills=["documentation", "readme", "api-doc"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"架构：{str((state.get('architect') or {}).get('output', ''))[:800]}\n"
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            "请生成 README.md 与 API.md。用代码块标明文件路径，如 '# file: README.md'。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        blocks = self._extract_code_blocks(output)
        files: List[str] = []
        for block in blocks:
            path = block["path"] or "README.md"
            if not path.endswith(".md"):
                path += ".md"
            res = await self._write_file(f"docs/{path}", block["code"], workspace)
            if res.get("success"):
                files.append(f"docs/{path}")
        if not files:
            await self._write_file("docs/README.md", output, workspace)
            files.append("docs/README.md")
        return {"files": files}


class DevOpsAgent(BaseAgent):
    summary_budget = 1000

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "DevOps",
            "部署运维",
            _load_prompt("devops"),
            model=model,
            skills=["docker", "ci-cd", "deployment"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            "请生成 Dockerfile、docker-compose.yml 与 CI/CD 配置摘要，并说明部署前需人工确认。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        blocks = self._extract_code_blocks(output)
        files: List[str] = []
        for block in blocks:
            path = block["path"]
            if not path:
                continue
            res = await self._write_file(path, block["code"], workspace)
            if res.get("success"):
                files.append(path)
        if not files:
            await self._write_file("deploy_summary.md", output, workspace)
            files.append("deploy_summary.md")
        return {"files": files, "needs_approval": True}


class ProductManagerAgent(BaseAgent):
    report_schema = PRDOutput
    summary_budget = 1200

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "ProductManager",
            "产品经理",
            _load_prompt("product_manager"),
            model=model,
            skills=["requirement-analysis", "prd", "user-stories"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"用户需求：{state.get('input', '')}\n"
            "请把需求拆分为 PRD、用户故事和验收标准。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        report = await self._parse_json_output(output, self.report_schema) or {}
        prd_file = "prd.md"
        # 如果结构化输出里有 prd_markdown，优先写入；否则把原始输出作为 PRD 正文
        prd_body = report.get("prd_markdown") or output
        await self._write_file(prd_file, prd_body, workspace)
        return {
            "prd_file": prd_file,
            "user_stories": report.get("user_stories", []),
            "acceptance_criteria": report.get("acceptance_criteria", []),
            "parsed": report,
        }


class SecurityAgent(BaseAgent):
    json_output = True
    report_schema = ReviewReport
    summary_budget = 1200

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Security",
            "安全审查",
            _load_prompt("security"),
            model=model,
            skills=["security-review", "vulnerability", "compliance"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"原始需求：{state.get('input', '')}\n"
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            f"测试文件：{(state.get('tester') or {}).get('files', [])}\n"
            f"架构设计：{(state.get('architect') or {}).get('output', '')[:1500]}\n"
            "请独立进行安全审查，输出 JSON {severity, passed, issues, suggestions}。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        report = await self._parse_json_output(output, self.report_schema)
        if not report:
            report = {
                "severity": "medium",
                "passed": False,
                "issues": ["Security Agent 输出无法解析为 JSON"],
                "suggestions": ["请检查 LLM 输出格式"],
            }
        report_file = "security_report.json"
        await self._write_file(report_file, json.dumps(report, ensure_ascii=False, indent=2), workspace)
        report["report_file"] = report_file
        return report


class DBAAgent(BaseAgent):
    json_output = True
    report_schema = DBAReport
    summary_budget = 1500

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "DBA",
            "数据库架构",
            _load_prompt("dba"),
            model=model,
            skills=["database-design", "schema", "migration"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"原始需求：{state.get('input', '')}\n"
            f"架构设计：{(state.get('architect') or {}).get('output', '')[:2000]}\n"
            "请输出数据库 Schema 与迁移 SQL。必须输出一个合法的 JSON 对象：\n"
            "{\"files\": [{\"path\": \"schema.sql\", \"code\": \"...\"}, {\"path\": \"migrations/001_initial.sql\", \"code\": \"...\"}], "
            "\"report\": {\"tables\": [...], \"notes\": \"\"}}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        files: List[str] = []

        # 优先解析结构化 JSON 输出
        structured = await self._parse_json_output(output, AgentOutput)
        report: Dict[str, Any] = {}
        if structured and "files" in structured and "report" in structured:
            for f in structured.get("files", []):
                path = f.get("path", "")
                code = f.get("code", "")
                if not path:
                    continue
                if not path.endswith(".sql"):
                    path += ".sql"
                res = await self._write_file(path, code, workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(structured.get("report"), self.report_schema) or structured.get("report", {})
        else:
            # 兼容历史/测试中的 Markdown 代码块 + JSON 报告
            blocks = self._extract_code_blocks(output)
            for block in blocks:
                path = block["path"]
                if not path:
                    continue
                if not path.endswith(".sql"):
                    path += ".sql"
                res = await self._write_file(path, block["code"], workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(output, self.report_schema) or {}

        if not files:
            await self._write_file("schema.sql", output, workspace)
            files.append("schema.sql")

        return {
            "files": files,
            "tables": report.get("tables", []),
            "notes": report.get("notes", ""),
        }


class MemoryAgentFacade:
    """对外的 Memory Agent 接口，供 Orchestrator 调用。"""

    def __init__(self, base_dir: Optional[str] = None):
        self._impl = MemoryAgent(base_dir=base_dir)

    async def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        session = state.get("request_id", "default")
        query = state.get("input", "")
        memories = await self._impl.arecall(query, session_id=session, layer="working", top_k=5)
        summary = self._impl.summarize(state.get("history", []))
        return {"agent": "Memory", "role": "记忆", "memories": memories, "summary": summary}


def _load_prompt(agent_name: str) -> str:
    """从 prompts.yaml 加载 System Prompt；失败时返回内置提示。"""
    prompt_file = Path(__file__).with_name("prompts.yaml")
    try:
        with open(prompt_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get(agent_name, _FALLBACK_PROMPTS.get(agent_name, f"你是 {agent_name} Agent。"))
    except Exception:  # noqa: BLE001
        return _FALLBACK_PROMPTS.get(agent_name, f"你是 {agent_name} Agent。")


_FALLBACK_PROMPTS: Dict[str, str] = {
    "architect": "你是 Architect Agent，负责架构设计。禁止写实现代码。",
    "coder": "你是 Coder Agent，负责生成可运行代码。",
    "tester": "你是 Tester Agent，负责生成并执行测试。",
    "reviewer": "你是 Reviewer Agent，必须独立思考，不信任上游。",
    "docs": "你是 Docs Agent，负责同步文档。",
    "devops": "你是 DevOps Agent，负责 CI/CD 与部署。",
    "product_manager": "你是 Product Manager Agent，负责需求分析与 PRD。",
    "security": "你是 Security Agent，负责独立安全审查。",
    "dba": "你是 DBA Agent，负责数据库 Schema 与迁移。",
}
``` 代码块，支持前接 '# file: path' 等头部。"""
        blocks: List[Dict[str, str]] = []
        pattern = r"(?:^|\n)(?:[^\n`]*?(?:file|path|filename)[:\s]+([^\n]+))?\n?```(?:\w+)?\n(.*?)```"
        for m in re.finditer(pattern, text, re.DOTALL | re.I):
            path = (m.group(1) or "").strip().strip("`").strip()
            code = m.group(2)
            blocks.append({"path": path, "code": code})
        return blocks

    @staticmethod
    def _find_first_json_object(text: str) -> Optional[Any]:
        """从文本中定位第一个非空的 JSON 对象/数组。

        优先匹配 ```json ... ``` 代码块，再扫描内嵌的 JSON。
        """
        # 1) 显式 JSON 代码块
        for m in re.finditer(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL | re.I):
            block = m.group(1).strip()
            if not block:
                continue
            try:
                data = json.loads(block)
                if isinstance(data, (dict, list)) and data:
                    return data
            except json.JSONDecodeError:
                continue

        # 2) 用 JSONDecoder 扫描 { } / [ ]，跳过空的 {} / []
        decoder = json.JSONDecoder()
        idx = 0
        n = len(text)
        while idx < n:
            # 定位到下一个 { 或 [
            while idx < n and text[idx] not in "{[":
                idx += 1
            if idx >= n:
                return None
            try:
                data, end = decoder.raw_decode(text, idx)
                if isinstance(data, dict) and data:
                    return data
                if isinstance(data, list) and data:
                    return data
                idx += max(end, 1)
            except (json.JSONDecodeError, ValueError):
                idx += 1
        return None

    @staticmethod
    def _truncate_for_summary(
        value: Any,
        max_str: int = 400,
        max_list: int = 10,
        max_depth: int = 4,
        current_depth: int = 0,
    ) -> Any:
        """递归截断 dict/list/str，用于生成下游 Agent 可读的 summary。"""
        if current_depth > max_depth:
            return "..."
        if isinstance(value, str):
            if len(value) > max_str:
                return value[:max_str] + "... [truncated]"
            return value
        if isinstance(value, (list, tuple)):
            truncated = [BaseAgent._truncate_for_summary(v, max_str, max_list, max_depth, current_depth + 1) for v in value[:max_list]]
            if len(value) > max_list:
                truncated.append("...")
            return truncated
        if isinstance(value, dict):
            return {
                k: BaseAgent._truncate_for_summary(v, max_str, max_list, max_depth, current_depth + 1)
                for k, v in value.items()
            }
        return value

    def _summarize_result(self, result: Dict[str, Any]) -> str:
        """把 Agent 运行结果压缩成下游可传递的关键信息字符串。

        - 丢弃原始 LLM 输出（已解析到产物/文件和 report）
        - 递归截断长字符串/列表，避免 state 和 checkpoint 膨胀
        - 保证返回合法 JSON，便于下游直接解析
        """
        # 不向下游传递的元数据键
        excluded = {"output", "workspace", "model", "llm_kwargs", "agent", "role", "raw"}
        raw = {k: v for k, v in result.items() if k not in excluded and not k.startswith("_")}

        # 自适应截断：在保证合法 JSON 的前提下把 summary 压到 budget 内
        max_str, max_list = 400, 10
        while True:
            data = self._truncate_for_summary(raw, max_str=max_str, max_list=max_list)
            text = json.dumps(data, ensure_ascii=False, default=str)
            if len(text) <= self.summary_budget or max_str <= 50:
                break
            max_str = max(50, max_str // 2)
            max_list = max(3, max_list - 2)

        return text

    def _with_json_schema_prompt(self, prompt: str) -> str:
        """在 prompt 末尾追加 report_schema 对应的 JSON Schema，强化输出约束。"""
        if self.report_schema is None:
            return prompt + "\n\n你必须输出且仅输出一个合法 JSON 对象，不要包含解释文字。"
        try:
            schema = self.report_schema.model_json_schema()
        except Exception:  # noqa: BLE001
            return prompt + "\n\n你必须输出且仅输出一个合法 JSON 对象，不要包含解释文字。"
        return (
            prompt
            + "\n\n你必须输出且仅输出一个严格符合以下 JSON Schema 的单一 JSON 对象，"
            "不要包含任何解释文字或 Markdown 代码块包装：\n\n"
            f"```json\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n```"
        )

    @staticmethod
    def _parse_raw_json(text: Any) -> Optional[Any]:
        """从任意输入中提取 dict/list，不校验 schema（兼容旧版实现）。"""
        if text is None:
            return None
        if isinstance(text, (dict, list)):
            return text
        cleaned = str(text).strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`").strip()
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return BaseAgent._find_first_json_object(cleaned)

    async def _parse_json_output(
        self,
        text: Any,
        schema: Optional[Type[BaseModel]] = None,
    ) -> Optional[Dict[str, Any]]:
        """解析并可选做 Pydantic 校验；失败时尝试自我修复（最多 max_repair_attempts 次）。"""
        raw = text
        schema = schema or self.report_schema
        last_error = ""
        for attempt in range(self.max_repair_attempts + 1):
            data = BaseAgent._parse_raw_json(raw)
            if not isinstance(data, dict):
                if attempt == self.max_repair_attempts or not self.json_output:
                    return None
                last_error = "无法从文本中提取 JSON 对象"
                raw = await self.llm.achat(
                    self.system_prompt,
                    self._build_repair_prompt(str(text), last_error, schema),
                    json_mode=True,
                )
                continue
            if schema is None:
                return data
            try:
                return schema.model_validate(data).model_dump()
            except ValidationError as exc:
                if attempt == self.max_repair_attempts:
                    # 最后一次仍失败：如果 extra="ignore" 则返回原 dict；否则 None
                    return data
                last_error = str(exc)
                raw = await self.llm.achat(
                    self.system_prompt,
                    self._build_repair_prompt(str(text), last_error, schema),
                    json_mode=True,
                )
        return None

    def _build_repair_prompt(self, raw_output: str, error_message: str, schema: Optional[Type[BaseModel]]) -> str:
        schema_prompt = ""
        if schema is not None:
            try:
                schema_json = schema.model_json_schema()
                schema_prompt = f"\n必须严格符合的 JSON Schema：\n```json\n{json.dumps(schema_json, ensure_ascii=False, indent=2)}\n```\n"
            except Exception:  # noqa: BLE001
                pass
        return (
            "你之前生成的 JSON 输出无法通过校验，请重新生成。\n\n"
            f"原始输出：\n{raw_output}\n\n"
            f"错误信息：\n{error_message}\n"
            f"{schema_prompt}\n"
            "请只输出修复后的合法 JSON，不要解释。"
        )

    async def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        session = state.get("request_id", "default")
        workspace = self._workspace(state)
        workspace.mkdir(parents=True, exist_ok=True)
        state["workspace"] = str(workspace)

        memories = self.memory.recall(state.get("input", ""), session_id=session, layer="working", top_k=3)
        memory_text = "\n".join(str(m["value"]) for m in memories)
        prompt = self.build_prompt(state)
        full_prompt = f"相关记忆：\n{memory_text}\n\n{prompt}" if memory_text else prompt

        # 上下文压缩：超过阈值后保留头部和尾部
        if len(full_prompt) > Settings.context_compress_threshold():
            full_prompt = self.memory.compress_context(
                full_prompt, max_chars=Settings.context_window_limit()
            )

        # 敏感信息脱敏：进入 LLM 前与离开 LLM 后都进行 redaction
        full_prompt = SecretRedactor.redact(full_prompt)

        # 如果启用 json_mode 且绑定了 report_schema，把 JSON Schema 注入 prompt 强化约束
        if self.json_output:
            full_prompt = self._with_json_schema_prompt(full_prompt)

        resolved_model, kwargs = self.router.resolve(self.name, full_prompt)

        with self.telemetry.span(
            f"agent.{self.name}.llm",
            {"agent": self.name, "model": resolved_model, "request_id": session},
        ):
            output = await self.llm.achat(
                self.system_prompt,
                full_prompt,
                model=resolved_model,
                json_mode=self.json_output,
                **kwargs,
            )

        output = SecretRedactor.redact(output)

        # 近似 token 数与延迟统计
        self.telemetry.collector.counter(
            "llm_calls_total",
            "Total number of LLM calls",
            labelnames=["agent", "model"],
        ).inc(agent=self.name, model=resolved_model)
        self.telemetry.collector.histogram(
            "llm_prompt_tokens_approx",
            "Approximate prompt tokens",
            labelnames=["agent", "model"],
        ).observe(len(full_prompt) / 4, agent=self.name, model=resolved_model)
        self.telemetry.collector.histogram(
            "llm_output_tokens_approx",
            "Approximate output tokens",
            labelnames=["agent", "model"],
        ).observe(len(output) / 4, agent=self.name, model=resolved_model)

        result: Dict[str, Any] = {
            "agent": self.name,
            "role": self.role,
            "output": output,
            "workspace": str(workspace),
            "model": resolved_model,
            "llm_kwargs": kwargs,
        }
        extra = await self.postprocess(output, state)
        result.update(extra)

        # 生成关键信息摘要，替换原始 output，避免无效数据在 Agent 间传递
        result["output"] = self._summarize_result(result)
        # llm_kwargs 等内部元数据无需进入 LangGraph state
        result.pop("llm_kwargs", None)
        # 记忆层也存摘要，避免后续 recall 把原始大段输出塞进 prompt
        self.memory.remember("last_output", result["output"], session_id=session, layer="short", ttl=3600)

        return result

    def agent_card(self, url: str) -> AgentCard:
        return AgentCard(
            name=f"{self.name} Agent",
            url=url,
            skills=[AgentSkill(name=s) for s in self.skills],
            capabilities={"streaming": False, "autonomy": "L2", "modalities": ["text", "code"]},
        )


class ArchitectAgent(BaseAgent):
    json_output = True
    report_schema = DesignOutput
    summary_budget = 2000

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Architect",
            "系统架构师",
            _load_prompt("architect"),
            model=model,
            skills=["system-design", "api-contract", "tech-stack"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        prd = (state.get("product_manager") or {}).get("output", "")
        template = get_language(state)
        return (
            f"目标语言/技术栈：{template.display}\n"
            f"用户需求：{state.get('input', '')}\n"
            f"PRD：{prd[:1500] if prd else '无'}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            "请输出 JSON 格式架构设计：{modules, api_contract, tech_stack, mermaid, notes}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        design = await self._parse_json_output(output, self.report_schema)
        if design:
            await self._write_file("design.json", json.dumps(design, ensure_ascii=False, indent=2), workspace)
        return {"design_file": "design.json" if design else None, "parsed": design}


class CoderAgent(BaseAgent):
    json_output = True
    report_schema = CoderReport
    summary_budget = 1500

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Coder",
            "代码实现引擎",
            _load_prompt("coder"),
            model=model,
            skills=["code-implementation", "refactor", "python"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        dba_output = (state.get("dba") or {}).get("output", "")
        template = get_language(state)
        json_example = (
            '{"files": [{"path": "main.%s", "code": "..."}], '
            '"report": {"status": "completed", "files_modified": [...], '
            '"test_result": "passed", "note": ""}}'
        ) % template.file_ext
        return (
            f"目标语言/技术栈：{template.display}\n"
            f"构建命令：{template.build_cmd or '无'}\n"
            f"测试命令：{template.test_cmd}\n"
            f"用户生成文件扩展名：.{template.file_ext}，测试文件扩展名：.{template.test_ext}\n"
            f"用户需求：{state.get('input', '')}\n"
            f"架构设计：{(state.get('architect') or {}).get('output', '')[:2000]}\n"
            f"数据库设计：{dba_output[:1500] if dba_output else '无'}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            f"请生成可运行代码。必须输出一个合法的 JSON 对象：\n{json_example}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        template = get_language(state)
        files: List[str] = []
        security_issues: List[Dict[str, Any]] = []

        # 优先解析结构化 JSON 输出（JSON Mode / response_format）
        structured = await self._parse_json_output(output, AgentOutput)
        report: Dict[str, Any] = {}
        if structured and "files" in structured and "report" in structured:
            for f in structured.get("files", []):
                path = f.get("path", "")
                code = f.get("code", "")
                if not path:
                    continue
                if not path.endswith(f".{template.file_ext}"):
                    path += f".{template.file_ext}"
                issues = SafetyScanner.scan_code(code)
                security_issues.extend(issues)
                res = await self._write_file(path, code, workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(structured.get("report"), self.report_schema) or structured.get("report", {})
        else:
            # 兼容历史/测试中的 Markdown 代码块 + JSON 报告
            blocks = self._extract_code_blocks(output)
            for idx, block in enumerate(blocks, start=1):
                path = block["path"]
                if not path:
                    path = f"module_{idx}.{template.file_ext}"
                if not path.endswith(f".{template.file_ext}"):
                    path += f".{template.file_ext}"
                issues = SafetyScanner.scan_code(block["code"])
                security_issues.extend(issues)
                res = await self._write_file(path, block["code"], workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(output, self.report_schema) or {}

        # MOCK 降级：没有真实 LLM 时写一段占位代码，方便 CLI/测试继续跑
        if not files and self.llm.is_mock():
            stub = self._fallback_code(state.get("input", ""), template)
            res = await self._write_file(template.main_file(), stub, workspace)
            if res.get("success"):
                files.append(template.main_file())
            report = {
                "status": "mock_fallback",
                "files_modified": files,
                "test_result": "unknown",
                "note": f"MOCK 模式生成的占位代码 ({template.display})",
            }

        return {
            "files": files,
            "status": report.get("status", "completed" if files else "needs_help"),
            "test_result": report.get("test_result", "unknown"),
            "note": report.get("note", ""),
            "security_issues": security_issues,
        }

    @staticmethod
    def _fallback_code(requirement: str, template: Any) -> str:
        safe = re.sub(r"[^\w\u4e00-\u9fff]+", "_", requirement)[:30].strip("_") or "agent"
        if template.name == "java":
            class_name = safe.capitalize()
            return (
                f"package com.devagent;\n\n"
                f"public class {class_name} {{\n"
                f"    public static void main(String[] args) {{\n"
                f"        System.out.println(\"Hello from {safe}\");\n"
                f"    }}\n"
                f"}}\n"
            )
        if template.name == "go":
            return (
                f"package main\n\n"
                f"import \"fmt\"\n\n"
                f"func main() {{\n"
                f"    fmt.Println(\"Hello from {safe}\")\n"
                f"}}\n"
            )
        if template.name == "typescript":
            return (
                f"console.log(\"Hello from {safe}\");\n"
            )
        return f'"""Generated from requirement: {requirement}"""\n\ndef main():\n    print("Hello from {safe}")\n\nif __name__ == "__main__":\n    main()\n'


class TesterAgent(BaseAgent):
    json_output = True
    report_schema = TestReport
    summary_budget = 1200

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Tester",
            "测试工程师",
            _load_prompt("tester"),
            model=model,
            skills=["test-generation", "pytest", "coverage"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        workspace = state.get("workspace", "")
        template = get_language(state)
        code_files = (state.get("coder") or {}).get("files", [])
        code_snippets: List[str] = []
        for f in code_files[:3]:
            res = ToolSandbox.read_file(f, base_dir=workspace)  # 同步读取即可
            if res.get("success"):
                code_snippets.append(f"--- {f} ---\n{res['content'][:1500]}")
        json_example = (
            '{"files": [{"path": "test_%s", "code": "..."}], '
            '"report": {"passed": 0, "failed": 0, "coverage": 0.0, "report": ""}}'
        ) % template.file_ext
        return (
            f"目标语言：{template.display}\n"
            f"测试框架/命令：{template.test_cmd}\n"
            f"测试文件命名：*.{template.test_ext}\n"
            f"代码文件：{code_files}\n"
            f"{''.join(code_snippets)[:2500]}\n"
            f"工作目录：{workspace}\n"
            f"请生成对应语言的测试用例。必须输出一个合法的 JSON 对象：\n{json_example}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        template = get_language(state)
        files: List[str] = []

        # 优先解析结构化 JSON 输出
        structured = await self._parse_json_output(output, AgentOutput)
        report: Dict[str, Any] = {}
        if structured and "files" in structured and "report" in structured:
            for f in structured.get("files", []):
                path = f.get("path", "")
                code = f.get("code", "")
                if not path:
                    continue
                if not path.endswith(f".{template.test_ext}"):
                    path += f".{template.test_ext}"
                res = await self._write_file(path, code, workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(structured.get("report"), self.report_schema) or structured.get("report", {})
        else:
            # 兼容历史/测试中的 Markdown 代码块 + JSON 报告
            blocks = self._extract_code_blocks(output)
            for idx, block in enumerate(blocks, start=1):
                path = block["path"]
                if not path:
                    path = f"test_module_{idx}.{template.test_ext}"
                if not path.endswith(f".{template.test_ext}"):
                    path += f".{template.test_ext}"
                res = await self._write_file(path, block["code"], workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(output, self.report_schema) or {}

        if files:
            test_res = await self._run_command(f"{template.test_cmd} -q", workspace, timeout=15)
        else:
            test_res = {"success": False, "stdout": "", "stderr": "no tests generated"}

        passed = report.get("passed")
        failed = report.get("failed")
        if passed is None or failed is None:
            passed, failed = self._parse_test_summary(test_res.get("stdout", ""))

        return {
            "files": files,
            "passed": passed,
            "failed": failed,
            "coverage": report.get("coverage", 0.0),
            "report": (test_res.get("stdout", "") + "\n" + test_res.get("stderr", "")).strip(),
            "test_command_success": test_res.get("success", False),
        }

    @staticmethod
    def _parse_test_summary(stdout: str):
        m = re.search(r"(\d+)\s+passed", stdout)
        passed = int(m.group(1)) if m else 0
        m = re.search(r"(\d+)\s+failed", stdout)
        failed = int(m.group(1)) if m else 0
        return passed, failed


class ReviewerAgent(BaseAgent):
    json_output = True
    report_schema = ReviewReport
    summary_budget = 1200

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Reviewer",
            "代码审查",
            _load_prompt("reviewer"),
            model=model,
            skills=["code-review", "security", "performance"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"原始需求：{state.get('input', '')}\n"
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            f"测试报告：{(state.get('tester') or {}).get('report', '')[:1200]}\n"
            f"文档文件：{(state.get('docs') or {}).get('files', [])}\n"
            "请独立思考，从需求出发审查。输出 JSON：{severity, passed, issues, suggestions}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        report = await self._parse_json_output(output, self.report_schema)
        if not report:
            # 无法解析 JSON 时做最保守判断
            report = {
                "severity": "medium",
                "passed": False,
                "issues": ["Reviewer 输出无法解析为 JSON"],
                "suggestions": ["请检查 LLM 输出格式"],
            }
        review_file = "review_report.json"
        await self._write_file(review_file, json.dumps(report, ensure_ascii=False, indent=2), workspace)
        report["report_file"] = review_file
        return report


class DocsAgent(BaseAgent):
    summary_budget = 800

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Docs",
            "文档工程师",
            _load_prompt("docs"),
            model=model,
            skills=["documentation", "readme", "api-doc"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"架构：{str((state.get('architect') or {}).get('output', ''))[:800]}\n"
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            "请生成 README.md 与 API.md。用代码块标明文件路径，如 '# file: README.md'。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        blocks = self._extract_code_blocks(output)
        files: List[str] = []
        for block in blocks:
            path = block["path"] or "README.md"
            if not path.endswith(".md"):
                path += ".md"
            res = await self._write_file(f"docs/{path}", block["code"], workspace)
            if res.get("success"):
                files.append(f"docs/{path}")
        if not files:
            await self._write_file("docs/README.md", output, workspace)
            files.append("docs/README.md")
        return {"files": files}


class DevOpsAgent(BaseAgent):
    summary_budget = 1000

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "DevOps",
            "部署运维",
            _load_prompt("devops"),
            model=model,
            skills=["docker", "ci-cd", "deployment"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            "请生成 Dockerfile、docker-compose.yml 与 CI/CD 配置摘要，并说明部署前需人工确认。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        blocks = self._extract_code_blocks(output)
        files: List[str] = []
        for block in blocks:
            path = block["path"]
            if not path:
                continue
            res = await self._write_file(path, block["code"], workspace)
            if res.get("success"):
                files.append(path)
        if not files:
            await self._write_file("deploy_summary.md", output, workspace)
            files.append("deploy_summary.md")
        return {"files": files, "needs_approval": True}


class ProductManagerAgent(BaseAgent):
    report_schema = PRDOutput
    summary_budget = 1200

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "ProductManager",
            "产品经理",
            _load_prompt("product_manager"),
            model=model,
            skills=["requirement-analysis", "prd", "user-stories"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"用户需求：{state.get('input', '')}\n"
            "请把需求拆分为 PRD、用户故事和验收标准。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        report = await self._parse_json_output(output, self.report_schema) or {}
        prd_file = "prd.md"
        # 如果结构化输出里有 prd_markdown，优先写入；否则把原始输出作为 PRD 正文
        prd_body = report.get("prd_markdown") or output
        await self._write_file(prd_file, prd_body, workspace)
        return {
            "prd_file": prd_file,
            "user_stories": report.get("user_stories", []),
            "acceptance_criteria": report.get("acceptance_criteria", []),
            "parsed": report,
        }


class SecurityAgent(BaseAgent):
    json_output = True
    report_schema = ReviewReport
    summary_budget = 1200

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Security",
            "安全审查",
            _load_prompt("security"),
            model=model,
            skills=["security-review", "vulnerability", "compliance"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"原始需求：{state.get('input', '')}\n"
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            f"测试文件：{(state.get('tester') or {}).get('files', [])}\n"
            f"架构设计：{(state.get('architect') or {}).get('output', '')[:1500]}\n"
            "请独立进行安全审查，输出 JSON {severity, passed, issues, suggestions}。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        report = await self._parse_json_output(output, self.report_schema)
        if not report:
            report = {
                "severity": "medium",
                "passed": False,
                "issues": ["Security Agent 输出无法解析为 JSON"],
                "suggestions": ["请检查 LLM 输出格式"],
            }
        report_file = "security_report.json"
        await self._write_file(report_file, json.dumps(report, ensure_ascii=False, indent=2), workspace)
        report["report_file"] = report_file
        return report


class DBAAgent(BaseAgent):
    json_output = True
    report_schema = DBAReport
    summary_budget = 1500

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "DBA",
            "数据库架构",
            _load_prompt("dba"),
            model=model,
            skills=["database-design", "schema", "migration"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"原始需求：{state.get('input', '')}\n"
            f"架构设计：{(state.get('architect') or {}).get('output', '')[:2000]}\n"
            "请输出数据库 Schema 与迁移 SQL。必须输出一个合法的 JSON 对象：\n"
            "{\"files\": [{\"path\": \"schema.sql\", \"code\": \"...\"}, {\"path\": \"migrations/001_initial.sql\", \"code\": \"...\"}], "
            "\"report\": {\"tables\": [...], \"notes\": \"\"}}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        files: List[str] = []

        # 优先解析结构化 JSON 输出
        structured = await self._parse_json_output(output, AgentOutput)
        report: Dict[str, Any] = {}
        if structured and "files" in structured and "report" in structured:
            for f in structured.get("files", []):
                path = f.get("path", "")
                code = f.get("code", "")
                if not path:
                    continue
                if not path.endswith(".sql"):
                    path += ".sql"
                res = await self._write_file(path, code, workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(structured.get("report"), self.report_schema) or structured.get("report", {})
        else:
            # 兼容历史/测试中的 Markdown 代码块 + JSON 报告
            blocks = self._extract_code_blocks(output)
            for block in blocks:
                path = block["path"]
                if not path:
                    continue
                if not path.endswith(".sql"):
                    path += ".sql"
                res = await self._write_file(path, block["code"], workspace)
                if res.get("success"):
                    files.append(path)
            report = await self._parse_json_output(output, self.report_schema) or {}

        if not files:
            await self._write_file("schema.sql", output, workspace)
            files.append("schema.sql")

        return {
            "files": files,
            "tables": report.get("tables", []),
            "notes": report.get("notes", ""),
        }


class MemoryAgentFacade:
    """对外的 Memory Agent 接口，供 Orchestrator 调用。"""

    def __init__(self, base_dir: str = "memory_store"):
        self._impl = MemoryAgent(base_dir=base_dir)

    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        session = state.get("request_id", "default")
        query = state.get("input", "")
        memories = self._impl.recall(query, session_id=session, layer="working", top_k=5)
        summary = self._impl.summarize(state.get("history", []))
        return {"agent": "Memory", "role": "记忆", "memories": memories, "summary": summary}


def _load_prompt(agent_name: str) -> str:
    """从 prompts.yaml 加载 System Prompt；失败时返回内置提示。"""
    prompt_file = Path(__file__).with_name("prompts.yaml")
    try:
        with open(prompt_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get(agent_name, _FALLBACK_PROMPTS.get(agent_name, f"你是 {agent_name} Agent。"))
    except Exception:  # noqa: BLE001
        return _FALLBACK_PROMPTS.get(agent_name, f"你是 {agent_name} Agent。")


_FALLBACK_PROMPTS: Dict[str, str] = {
    "architect": "你是 Architect Agent，负责架构设计。禁止写实现代码。",
    "coder": "你是 Coder Agent，负责生成可运行代码。",
    "tester": "你是 Tester Agent，负责生成并执行测试。",
    "reviewer": "你是 Reviewer Agent，必须独立思考，不信任上游。",
    "docs": "你是 Docs Agent，负责同步文档。",
    "devops": "你是 DevOps Agent，负责 CI/CD 与部署。",
    "product_manager": "你是 Product Manager Agent，负责需求分析与 PRD。",
    "security": "你是 Security Agent，负责独立安全审查。",
    "dba": "你是 DBA Agent，负责数据库 Schema 与迁移。",
}
``` 代码块，支持前接 '# file: path' 等头部。"""
        blocks: List[Dict[str, str]] = []
        pattern = r"(?:^|\n)(?:[^\n`]*?(?:file|path|filename)[:\s]+([^\n]+))?\n?```(?:\w+)?\n(.*?)```"
        for m in re.finditer(pattern, text, re.DOTALL | re.I):
            path = (m.group(1) or "").strip().strip("`").strip()
            code = m.group(2)
            blocks.append({"path": path, "code": code})
        return blocks

    @staticmethod
    def _find_first_json_object(text: str) -> Optional[Any]:
        """从文本中定位第一个非空的 JSON 对象/数组。

        优先匹配 ```json ... ``` 代码块，再扫描内嵌的 JSON。
        """
        # 1) 显式 JSON 代码块
        for m in re.finditer(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL | re.I):
            block = m.group(1).strip()
            if not block:
                continue
            try:
                data = json.loads(block)
                if isinstance(data, (dict, list)) and data:
                    return data
            except json.JSONDecodeError:
                continue

        # 2) 用 JSONDecoder 扫描 { } / [ ]，跳过空的 {} / []
        decoder = json.JSONDecoder()
        idx = 0
        n = len(text)
        while idx < n:
            # 定位到下一个 { 或 [
            while idx < n and text[idx] not in "{[":
                idx += 1
            if idx >= n:
                return None
            try:
                data, end = decoder.raw_decode(text, idx)
                if isinstance(data, dict) and data:
                    return data
                if isinstance(data, list) and data:
                    return data
                idx += max(end, 1)
            except (json.JSONDecodeError, ValueError):
                idx += 1
        return None

    @staticmethod
    def _parse_json_output(
        text: Any,
        schema: Optional[Type[BaseModel]] = None,
    ) -> Optional[Dict[str, Any]]:
        """解析 LLM 输出为 JSON 并可选做 Pydantic 校验。

        兼容三种形态：
        1) 纯 JSON 字符串（结构化输出 / JSON Mode 返回值）
        2) Markdown 文本中内嵌的 JSON 对象（历史输出/旧 Prompt）
        3) 已解析的 dict 直接做校验
        """
        if text is None:
            return None

        if isinstance(text, dict):
            data: Any = text
        else:
            cleaned = str(text).strip()
            # 去除可能的 ```json ... ``` 外层包裹
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`").strip()
                if cleaned.lower().startswith("json"):
                    cleaned = cleaned[4:].strip()

            try:
                data = json.loads(cleaned)
            except json.JSONDecodeError:
                data = BaseAgent._find_first_json_object(cleaned)
                if data is None:
                    return None

        if not isinstance(data, dict):
            return None

        if schema is not None:
            try:
                return schema.model_validate(data).model_dump()
            except Exception:  # noqa: BLE001
                # 校验失败时仍返回原 dict，由调用方决定是否降级
                return data
        return data

    @staticmethod
    def _truncate_for_summary(
        value: Any,
        max_str: int = 400,
        max_list: int = 10,
        max_depth: int = 4,
        current_depth: int = 0,
    ) -> Any:
        """递归截断 dict/list/str，用于生成下游 Agent 可读的 summary。"""
        if current_depth > max_depth:
            return "..."
        if isinstance(value, str):
            if len(value) > max_str:
                return value[:max_str] + "... [truncated]"
            return value
        if isinstance(value, (list, tuple)):
            truncated = [BaseAgent._truncate_for_summary(v, max_str, max_list, max_depth, current_depth + 1) for v in value[:max_list]]
            if len(value) > max_list:
                truncated.append("...")
            return truncated
        if isinstance(value, dict):
            return {
                k: BaseAgent._truncate_for_summary(v, max_str, max_list, max_depth, current_depth + 1)
                for k, v in value.items()
            }
        return value

    def _summarize_result(self, result: Dict[str, Any]) -> str:
        """把 Agent 运行结果压缩成下游可传递的关键信息字符串。

        - 丢弃原始 LLM 输出（已解析到产物/文件和 report）
        - 递归截断长字符串/列表，避免 state 和 checkpoint 膨胀
        - 保证返回合法 JSON，便于下游直接解析
        """
        # 不向下游传递的元数据键
        excluded = {"output", "workspace", "model", "llm_kwargs", "agent", "role", "raw"}
        raw = {k: v for k, v in result.items() if k not in excluded and not k.startswith("_")}

        # 自适应截断：在保证合法 JSON 的前提下把 summary 压到 budget 内
        max_str, max_list = 400, 10
        while True:
            data = self._truncate_for_summary(raw, max_str=max_str, max_list=max_list)
            text = json.dumps(data, ensure_ascii=False, default=str)
            if len(text) <= self.summary_budget or max_str <= 50:
                break
            max_str = max(50, max_str // 2)
            max_list = max(3, max_list - 2)

        return text

    async def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        session = state.get("request_id", "default")
        workspace = self._workspace(state)
        workspace.mkdir(parents=True, exist_ok=True)
        state["workspace"] = str(workspace)

        memories = self.memory.recall(state.get("input", ""), session_id=session, layer="working", top_k=3)
        memory_text = "\n".join(str(m["value"]) for m in memories)
        prompt = self.build_prompt(state)
        full_prompt = f"相关记忆：\n{memory_text}\n\n{prompt}" if memory_text else prompt

        # 上下文压缩：超过阈值后保留头部和尾部
        if len(full_prompt) > Settings.context_compress_threshold():
            full_prompt = self.memory.compress_context(
                full_prompt, max_chars=Settings.context_window_limit()
            )

        # 敏感信息脱敏：进入 LLM 前与离开 LLM 后都进行 redaction
        full_prompt = SecretRedactor.redact(full_prompt)
        resolved_model, kwargs = self.router.resolve(self.name, full_prompt)

        with self.telemetry.span(
            f"agent.{self.name}.llm",
            {"agent": self.name, "model": resolved_model, "request_id": session},
        ):
            output = self.llm.chat(
                self.system_prompt,
                full_prompt,
                model=resolved_model,
                json_mode=self.json_output,
                **kwargs,
            )

        output = SecretRedactor.redact(output)

        # 近似 token 数与延迟统计
        self.telemetry.collector.counter(
            "llm_calls_total",
            "Total number of LLM calls",
            labelnames=["agent", "model"],
        ).inc(agent=self.name, model=resolved_model)
        self.telemetry.collector.histogram(
            "llm_prompt_tokens_approx",
            "Approximate prompt tokens",
            labelnames=["agent", "model"],
        ).observe(len(full_prompt) / 4, agent=self.name, model=resolved_model)
        self.telemetry.collector.histogram(
            "llm_output_tokens_approx",
            "Approximate output tokens",
            labelnames=["agent", "model"],
        ).observe(len(output) / 4, agent=self.name, model=resolved_model)

        result: Dict[str, Any] = {
            "agent": self.name,
            "role": self.role,
            "output": output,
            "workspace": str(workspace),
            "model": resolved_model,
            "llm_kwargs": kwargs,
        }
        extra = await self.postprocess(output, state)
        result.update(extra)

        # 生成关键信息摘要，替换原始 output，避免无效数据在 Agent 间传递
        result["output"] = self._summarize_result(result)
        # llm_kwargs 等内部元数据无需进入 LangGraph state
        result.pop("llm_kwargs", None)
        # 记忆层也存摘要，避免后续 recall 把原始大段输出塞进 prompt
        self.memory.remember("last_output", result["output"], session_id=session, layer="short", ttl=3600)

        return result

    def agent_card(self, url: str) -> AgentCard:
        return AgentCard(
            name=f"{self.name} Agent",
            url=url,
            skills=[AgentSkill(name=s) for s in self.skills],
            capabilities={"streaming": False, "autonomy": "L2", "modalities": ["text", "code"]},
        )


class ArchitectAgent(BaseAgent):
    json_output = True
    report_schema = DesignOutput
    summary_budget = 2000

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Architect",
            "系统架构师",
            _load_prompt("architect"),
            model=model,
            skills=["system-design", "api-contract", "tech-stack"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        prd = (state.get("product_manager") or {}).get("output", "")
        template = get_language(state)
        return (
            f"目标语言/技术栈：{template.display}\n"
            f"用户需求：{state.get('input', '')}\n"
            f"PRD：{prd[:1500] if prd else '无'}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            "请输出 JSON 格式架构设计：{modules, api_contract, tech_stack, mermaid, notes}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        design = self._parse_json_output(output, self.report_schema)
        if design:
            await self._write_file("design.json", json.dumps(design, ensure_ascii=False, indent=2), workspace)
        return {"design_file": "design.json" if design else None, "parsed": design}


class CoderAgent(BaseAgent):
    json_output = True
    report_schema = CoderReport
    summary_budget = 1500

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Coder",
            "代码实现引擎",
            _load_prompt("coder"),
            model=model,
            skills=["code-implementation", "refactor", "python"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        dba_output = (state.get("dba") or {}).get("output", "")
        template = get_language(state)
        json_example = (
            '{"files": [{"path": "main.%s", "code": "..."}], '
            '"report": {"status": "completed", "files_modified": [...], '
            '"test_result": "passed", "note": ""}}'
        ) % template.file_ext
        return (
            f"目标语言/技术栈：{template.display}\n"
            f"构建命令：{template.build_cmd or '无'}\n"
            f"测试命令：{template.test_cmd}\n"
            f"用户生成文件扩展名：.{template.file_ext}，测试文件扩展名：.{template.test_ext}\n"
            f"用户需求：{state.get('input', '')}\n"
            f"架构设计：{(state.get('architect') or {}).get('output', '')[:2000]}\n"
            f"数据库设计：{dba_output[:1500] if dba_output else '无'}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            f"请生成可运行代码。必须输出一个合法的 JSON 对象：\n{json_example}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        template = get_language(state)
        files: List[str] = []
        security_issues: List[Dict[str, Any]] = []

        # 优先解析结构化 JSON 输出（JSON Mode / response_format）
        structured = self._parse_json_output(output, AgentOutput)
        report: Dict[str, Any] = {}
        if structured and "files" in structured and "report" in structured:
            for f in structured.get("files", []):
                path = f.get("path", "")
                code = f.get("code", "")
                if not path:
                    continue
                if not path.endswith(f".{template.file_ext}"):
                    path += f".{template.file_ext}"
                issues = SafetyScanner.scan_code(code)
                security_issues.extend(issues)
                res = await self._write_file(path, code, workspace)
                if res.get("success"):
                    files.append(path)
            report = self._parse_json_output(structured.get("report"), self.report_schema) or structured.get("report", {})
        else:
            # 兼容历史/测试中的 Markdown 代码块 + JSON 报告
            blocks = self._extract_code_blocks(output)
            for idx, block in enumerate(blocks, start=1):
                path = block["path"]
                if not path:
                    path = f"module_{idx}.{template.file_ext}"
                if not path.endswith(f".{template.file_ext}"):
                    path += f".{template.file_ext}"
                issues = SafetyScanner.scan_code(block["code"])
                security_issues.extend(issues)
                res = await self._write_file(path, block["code"], workspace)
                if res.get("success"):
                    files.append(path)
            report = self._parse_json_output(output, self.report_schema) or {}

        # MOCK 降级：没有真实 LLM 时写一段占位代码，方便 CLI/测试继续跑
        if not files and self.llm.is_mock():
            stub = self._fallback_code(state.get("input", ""), template)
            res = await self._write_file(template.main_file(), stub, workspace)
            if res.get("success"):
                files.append(template.main_file())
            report = {
                "status": "mock_fallback",
                "files_modified": files,
                "test_result": "unknown",
                "note": f"MOCK 模式生成的占位代码 ({template.display})",
            }

        return {
            "files": files,
            "status": report.get("status", "completed" if files else "needs_help"),
            "test_result": report.get("test_result", "unknown"),
            "note": report.get("note", ""),
            "security_issues": security_issues,
        }

    @staticmethod
    def _fallback_code(requirement: str, template: Any) -> str:
        safe = re.sub(r"[^\w\u4e00-\u9fff]+", "_", requirement)[:30].strip("_") or "agent"
        if template.name == "java":
            class_name = safe.capitalize()
            return (
                f"package com.devagent;\n\n"
                f"public class {class_name} {{\n"
                f"    public static void main(String[] args) {{\n"
                f"        System.out.println(\"Hello from {safe}\");\n"
                f"    }}\n"
                f"}}\n"
            )
        if template.name == "go":
            return (
                f"package main\n\n"
                f"import \"fmt\"\n\n"
                f"func main() {{\n"
                f"    fmt.Println(\"Hello from {safe}\")\n"
                f"}}\n"
            )
        if template.name == "typescript":
            return (
                f"console.log(\"Hello from {safe}\");\n"
            )
        return f'"""Generated from requirement: {requirement}"""\n\ndef main():\n    print("Hello from {safe}")\n\nif __name__ == "__main__":\n    main()\n'


class TesterAgent(BaseAgent):
    json_output = True
    report_schema = TestReport
    summary_budget = 1200

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Tester",
            "测试工程师",
            _load_prompt("tester"),
            model=model,
            skills=["test-generation", "pytest", "coverage"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        workspace = state.get("workspace", "")
        template = get_language(state)
        code_files = (state.get("coder") or {}).get("files", [])
        code_snippets: List[str] = []
        for f in code_files[:3]:
            res = ToolSandbox.read_file(f, base_dir=workspace)  # 同步读取即可
            if res.get("success"):
                code_snippets.append(f"--- {f} ---\n{res['content'][:1500]}")
        json_example = (
            '{"files": [{"path": "test_%s", "code": "..."}], '
            '"report": {"passed": 0, "failed": 0, "coverage": 0.0, "report": ""}}'
        ) % template.file_ext
        return (
            f"目标语言：{template.display}\n"
            f"测试框架/命令：{template.test_cmd}\n"
            f"测试文件命名：*.{template.test_ext}\n"
            f"代码文件：{code_files}\n"
            f"{''.join(code_snippets)[:2500]}\n"
            f"工作目录：{workspace}\n"
            f"请生成对应语言的测试用例。必须输出一个合法的 JSON 对象：\n{json_example}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        template = get_language(state)
        files: List[str] = []

        # 优先解析结构化 JSON 输出
        structured = self._parse_json_output(output, AgentOutput)
        report: Dict[str, Any] = {}
        if structured and "files" in structured and "report" in structured:
            for f in structured.get("files", []):
                path = f.get("path", "")
                code = f.get("code", "")
                if not path:
                    continue
                if not path.endswith(f".{template.test_ext}"):
                    path += f".{template.test_ext}"
                res = await self._write_file(path, code, workspace)
                if res.get("success"):
                    files.append(path)
            report = self._parse_json_output(structured.get("report"), self.report_schema) or structured.get("report", {})
        else:
            # 兼容历史/测试中的 Markdown 代码块 + JSON 报告
            blocks = self._extract_code_blocks(output)
            for idx, block in enumerate(blocks, start=1):
                path = block["path"]
                if not path:
                    path = f"test_module_{idx}.{template.test_ext}"
                if not path.endswith(f".{template.test_ext}"):
                    path += f".{template.test_ext}"
                res = await self._write_file(path, block["code"], workspace)
                if res.get("success"):
                    files.append(path)
            report = self._parse_json_output(output, self.report_schema) or {}

        if files:
            test_res = await self._run_command(f"{template.test_cmd} -q", workspace, timeout=15)
        else:
            test_res = {"success": False, "stdout": "", "stderr": "no tests generated"}

        passed = report.get("passed")
        failed = report.get("failed")
        if passed is None or failed is None:
            passed, failed = self._parse_test_summary(test_res.get("stdout", ""))

        return {
            "files": files,
            "passed": passed,
            "failed": failed,
            "coverage": report.get("coverage", 0.0),
            "report": (test_res.get("stdout", "") + "\n" + test_res.get("stderr", "")).strip(),
            "test_command_success": test_res.get("success", False),
        }

    @staticmethod
    def _parse_test_summary(stdout: str):
        m = re.search(r"(\d+)\s+passed", stdout)
        passed = int(m.group(1)) if m else 0
        m = re.search(r"(\d+)\s+failed", stdout)
        failed = int(m.group(1)) if m else 0
        return passed, failed


class ReviewerAgent(BaseAgent):
    json_output = True
    report_schema = ReviewReport
    summary_budget = 1200

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Reviewer",
            "代码审查",
            _load_prompt("reviewer"),
            model=model,
            skills=["code-review", "security", "performance"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"原始需求：{state.get('input', '')}\n"
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            f"测试报告：{(state.get('tester') or {}).get('report', '')[:1200]}\n"
            f"文档文件：{(state.get('docs') or {}).get('files', [])}\n"
            "请独立思考，从需求出发审查。输出 JSON：{severity, passed, issues, suggestions}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        report = self._parse_json_output(output, self.report_schema)
        if not report:
            # 无法解析 JSON 时做最保守判断
            report = {
                "severity": "medium",
                "passed": False,
                "issues": ["Reviewer 输出无法解析为 JSON"],
                "suggestions": ["请检查 LLM 输出格式"],
            }
        review_file = "review_report.json"
        await self._write_file(review_file, json.dumps(report, ensure_ascii=False, indent=2), workspace)
        report["report_file"] = review_file
        return report


class DocsAgent(BaseAgent):
    summary_budget = 800

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Docs",
            "文档工程师",
            _load_prompt("docs"),
            model=model,
            skills=["documentation", "readme", "api-doc"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"架构：{str((state.get('architect') or {}).get('output', ''))[:800]}\n"
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            "请生成 README.md 与 API.md。用代码块标明文件路径，如 '# file: README.md'。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        blocks = self._extract_code_blocks(output)
        files: List[str] = []
        for block in blocks:
            path = block["path"] or "README.md"
            if not path.endswith(".md"):
                path += ".md"
            res = await self._write_file(f"docs/{path}", block["code"], workspace)
            if res.get("success"):
                files.append(f"docs/{path}")
        if not files:
            await self._write_file("docs/README.md", output, workspace)
            files.append("docs/README.md")
        return {"files": files}


class DevOpsAgent(BaseAgent):
    summary_budget = 1000

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "DevOps",
            "部署运维",
            _load_prompt("devops"),
            model=model,
            skills=["docker", "ci-cd", "deployment"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            "请生成 Dockerfile、docker-compose.yml 与 CI/CD 配置摘要，并说明部署前需人工确认。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        blocks = self._extract_code_blocks(output)
        files: List[str] = []
        for block in blocks:
            path = block["path"]
            if not path:
                continue
            res = await self._write_file(path, block["code"], workspace)
            if res.get("success"):
                files.append(path)
        if not files:
            await self._write_file("deploy_summary.md", output, workspace)
            files.append("deploy_summary.md")
        return {"files": files, "needs_approval": True}


class ProductManagerAgent(BaseAgent):
    report_schema = PRDOutput
    summary_budget = 1200

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "ProductManager",
            "产品经理",
            _load_prompt("product_manager"),
            model=model,
            skills=["requirement-analysis", "prd", "user-stories"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"用户需求：{state.get('input', '')}\n"
            "请把需求拆分为 PRD、用户故事和验收标准。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        report = self._parse_json_output(output, self.report_schema) or {}
        prd_file = "prd.md"
        # 如果结构化输出里有 prd_markdown，优先写入；否则把原始输出作为 PRD 正文
        prd_body = report.get("prd_markdown") or output
        await self._write_file(prd_file, prd_body, workspace)
        return {
            "prd_file": prd_file,
            "user_stories": report.get("user_stories", []),
            "acceptance_criteria": report.get("acceptance_criteria", []),
            "parsed": report,
        }


class SecurityAgent(BaseAgent):
    json_output = True
    report_schema = ReviewReport
    summary_budget = 1200

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Security",
            "安全审查",
            _load_prompt("security"),
            model=model,
            skills=["security-review", "vulnerability", "compliance"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"原始需求：{state.get('input', '')}\n"
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            f"测试文件：{(state.get('tester') or {}).get('files', [])}\n"
            f"架构设计：{(state.get('architect') or {}).get('output', '')[:1500]}\n"
            "请独立进行安全审查，输出 JSON {severity, passed, issues, suggestions}。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        report = self._parse_json_output(output, self.report_schema)
        if not report:
            report = {
                "severity": "medium",
                "passed": False,
                "issues": ["Security Agent 输出无法解析为 JSON"],
                "suggestions": ["请检查 LLM 输出格式"],
            }
        report_file = "security_report.json"
        await self._write_file(report_file, json.dumps(report, ensure_ascii=False, indent=2), workspace)
        report["report_file"] = report_file
        return report


class DBAAgent(BaseAgent):
    json_output = True
    report_schema = DBAReport
    summary_budget = 1500

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "DBA",
            "数据库架构",
            _load_prompt("dba"),
            model=model,
            skills=["database-design", "schema", "migration"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"原始需求：{state.get('input', '')}\n"
            f"架构设计：{(state.get('architect') or {}).get('output', '')[:2000]}\n"
            "请输出数据库 Schema 与迁移 SQL。必须输出一个合法的 JSON 对象：\n"
            "{\"files\": [{\"path\": \"schema.sql\", \"code\": \"...\"}, {\"path\": \"migrations/001_initial.sql\", \"code\": \"...\"}], "
            "\"report\": {\"tables\": [...], \"notes\": \"\"}}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        files: List[str] = []

        # 优先解析结构化 JSON 输出
        structured = self._parse_json_output(output, AgentOutput)
        report: Dict[str, Any] = {}
        if structured and "files" in structured and "report" in structured:
            for f in structured.get("files", []):
                path = f.get("path", "")
                code = f.get("code", "")
                if not path:
                    continue
                if not path.endswith(".sql"):
                    path += ".sql"
                res = await self._write_file(path, code, workspace)
                if res.get("success"):
                    files.append(path)
            report = self._parse_json_output(structured.get("report"), self.report_schema) or structured.get("report", {})
        else:
            # 兼容历史/测试中的 Markdown 代码块 + JSON 报告
            blocks = self._extract_code_blocks(output)
            for block in blocks:
                path = block["path"]
                if not path:
                    continue
                if not path.endswith(".sql"):
                    path += ".sql"
                res = await self._write_file(path, block["code"], workspace)
                if res.get("success"):
                    files.append(path)
            report = self._parse_json_output(output, self.report_schema) or {}

        if not files:
            await self._write_file("schema.sql", output, workspace)
            files.append("schema.sql")

        return {
            "files": files,
            "tables": report.get("tables", []),
            "notes": report.get("notes", ""),
        }


class MemoryAgentFacade:
    """对外的 Memory Agent 接口，供 Orchestrator 调用。"""

    def __init__(self, base_dir: str = "memory_store"):
        self._impl = MemoryAgent(base_dir=base_dir)

    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        session = state.get("request_id", "default")
        query = state.get("input", "")
        memories = self._impl.recall(query, session_id=session, layer="working", top_k=5)
        summary = self._impl.summarize(state.get("history", []))
        return {"agent": "Memory", "role": "记忆", "memories": memories, "summary": summary}


def _load_prompt(agent_name: str) -> str:
    """从 prompts.yaml 加载 System Prompt；失败时返回内置提示。"""
    prompt_file = Path(__file__).with_name("prompts.yaml")
    try:
        with open(prompt_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get(agent_name, _FALLBACK_PROMPTS.get(agent_name, f"你是 {agent_name} Agent。"))
    except Exception:  # noqa: BLE001
        return _FALLBACK_PROMPTS.get(agent_name, f"你是 {agent_name} Agent。")


_FALLBACK_PROMPTS: Dict[str, str] = {
    "architect": "你是 Architect Agent，负责架构设计。禁止写实现代码。",
    "coder": "你是 Coder Agent，负责生成可运行代码。",
    "tester": "你是 Tester Agent，负责生成并执行测试。",
    "reviewer": "你是 Reviewer Agent，必须独立思考，不信任上游。",
    "docs": "你是 Docs Agent，负责同步文档。",
    "devops": "你是 DevOps Agent，负责 CI/CD 与部署。",
    "product_manager": "你是 Product Manager Agent，负责需求分析与 PRD。",
    "security": "你是 Security Agent，负责独立安全审查。",
    "dba": "你是 DBA Agent，负责数据库 Schema 与迁移。",
}
``` 代码块，支持前接 '# file: path' 等头部。"""
        blocks: List[Dict[str, str]] = []
        pattern = r"(?:^|\n)(?:[^\n`]*?(?:file|path|filename)[:\s]+([^\n]+))?\n?```(?:\w+)?\n(.*?)```"
        for m in re.finditer(pattern, text, re.DOTALL | re.I):
            path = (m.group(1) or "").strip().strip("`").strip()
            code = m.group(2)
            blocks.append({"path": path, "code": code})
        return blocks

    @staticmethod
    def _find_first_json_object(text: str) -> Optional[Any]:
        """从文本中定位第一个非空的 JSON 对象/数组。

        优先匹配 ```json ... ``` 代码块，再扫描内嵌的 JSON。
        """
        # 1) 显式 JSON 代码块
        for m in re.finditer(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL | re.I):
            block = m.group(1).strip()
            if not block:
                continue
            try:
                data = json.loads(block)
                if isinstance(data, (dict, list)) and data:
                    return data
            except json.JSONDecodeError:
                continue

        # 2) 用 JSONDecoder 扫描 { } / [ ]，跳过空的 {} / []
        decoder = json.JSONDecoder()
        idx = 0
        n = len(text)
        while idx < n:
            # 定位到下一个 { 或 [
            while idx < n and text[idx] not in "{[":
                idx += 1
            if idx >= n:
                return None
            try:
                data, end = decoder.raw_decode(text, idx)
                if isinstance(data, dict) and data:
                    return data
                if isinstance(data, list) and data:
                    return data
                idx += max(end, 1)
            except (json.JSONDecodeError, ValueError):
                idx += 1
        return None

    @staticmethod
    def _parse_json_output(
        text: Any,
        schema: Optional[Type[BaseModel]] = None,
    ) -> Optional[Dict[str, Any]]:
        """解析 LLM 输出为 JSON 并可选做 Pydantic 校验。

        兼容三种形态：
        1) 纯 JSON 字符串（结构化输出 / JSON Mode 返回值）
        2) Markdown 文本中内嵌的 JSON 对象（历史输出/旧 Prompt）
        3) 已解析的 dict 直接做校验
        """
        if text is None:
            return None

        if isinstance(text, dict):
            data: Any = text
        else:
            cleaned = str(text).strip()
            # 去除可能的 ```json ... ``` 外层包裹
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`").strip()
                if cleaned.lower().startswith("json"):
                    cleaned = cleaned[4:].strip()

            try:
                data = json.loads(cleaned)
            except json.JSONDecodeError:
                data = BaseAgent._find_first_json_object(cleaned)
                if data is None:
                    return None

        if not isinstance(data, dict):
            return None

        if schema is not None:
            try:
                return schema.model_validate(data).model_dump()
            except Exception:  # noqa: BLE001
                # 校验失败时仍返回原 dict，由调用方决定是否降级
                return data
        return data

    @staticmethod
    def _truncate_for_summary(
        value: Any,
        max_str: int = 400,
        max_list: int = 10,
        max_depth: int = 4,
        current_depth: int = 0,
    ) -> Any:
        """递归截断 dict/list/str，用于生成下游 Agent 可读的 summary。"""
        if current_depth > max_depth:
            return "..."
        if isinstance(value, str):
            if len(value) > max_str:
                return value[:max_str] + "... [truncated]"
            return value
        if isinstance(value, (list, tuple)):
            truncated = [BaseAgent._truncate_for_summary(v, max_str, max_list, max_depth, current_depth + 1) for v in value[:max_list]]
            if len(value) > max_list:
                truncated.append("...")
            return truncated
        if isinstance(value, dict):
            return {
                k: BaseAgent._truncate_for_summary(v, max_str, max_list, max_depth, current_depth + 1)
                for k, v in value.items()
            }
        return value

    def _summarize_result(self, result: Dict[str, Any]) -> str:
        """把 Agent 运行结果压缩成下游可传递的关键信息字符串。

        - 丢弃原始 LLM 输出（已解析到产物/文件和 report）
        - 递归截断长字符串/列表，避免 state 和 checkpoint 膨胀
        - 保证返回合法 JSON，便于下游直接解析
        """
        # 不向下游传递的元数据键
        excluded = {"output", "workspace", "model", "llm_kwargs", "agent", "role", "raw"}
        raw = {k: v for k, v in result.items() if k not in excluded and not k.startswith("_")}

        # 自适应截断：在保证合法 JSON 的前提下把 summary 压到 budget 内
        max_str, max_list = 400, 10
        while True:
            data = self._truncate_for_summary(raw, max_str=max_str, max_list=max_list)
            text = json.dumps(data, ensure_ascii=False, default=str)
            if len(text) <= self.summary_budget or max_str <= 50:
                break
            max_str = max(50, max_str // 2)
            max_list = max(3, max_list - 2)

        return text

    async def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        session = state.get("request_id", "default")
        workspace = self._workspace(state)
        workspace.mkdir(parents=True, exist_ok=True)
        state["workspace"] = str(workspace)

        memories = self.memory.recall(state.get("input", ""), session_id=session, layer="working", top_k=3)
        memory_text = "\n".join(str(m["value"]) for m in memories)
        prompt = self.build_prompt(state)
        full_prompt = f"相关记忆：\n{memory_text}\n\n{prompt}" if memory_text else prompt

        # 上下文压缩：超过阈值后保留头部和尾部
        if len(full_prompt) > Settings.context_compress_threshold():
            full_prompt = self.memory.compress_context(
                full_prompt, max_chars=Settings.context_window_limit()
            )

        # 敏感信息脱敏：进入 LLM 前与离开 LLM 后都进行 redaction
        full_prompt = SecretRedactor.redact(full_prompt)
        resolved_model, kwargs = self.router.resolve(self.name, full_prompt)

        with self.telemetry.span(
            f"agent.{self.name}.llm",
            {"agent": self.name, "model": resolved_model, "request_id": session},
        ):
            output = self.llm.chat(
                self.system_prompt,
                full_prompt,
                model=resolved_model,
                json_mode=self.json_output,
                **kwargs,
            )

        output = SecretRedactor.redact(output)

        # 近似 token 数与延迟统计
        self.telemetry.collector.counter(
            "llm_calls_total",
            "Total number of LLM calls",
            labelnames=["agent", "model"],
        ).inc(agent=self.name, model=resolved_model)
        self.telemetry.collector.histogram(
            "llm_prompt_tokens_approx",
            "Approximate prompt tokens",
            labelnames=["agent", "model"],
        ).observe(len(full_prompt) / 4, agent=self.name, model=resolved_model)
        self.telemetry.collector.histogram(
            "llm_output_tokens_approx",
            "Approximate output tokens",
            labelnames=["agent", "model"],
        ).observe(len(output) / 4, agent=self.name, model=resolved_model)

        result: Dict[str, Any] = {
            "agent": self.name,
            "role": self.role,
            "output": output,
            "workspace": str(workspace),
            "model": resolved_model,
            "llm_kwargs": kwargs,
        }
        extra = await self.postprocess(output, state)
        result.update(extra)

        # 生成关键信息摘要，替换原始 output，避免无效数据在 Agent 间传递
        result["output"] = self._summarize_result(result)
        # llm_kwargs 等内部元数据无需进入 LangGraph state
        result.pop("llm_kwargs", None)
        # 记忆层也存摘要，避免后续 recall 把原始大段输出塞进 prompt
        self.memory.remember("last_output", result["output"], session_id=session, layer="short", ttl=3600)

        return result

    def agent_card(self, url: str) -> AgentCard:
        return AgentCard(
            name=f"{self.name} Agent",
            url=url,
            skills=[AgentSkill(name=s) for s in self.skills],
            capabilities={"streaming": False, "autonomy": "L2", "modalities": ["text", "code"]},
        )


class ArchitectAgent(BaseAgent):
    json_output = True
    report_schema = DesignOutput
    summary_budget = 2000

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Architect",
            "系统架构师",
            _load_prompt("architect"),
            model=model,
            skills=["system-design", "api-contract", "tech-stack"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        prd = (state.get("product_manager") or {}).get("output", "")
        template = get_language(state)
        return (
            f"目标语言/技术栈：{template.display}\n"
            f"用户需求：{state.get('input', '')}\n"
            f"PRD：{prd[:1500] if prd else '无'}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            "请输出 JSON 格式架构设计：{modules, api_contract, tech_stack, mermaid, notes}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        design = self._parse_json_output(output, self.report_schema)
        if design:
            await self._write_file("design.json", json.dumps(design, ensure_ascii=False, indent=2), workspace)
        return {"design_file": "design.json" if design else None, "parsed": design}


class CoderAgent(BaseAgent):
    json_output = True
    report_schema = CoderReport
    summary_budget = 1500

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Coder",
            "代码实现引擎",
            _load_prompt("coder"),
            model=model,
            skills=["code-implementation", "refactor", "python"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        dba_output = (state.get("dba") or {}).get("output", "")
        template = get_language(state)
        json_example = (
            '{"files": [{"path": "main.%s", "code": "..."}], '
            '"report": {"status": "completed", "files_modified": [...], '
            '"test_result": "passed", "note": ""}}'
        ) % template.file_ext
        return (
            f"目标语言/技术栈：{template.display}\n"
            f"构建命令：{template.build_cmd or '无'}\n"
            f"测试命令：{template.test_cmd}\n"
            f"用户生成文件扩展名：.{template.file_ext}，测试文件扩展名：.{template.test_ext}\n"
            f"用户需求：{state.get('input', '')}\n"
            f"架构设计：{(state.get('architect') or {}).get('output', '')[:2000]}\n"
            f"数据库设计：{dba_output[:1500] if dba_output else '无'}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            f"请生成可运行代码。必须输出一个合法的 JSON 对象：\n{json_example}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        template = get_language(state)
        files: List[str] = []
        security_issues: List[Dict[str, Any]] = []

        # 优先解析结构化 JSON 输出（JSON Mode / response_format）
        structured = self._parse_json_output(output, AgentOutput)
        report: Dict[str, Any] = {}
        if structured and "files" in structured and "report" in structured:
            for f in structured.get("files", []):
                path = f.get("path", "")
                code = f.get("code", "")
                if not path:
                    continue
                if not path.endswith(f".{template.file_ext}"):
                    path += f".{template.file_ext}"
                issues = SafetyScanner.scan_code(code)
                security_issues.extend(issues)
                res = await self._write_file(path, code, workspace)
                if res.get("success"):
                    files.append(path)
            report = self._parse_json_output(structured.get("report"), self.report_schema) or structured.get("report", {})
        else:
            # 兼容历史/测试中的 Markdown 代码块 + JSON 报告
            blocks = self._extract_code_blocks(output)
            for idx, block in enumerate(blocks, start=1):
                path = block["path"]
                if not path:
                    path = f"module_{idx}.{template.file_ext}"
                if not path.endswith(f".{template.file_ext}"):
                    path += f".{template.file_ext}"
                issues = SafetyScanner.scan_code(block["code"])
                security_issues.extend(issues)
                res = await self._write_file(path, block["code"], workspace)
                if res.get("success"):
                    files.append(path)
            report = self._parse_json_output(output, self.report_schema) or {}

        # MOCK 降级：没有真实 LLM 时写一段占位代码，方便 CLI/测试继续跑
        if not files and self.llm.is_mock():
            stub = self._fallback_code(state.get("input", ""), template)
            res = await self._write_file(template.main_file(), stub, workspace)
            if res.get("success"):
                files.append(template.main_file())
            report = {
                "status": "mock_fallback",
                "files_modified": files,
                "test_result": "unknown",
                "note": f"MOCK 模式生成的占位代码 ({template.display})",
            }

        return {
            "files": files,
            "status": report.get("status", "completed" if files else "needs_help"),
            "test_result": report.get("test_result", "unknown"),
            "note": report.get("note", ""),
            "security_issues": security_issues,
        }

    @staticmethod
    def _fallback_code(requirement: str, template: Any) -> str:
        safe = re.sub(r"[^\w\u4e00-\u9fff]+", "_", requirement)[:30].strip("_") or "agent"
        if template.name == "java":
            class_name = safe.capitalize()
            return (
                f"package com.devagent;\n\n"
                f"public class {class_name} {{\n"
                f"    public static void main(String[] args) {{\n"
                f"        System.out.println(\"Hello from {safe}\");\n"
                f"    }}\n"
                f"}}\n"
            )
        if template.name == "go":
            return (
                f"package main\n\n"
                f"import \"fmt\"\n\n"
                f"func main() {{\n"
                f"    fmt.Println(\"Hello from {safe}\")\n"
                f"}}\n"
            )
        if template.name == "typescript":
            return (
                f"console.log(\"Hello from {safe}\");\n"
            )
        return f'"""Generated from requirement: {requirement}"""\n\ndef main():\n    print("Hello from {safe}")\n\nif __name__ == "__main__":\n    main()\n'


class TesterAgent(BaseAgent):
    json_output = True
    report_schema = TestReport
    summary_budget = 1200

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Tester",
            "测试工程师",
            _load_prompt("tester"),
            model=model,
            skills=["test-generation", "pytest", "coverage"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        workspace = state.get("workspace", "")
        template = get_language(state)
        code_files = (state.get("coder") or {}).get("files", [])
        code_snippets: List[str] = []
        for f in code_files[:3]:
            res = ToolSandbox.read_file(f, base_dir=workspace)  # 同步读取即可
            if res.get("success"):
                code_snippets.append(f"--- {f} ---\n{res['content'][:1500]}")
        json_example = (
            '{"files": [{"path": "test_%s", "code": "..."}], '
            '"report": {"passed": 0, "failed": 0, "coverage": 0.0, "report": ""}}'
        ) % template.file_ext
        return (
            f"目标语言：{template.display}\n"
            f"测试框架/命令：{template.test_cmd}\n"
            f"测试文件命名：*.{template.test_ext}\n"
            f"代码文件：{code_files}\n"
            f"{''.join(code_snippets)[:2500]}\n"
            f"工作目录：{workspace}\n"
            f"请生成对应语言的测试用例。必须输出一个合法的 JSON 对象：\n{json_example}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        template = get_language(state)
        files: List[str] = []

        # 优先解析结构化 JSON 输出
        structured = self._parse_json_output(output, AgentOutput)
        report: Dict[str, Any] = {}
        if structured and "files" in structured and "report" in structured:
            for f in structured.get("files", []):
                path = f.get("path", "")
                code = f.get("code", "")
                if not path:
                    continue
                if not path.endswith(f".{template.test_ext}"):
                    path += f".{template.test_ext}"
                res = await self._write_file(path, code, workspace)
                if res.get("success"):
                    files.append(path)
            report = self._parse_json_output(structured.get("report"), self.report_schema) or structured.get("report", {})
        else:
            # 兼容历史/测试中的 Markdown 代码块 + JSON 报告
            blocks = self._extract_code_blocks(output)
            for idx, block in enumerate(blocks, start=1):
                path = block["path"]
                if not path:
                    path = f"test_module_{idx}.{template.test_ext}"
                if not path.endswith(f".{template.test_ext}"):
                    path += f".{template.test_ext}"
                res = await self._write_file(path, block["code"], workspace)
                if res.get("success"):
                    files.append(path)
            report = self._parse_json_output(output, self.report_schema) or {}

        if files:
            test_res = await self._run_command(f"{template.test_cmd} -q", workspace, timeout=15)
        else:
            test_res = {"success": False, "stdout": "", "stderr": "no tests generated"}

        passed = report.get("passed")
        failed = report.get("failed")
        if passed is None or failed is None:
            passed, failed = self._parse_test_summary(test_res.get("stdout", ""))

        return {
            "files": files,
            "passed": passed,
            "failed": failed,
            "coverage": report.get("coverage", 0.0),
            "report": (test_res.get("stdout", "") + "\n" + test_res.get("stderr", "")).strip(),
            "test_command_success": test_res.get("success", False),
        }

    @staticmethod
    def _parse_test_summary(stdout: str):
        m = re.search(r"(\d+)\s+passed", stdout)
        passed = int(m.group(1)) if m else 0
        m = re.search(r"(\d+)\s+failed", stdout)
        failed = int(m.group(1)) if m else 0
        return passed, failed


class ReviewerAgent(BaseAgent):
    json_output = True
    report_schema = ReviewReport
    summary_budget = 1200

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Reviewer",
            "代码审查",
            _load_prompt("reviewer"),
            model=model,
            skills=["code-review", "security", "performance"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"原始需求：{state.get('input', '')}\n"
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            f"测试报告：{(state.get('tester') or {}).get('report', '')[:1200]}\n"
            f"文档文件：{(state.get('docs') or {}).get('files', [])}\n"
            "请独立思考，从需求出发审查。输出 JSON：{severity, passed, issues, suggestions}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        report = self._parse_json_output(output, self.report_schema)
        if not report:
            # 无法解析 JSON 时做最保守判断
            report = {
                "severity": "medium",
                "passed": False,
                "issues": ["Reviewer 输出无法解析为 JSON"],
                "suggestions": ["请检查 LLM 输出格式"],
            }
        review_file = "review_report.json"
        await self._write_file(review_file, json.dumps(report, ensure_ascii=False, indent=2), workspace)
        report["report_file"] = review_file
        return report


class DocsAgent(BaseAgent):
    summary_budget = 800

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Docs",
            "文档工程师",
            _load_prompt("docs"),
            model=model,
            skills=["documentation", "readme", "api-doc"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"架构：{str((state.get('architect') or {}).get('output', ''))[:800]}\n"
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            "请生成 README.md 与 API.md。用代码块标明文件路径，如 '# file: README.md'。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        blocks = self._extract_code_blocks(output)
        files: List[str] = []
        for block in blocks:
            path = block["path"] or "README.md"
            if not path.endswith(".md"):
                path += ".md"
            res = await self._write_file(f"docs/{path}", block["code"], workspace)
            if res.get("success"):
                files.append(f"docs/{path}")
        if not files:
            await self._write_file("docs/README.md", output, workspace)
            files.append("docs/README.md")
        return {"files": files}


class DevOpsAgent(BaseAgent):
    summary_budget = 1000

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "DevOps",
            "部署运维",
            _load_prompt("devops"),
            model=model,
            skills=["docker", "ci-cd", "deployment"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            "请生成 Dockerfile、docker-compose.yml 与 CI/CD 配置摘要，并说明部署前需人工确认。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        blocks = self._extract_code_blocks(output)
        files: List[str] = []
        for block in blocks:
            path = block["path"]
            if not path:
                continue
            res = await self._write_file(path, block["code"], workspace)
            if res.get("success"):
                files.append(path)
        if not files:
            await self._write_file("deploy_summary.md", output, workspace)
            files.append("deploy_summary.md")
        return {"files": files, "needs_approval": True}


class ProductManagerAgent(BaseAgent):
    report_schema = PRDOutput
    summary_budget = 1200

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "ProductManager",
            "产品经理",
            _load_prompt("product_manager"),
            model=model,
            skills=["requirement-analysis", "prd", "user-stories"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"用户需求：{state.get('input', '')}\n"
            "请把需求拆分为 PRD、用户故事和验收标准。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        report = self._parse_json_output(output, self.report_schema) or {}
        prd_file = "prd.md"
        # 如果结构化输出里有 prd_markdown，优先写入；否则把原始输出作为 PRD 正文
        prd_body = report.get("prd_markdown") or output
        await self._write_file(prd_file, prd_body, workspace)
        return {
            "prd_file": prd_file,
            "user_stories": report.get("user_stories", []),
            "acceptance_criteria": report.get("acceptance_criteria", []),
            "parsed": report,
        }


class SecurityAgent(BaseAgent):
    json_output = True
    report_schema = ReviewReport
    summary_budget = 1200

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Security",
            "安全审查",
            _load_prompt("security"),
            model=model,
            skills=["security-review", "vulnerability", "compliance"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"原始需求：{state.get('input', '')}\n"
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            f"测试文件：{(state.get('tester') or {}).get('files', [])}\n"
            f"架构设计：{(state.get('architect') or {}).get('output', '')[:1500]}\n"
            "请独立进行安全审查，输出 JSON {severity, passed, issues, suggestions}。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        report = self._parse_json_output(output, self.report_schema)
        if not report:
            report = {
                "severity": "medium",
                "passed": False,
                "issues": ["Security Agent 输出无法解析为 JSON"],
                "suggestions": ["请检查 LLM 输出格式"],
            }
        report_file = "security_report.json"
        await self._write_file(report_file, json.dumps(report, ensure_ascii=False, indent=2), workspace)
        report["report_file"] = report_file
        return report


class DBAAgent(BaseAgent):
    json_output = True
    report_schema = DBAReport
    summary_budget = 1500

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "DBA",
            "数据库架构",
            _load_prompt("dba"),
            model=model,
            skills=["database-design", "schema", "migration"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"原始需求：{state.get('input', '')}\n"
            f"架构设计：{(state.get('architect') or {}).get('output', '')[:2000]}\n"
            "请输出数据库 Schema 与迁移 SQL。必须输出一个合法的 JSON 对象：\n"
            "{\"files\": [{\"path\": \"schema.sql\", \"code\": \"...\"}, {\"path\": \"migrations/001_initial.sql\", \"code\": \"...\"}], "
            "\"report\": {\"tables\": [...], \"notes\": \"\"}}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        files: List[str] = []

        # 优先解析结构化 JSON 输出
        structured = self._parse_json_output(output, AgentOutput)
        report: Dict[str, Any] = {}
        if structured and "files" in structured and "report" in structured:
            for f in structured.get("files", []):
                path = f.get("path", "")
                code = f.get("code", "")
                if not path:
                    continue
                if not path.endswith(".sql"):
                    path += ".sql"
                res = await self._write_file(path, code, workspace)
                if res.get("success"):
                    files.append(path)
            report = self._parse_json_output(structured.get("report"), self.report_schema) or structured.get("report", {})
        else:
            # 兼容历史/测试中的 Markdown 代码块 + JSON 报告
            blocks = self._extract_code_blocks(output)
            for block in blocks:
                path = block["path"]
                if not path:
                    continue
                if not path.endswith(".sql"):
                    path += ".sql"
                res = await self._write_file(path, block["code"], workspace)
                if res.get("success"):
                    files.append(path)
            report = self._parse_json_output(output, self.report_schema) or {}

        if not files:
            await self._write_file("schema.sql", output, workspace)
            files.append("schema.sql")

        return {
            "files": files,
            "tables": report.get("tables", []),
            "notes": report.get("notes", ""),
        }


class MemoryAgentFacade:
    """对外的 Memory Agent 接口，供 Orchestrator 调用。"""

    def __init__(self, base_dir: str = "memory_store"):
        self._impl = MemoryAgent(base_dir=base_dir)

    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        session = state.get("request_id", "default")
        query = state.get("input", "")
        memories = self._impl.recall(query, session_id=session, layer="working", top_k=5)
        summary = self._impl.summarize(state.get("history", []))
        return {"agent": "Memory", "role": "记忆", "memories": memories, "summary": summary}


def _load_prompt(agent_name: str) -> str:
    """从 prompts.yaml 加载 System Prompt；失败时返回内置提示。"""
    prompt_file = Path(__file__).with_name("prompts.yaml")
    try:
        with open(prompt_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get(agent_name, _FALLBACK_PROMPTS.get(agent_name, f"你是 {agent_name} Agent。"))
    except Exception:  # noqa: BLE001
        return _FALLBACK_PROMPTS.get(agent_name, f"你是 {agent_name} Agent。")


_FALLBACK_PROMPTS: Dict[str, str] = {
    "architect": "你是 Architect Agent，负责架构设计。禁止写实现代码。",
    "coder": "你是 Coder Agent，负责生成可运行代码。",
    "tester": "你是 Tester Agent，负责生成并执行测试。",
    "reviewer": "你是 Reviewer Agent，必须独立思考，不信任上游。",
    "docs": "你是 Docs Agent，负责同步文档。",
    "devops": "你是 DevOps Agent，负责 CI/CD 与部署。",
    "product_manager": "你是 Product Manager Agent，负责需求分析与 PRD。",
    "security": "你是 Security Agent，负责独立安全审查。",
    "dba": "你是 DBA Agent，负责数据库 Schema 与迁移。",
}
``` 代码块，支持前接 '# file: path' 等头部。"""
        blocks: List[Dict[str, str]] = []
        pattern = r"(?:^|\n)(?:[^\n`]*?(?:file|path|filename)[:\s]+([^\n]+))?\n?```(?:\w+)?\n(.*?)```"
        for m in re.finditer(pattern, text, re.DOTALL | re.I):
            path = (m.group(1) or "").strip().strip("`").strip()
            code = m.group(2)
            blocks.append({"path": path, "code": code})
        return blocks

    async def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        session = state.get("request_id", "default")
        workspace = self._workspace(state)
        workspace.mkdir(parents=True, exist_ok=True)
        state["workspace"] = str(workspace)

        memories = self.memory.recall(state.get("input", ""), session_id=session, layer="working", top_k=3)
        memory_text = "\n".join(str(m["value"]) for m in memories)
        prompt = self.build_prompt(state)
        full_prompt = f"相关记忆：\n{memory_text}\n\n{prompt}" if memory_text else prompt

        # 上下文压缩：超过阈值后保留头部和尾部
        if len(full_prompt) > Settings.context_compress_threshold():
            full_prompt = self.memory.compress_context(
                full_prompt, max_chars=Settings.context_window_limit()
            )

        # 敏感信息脱敏：进入 LLM 前与离开 LLM 后都进行 redaction
        full_prompt = SecretRedactor.redact(full_prompt)
        resolved_model, kwargs = self.router.resolve(self.name, full_prompt)

        with self.telemetry.span(
            f"agent.{self.name}.llm",
            {"agent": self.name, "model": resolved_model, "request_id": session},
        ):
            output = self.llm.chat(self.system_prompt, full_prompt, model=resolved_model, **kwargs)

        output = SecretRedactor.redact(output)
        self.memory.remember("last_output", output, session_id=session, layer="short", ttl=3600)

        # 近似 token 数与延迟统计
        self.telemetry.collector.counter(
            "llm_calls_total",
            "Total number of LLM calls",
            labelnames=["agent", "model"],
        ).inc(agent=self.name, model=resolved_model)
        self.telemetry.collector.histogram(
            "llm_prompt_tokens_approx",
            "Approximate prompt tokens",
            labelnames=["agent", "model"],
        ).observe(len(full_prompt) / 4, agent=self.name, model=resolved_model)
        self.telemetry.collector.histogram(
            "llm_output_tokens_approx",
            "Approximate output tokens",
            labelnames=["agent", "model"],
        ).observe(len(output) / 4, agent=self.name, model=resolved_model)

        result: Dict[str, Any] = {
            "agent": self.name,
            "role": self.role,
            "output": output,
            "workspace": str(workspace),
            "model": resolved_model,
            "llm_kwargs": kwargs,
        }
        extra = await self.postprocess(output, state)
        result.update(extra)
        return result

    def agent_card(self, url: str) -> AgentCard:
        return AgentCard(
            name=f"{self.name} Agent",
            url=url,
            skills=[AgentSkill(name=s) for s in self.skills],
            capabilities={"streaming": False, "autonomy": "L2", "modalities": ["text", "code"]},
        )


class ArchitectAgent(BaseAgent):
    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Architect",
            "系统架构师",
            _load_prompt("architect"),
            model=model,
            skills=["system-design", "api-contract", "tech-stack"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        prd = (state.get("product_manager") or {}).get("output", "")
        template = get_language(state)
        return (
            f"目标语言/技术栈：{template.display}\n"
            f"用户需求：{state.get('input', '')}\n"
            f"PRD：{prd[:1500] if prd else '无'}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            "请输出 JSON 格式架构设计：{modules, api_contract, tech_stack, mermaid, notes}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        design = self._extract_json(output)
        if design:
            await self._write_file("design.json", json.dumps(design, ensure_ascii=False, indent=2), workspace)
        return {"design_file": "design.json" if design else None, "parsed": design}


class CoderAgent(BaseAgent):
    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Coder",
            "代码实现引擎",
            _load_prompt("coder"),
            model=model,
            skills=["code-implementation", "refactor", "python"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        dba_output = (state.get("dba") or {}).get("output", "")
        template = get_language(state)
        return (
            f"目标语言/技术栈：{template.display}\n"
            f"构建命令：{template.build_cmd or '无'}\n"
            f"测试命令：{template.test_cmd}\n"
            f"用户生成文件扩展名：.{template.file_ext}，测试文件扩展名：.{template.test_ext}\n"
            f"用户需求：{state.get('input', '')}\n"
            f"架构设计：{(state.get('architect') or {}).get('output', '')[:2000]}\n"
            f"数据库设计：{dba_output[:1500] if dba_output else '无'}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            "请生成可运行代码。每个代码块前用注释标明文件路径，例如 '# file: main."
            f"{template.file_ext}'。最后输出 JSON 状态报告："
            "{status, files_modified, test_result, note}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        template = get_language(state)
        blocks = self._extract_code_blocks(output)
        files: List[str] = []
        security_issues: List[Dict[str, Any]] = []
        for idx, block in enumerate(blocks, start=1):
            path = block["path"]
            if not path:
                path = f"module_{idx}.{template.file_ext}"
            if not path.endswith(f".{template.file_ext}"):
                path += f".{template.file_ext}"
            issues = SafetyScanner.scan_code(block["code"])
            security_issues.extend(issues)
            res = await self._write_file(path, block["code"], workspace)
            if res.get("success"):
                files.append(path)

        report = self._extract_json(output) or {}

        # MOCK 降级：没有真实 LLM 时写一段占位代码，方便 CLI/测试继续跑
        if not files and self.llm.is_mock():
            stub = self._fallback_code(state.get("input", ""), template)
            res = await self._write_file(template.main_file(), stub, workspace)
            if res.get("success"):
                files.append(template.main_file())
            report = {
                "status": "mock_fallback",
                "files_modified": files,
                "test_result": "unknown",
                "note": f"MOCK 模式生成的占位代码 ({template.display})",
            }

        return {
            "files": files,
            "status": report.get("status", "completed" if files else "needs_help"),
            "test_result": report.get("test_result", "unknown"),
            "note": report.get("note", ""),
            "security_issues": security_issues,
        }

    @staticmethod
    def _fallback_code(requirement: str, template: Any) -> str:
        safe = re.sub(r"[^\w\u4e00-\u9fff]+", "_", requirement)[:30].strip("_") or "agent"
        if template.name == "java":
            class_name = safe.capitalize()
            return (
                f"package com.devagent;\n\n"
                f"public class {class_name} {{\n"
                f"    public static void main(String[] args) {{\n"
                f"        System.out.println(\"Hello from {safe}\");\n"
                f"    }}\n"
                f"}}\n"
            )
        if template.name == "go":
            return (
                f"package main\n\n"
                f"import \"fmt\"\n\n"
                f"func main() {{\n"
                f"    fmt.Println(\"Hello from {safe}\")\n"
                f"}}\n"
            )
        if template.name == "typescript":
            return (
                f"console.log(\"Hello from {safe}\");\n"
            )
        return f'"""Generated from requirement: {requirement}"""\n\ndef main():\n    print("Hello from {safe}")\n\nif __name__ == "__main__":\n    main()\n'


class TesterAgent(BaseAgent):
    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Tester",
            "测试工程师",
            _load_prompt("tester"),
            model=model,
            skills=["test-generation", "pytest", "coverage"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        workspace = state.get("workspace", "")
        template = get_language(state)
        code_files = (state.get("coder") or {}).get("files", [])
        code_snippets: List[str] = []
        for f in code_files[:3]:
            res = ToolSandbox.read_file(f, base_dir=workspace)  # 同步读取即可
            if res.get("success"):
                code_snippets.append(f"--- {f} ---\n{res['content'][:1500]}")
        return (
            f"目标语言：{template.display}\n"
            f"测试框架/命令：{template.test_cmd}\n"
            f"测试文件命名：*.{template.test_ext}\n"
            f"代码文件：{code_files}\n"
            f"{''.join(code_snippets)[:2500]}\n"
            f"工作目录：{workspace}\n"
            "请生成对应语言的测试用例。每个测试代码块前标明文件路径，如 '# file: test_"
            f"{template.file_ext}'。最后输出 JSON 测试报告："
            "{passed, failed, coverage, report}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        template = get_language(state)
        blocks = self._extract_code_blocks(output)
        files: List[str] = []
        for idx, block in enumerate(blocks, start=1):
            path = block["path"]
            if not path:
                path = f"test_module_{idx}.{template.test_ext}"
            if not path.endswith(f".{template.test_ext}"):
                path += f".{template.test_ext}"
            res = await self._write_file(path, block["code"], workspace)
            if res.get("success"):
                files.append(path)

        if files:
            test_res = await self._run_command(f"{template.test_cmd} -q", workspace, timeout=15)
        else:
            test_res = {"success": False, "stdout": "", "stderr": "no tests generated"}

        report = self._extract_json(output) or {}
        passed = report.get("passed")
        failed = report.get("failed")
        if passed is None or failed is None:
            passed, failed = self._parse_test_summary(test_res.get("stdout", ""))

        return {
            "files": files,
            "passed": passed,
            "failed": failed,
            "coverage": report.get("coverage", 0.0),
            "report": (test_res.get("stdout", "") + "\n" + test_res.get("stderr", "")).strip(),
            "test_command_success": test_res.get("success", False),
        }

    @staticmethod
    def _parse_test_summary(stdout: str):
        m = re.search(r"(\d+)\s+passed", stdout)
        passed = int(m.group(1)) if m else 0
        m = re.search(r"(\d+)\s+failed", stdout)
        failed = int(m.group(1)) if m else 0
        return passed, failed


class ReviewerAgent(BaseAgent):
    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Reviewer",
            "代码审查",
            _load_prompt("reviewer"),
            model=model,
            skills=["code-review", "security", "performance"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"原始需求：{state.get('input', '')}\n"
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            f"测试报告：{(state.get('tester') or {}).get('report', '')[:1200]}\n"
            f"文档文件：{(state.get('docs') or {}).get('files', [])}\n"
            "请独立思考，从需求出发审查。输出 JSON：{severity, passed, issues, suggestions}"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        report = self._extract_json(output)
        if not report:
            # 无法解析 JSON 时做最保守判断
            report = {
                "severity": "medium",
                "passed": False,
                "issues": ["Reviewer 输出无法解析为 JSON"],
                "suggestions": ["请检查 LLM 输出格式"],
            }
        review_file = "review_report.json"
        await self._write_file(review_file, json.dumps(report, ensure_ascii=False, indent=2), workspace)
        report["report_file"] = review_file
        return report


class DocsAgent(BaseAgent):
    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Docs",
            "文档工程师",
            _load_prompt("docs"),
            model=model,
            skills=["documentation", "readme", "api-doc"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"架构：{str((state.get('architect') or {}).get('output', ''))[:800]}\n"
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            f"工作目录：{state.get('workspace', '')}\n"
            "请生成 README.md 与 API.md。用代码块标明文件路径，如 '# file: README.md'。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        blocks = self._extract_code_blocks(output)
        files: List[str] = []
        for block in blocks:
            path = block["path"] or "README.md"
            if not path.endswith(".md"):
                path += ".md"
            res = await self._write_file(f"docs/{path}", block["code"], workspace)
            if res.get("success"):
                files.append(f"docs/{path}")
        if not files:
            await self._write_file("docs/README.md", output, workspace)
            files.append("docs/README.md")
        return {"files": files}


class DevOpsAgent(BaseAgent):
    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "DevOps",
            "部署运维",
            _load_prompt("devops"),
            model=model,
            skills=["docker", "ci-cd", "deployment"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            "请生成 Dockerfile、docker-compose.yml 与 CI/CD 配置摘要，并说明部署前需人工确认。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        blocks = self._extract_code_blocks(output)
        files: List[str] = []
        for block in blocks:
            path = block["path"]
            if not path:
                continue
            res = await self._write_file(path, block["code"], workspace)
            if res.get("success"):
                files.append(path)
        if not files:
            await self._write_file("deploy_summary.md", output, workspace)
            files.append("deploy_summary.md")
        return {"files": files, "needs_approval": True}


class ProductManagerAgent(BaseAgent):
    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "ProductManager",
            "产品经理",
            _load_prompt("product_manager"),
            model=model,
            skills=["requirement-analysis", "prd", "user-stories"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"用户需求：{state.get('input', '')}\n"
            "请把需求拆分为 PRD、用户故事和验收标准。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        report = self._extract_json(output) or {}
        prd_file = "prd.md"
        await self._write_file(prd_file, output, workspace)
        return {
            "prd_file": prd_file,
            "user_stories": report.get("user_stories", []),
            "acceptance_criteria": report.get("acceptance_criteria", []),
            "parsed": report,
        }


class SecurityAgent(BaseAgent):
    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "Security",
            "安全审查",
            _load_prompt("security"),
            model=model,
            skills=["security-review", "vulnerability", "compliance"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"原始需求：{state.get('input', '')}\n"
            f"代码文件：{(state.get('coder') or {}).get('files', [])}\n"
            f"测试文件：{(state.get('tester') or {}).get('files', [])}\n"
            f"架构设计：{(state.get('architect') or {}).get('output', '')[:1500]}\n"
            "请独立进行安全审查，输出 JSON {severity, passed, issues, suggestions}。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        report = self._extract_json(output)
        if not report:
            report = {
                "severity": "medium",
                "passed": False,
                "issues": ["Security Agent 输出无法解析为 JSON"],
                "suggestions": ["请检查 LLM 输出格式"],
            }
        report_file = "security_report.json"
        await self._write_file(report_file, json.dumps(report, ensure_ascii=False, indent=2), workspace)
        report["report_file"] = report_file
        return report


class DBAAgent(BaseAgent):
    def __init__(self, model: Optional[str] = None):
        super().__init__(
            "DBA",
            "数据库架构",
            _load_prompt("dba"),
            model=model,
            skills=["database-design", "schema", "migration"],
        )

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return (
            f"原始需求：{state.get('input', '')}\n"
            f"架构设计：{(state.get('architect') or {}).get('output', '')[:2000]}\n"
            "请输出数据库 Schema 与迁移 SQL。"
        )

    async def postprocess(self, output: str, state: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(state)
        blocks = self._extract_code_blocks(output)
        files: List[str] = []
        for block in blocks:
            path = block["path"]
            if not path:
                continue
            if not path.endswith(".sql"):
                path += ".sql"
            res = await self._write_file(path, block["code"], workspace)
            if res.get("success"):
                files.append(path)

        report = self._extract_json(output) or {}
        if not files:
            await self._write_file("schema.sql", output, workspace)
            files.append("schema.sql")

        return {
            "files": files,
            "tables": report.get("tables", []),
            "notes": report.get("notes", ""),
        }


class MemoryAgentFacade:
    """对外的 Memory Agent 接口，供 Orchestrator 调用。"""

    def __init__(self, base_dir: str = "memory_store"):
        self._impl = MemoryAgent(base_dir=base_dir)

    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        session = state.get("request_id", "default")
        query = state.get("input", "")
        memories = self._impl.recall(query, session_id=session, layer="working", top_k=5)
        summary = self._impl.summarize(state.get("history", []))
        return {"agent": "Memory", "role": "记忆", "memories": memories, "summary": summary}


def _load_prompt(agent_name: str) -> str:
    """从 prompts.yaml 加载 System Prompt；失败时返回内置提示。"""
    prompt_file = Path(__file__).with_name("prompts.yaml")
    try:
        with open(prompt_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get(agent_name, _FALLBACK_PROMPTS.get(agent_name, f"你是 {agent_name} Agent。"))
    except Exception:  # noqa: BLE001
        return _FALLBACK_PROMPTS.get(agent_name, f"你是 {agent_name} Agent。")


_FALLBACK_PROMPTS: Dict[str, str] = {
    "architect": "你是 Architect Agent，负责架构设计。禁止写实现代码。",
    "coder": "你是 Coder Agent，负责生成可运行代码。",
    "tester": "你是 Tester Agent，负责生成并执行测试。",
    "reviewer": "你是 Reviewer Agent，必须独立思考，不信任上游。",
    "docs": "你是 Docs Agent，负责同步文档。",
    "devops": "你是 DevOps Agent，负责 CI/CD 与部署。",
    "product_manager": "你是 Product Manager Agent，负责需求分析与 PRD。",
    "security": "你是 Security Agent，负责独立安全审查。",
    "dba": "你是 DBA Agent，负责数据库 Schema 与迁移。",
}
```

## 附录 J：LangGraph 编排器（`orchestrator.py` 全文）

```python
"""DAG 编排器与迭代调度器（LangGraph StateGraph 实现）。"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from langgraph.graph import END, StateGraph

from dev_agent_system.agents import (
    ArchitectAgent,
    CoderAgent,
    DBAAgent,
    DevOpsAgent,
    DocsAgent,
    MemoryAgentFacade,
    ProductManagerAgent,
    ReviewerAgent,
    SecurityAgent,
    TesterAgent,
)
from dev_agent_system.checkpoint import make_checkpointer
from dev_agent_system.config import Settings
from dev_agent_system.devops import DevOpsRunner
from dev_agent_system.human_approval import HumanApprovalStore
from dev_agent_system.memory import MemoryAgent
from dev_agent_system.telemetry import DEFAULT as DEFAULT_TELEMETRY, Telemetry
from dev_agent_system.schemas import GraphState, GraphStateModel
from dev_agent_system.tracker import WorkflowTracker


def _review_passed(review: Dict[str, Any]) -> bool:
    """从 Reviewer 结构化输出中判断是否通过。"""
    passed = review.get("passed")
    if isinstance(passed, bool):
        return passed
    if isinstance(passed, str):
        return passed.lower() == "true"
    output = str(review.get("output", "")).lower()
    return '"passed": true' in output


class IdempotencyGuard:
    """基于 request_id 的幂等请求去重。"""

    def __init__(self, max_size: int = 200):
        self._seen: set = set()
        self._max_size = max_size

    def is_duplicate(self, request_id: str) -> bool:
        if request_id in self._seen:
            return True
        self._seen.add(request_id)
        if len(self._seen) > self._max_size:
            self._seen.pop()
        return False


class Orchestrator:
    """LangGraph 状态图编排器：Architect → Coder → {Tester, Docs} 并行 → Reviewer → 条件迭代。"""

    def __init__(
        self,
        max_iterations: int = 10,
        enable_devops: bool = False,
        devops_runner: Optional[Any] = None,
        enable_product_manager: bool = False,
        enable_security: bool = False,
        enable_dba: bool = False,
        telemetry: Optional[Telemetry] = None,
        tracker: Optional[WorkflowTracker] = None,
    ):
        self.max_iterations = max_iterations
        self.enable_devops = enable_devops
        self.devops_runner = devops_runner
        self.enable_product_manager = enable_product_manager
        self.enable_security = enable_security
        self.enable_dba = enable_dba
        self.telemetry = telemetry or DEFAULT_TELEMETRY
        self.tracker = tracker or WorkflowTracker()
        self.guard = IdempotencyGuard()
        self.memory = MemoryAgent()
        self.checkpointer = make_checkpointer()
        self.approval_store = HumanApprovalStore()
        self.agents = {
            "architect": ArchitectAgent(),
            "coder": CoderAgent(),
            "tester": TesterAgent(),
            "docs": DocsAgent(),
            "reviewer": ReviewerAgent(),
            "devops": DevOpsAgent(),
            "product_manager": ProductManagerAgent(),
            "security": SecurityAgent(),
            "dba": DBAAgent(),
            "memory": MemoryAgentFacade(),
        }

    def _build_state(
        self,
        requirement: str,
        request_id: Optional[str] = None,
        language: Optional[str] = "python",
    ) -> GraphState:
        request_id = request_id or str(uuid.uuid4())
        workspace = str(Settings.workspace_dir() / request_id)
        state = {
            "request_id": request_id,
            "input": requirement,
            "language": language or "python",
            "workspace": workspace,
            "iteration": 0,
            "max_iterations": self.max_iterations,
            "status": "submitted",
            "history": [],
        }
        # 用 Pydantic model 做启动前强校验，及早暴露字段类型错误
        return GraphStateModel.model_validate(state).model_dump(exclude_none=False)

    def _build_graph(self) -> StateGraph:
        """构建并返回编译后的 LangGraph。"""
        workflow = StateGraph(GraphState)

        if self.enable_product_manager:
            workflow.add_node("product_manager_node", self._product_manager_node)
            workflow.add_node("architect_node", self._architect_node)
            workflow.set_entry_point("product_manager_node")
            workflow.add_edge("product_manager_node", "architect_node")
        else:
            workflow.set_entry_point("architect_node")
            workflow.add_node("architect_node", self._architect_node)

        workflow.add_node("coder_node", self._coder_node)
        workflow.add_node("tester_docs_node", self._tester_docs_node)
        workflow.add_node("reviewer_node", self._reviewer_node)

        if self.enable_dba:
            workflow.add_node("dba_node", self._dba_node)
            workflow.add_edge("architect_node", "dba_node")
            workflow.add_edge("dba_node", "coder_node")
        else:
            workflow.add_edge("architect_node", "coder_node")

        workflow.add_edge("coder_node", "tester_docs_node")
        workflow.add_edge("tester_docs_node", "reviewer_node")

        # 确定条件边的挂载点
        if self.enable_security:
            workflow.add_node("security_node", self._security_node)
            workflow.add_edge("reviewer_node", "security_node")
            conditional_source = "security_node"
        else:
            conditional_source = "reviewer_node"

        if self.enable_devops:
            workflow.add_node("devops_node", self._devops_node)
            workflow.add_conditional_edges(
                conditional_source,
                self._should_continue,
                {"continue": "architect_node", "end": "devops_node"},
            )
            workflow.add_edge("devops_node", END)
        else:
            workflow.add_conditional_edges(
                conditional_source,
                self._should_continue,
                {"continue": "architect_node", "end": END},
            )

        return workflow.compile(checkpointer=self.checkpointer)

    def _thread_config(self, request_id: str) -> Dict[str, Any]:
        return {
            "configurable": {"thread_id": request_id},
            "recursion_limit": max(50, self.max_iterations * 5 + 10),
        }

    async def run(
        self,
        requirement: str,
        request_id: Optional[str] = None,
        language: Optional[str] = "python",
    ) -> Dict[str, Any]:
        state = self._build_state(requirement, request_id, language=language)
        if self.guard.is_duplicate(state["request_id"]):
            return {"request_id": state["request_id"], "status": "skipped", "reason": "duplicate"}

        self.tracker.start(state["request_id"], requirement)
        with self.telemetry.span("orchestrator.run", {"request_id": state["request_id"]}):
            # 注入工作记忆
            state["memory"] = await self.agents["memory"].run(state)

            graph = self._build_graph()
            config = self._thread_config(state["request_id"])
            final_state = await graph.ainvoke(state, config)
            final_state["finished_at"] = datetime.now().isoformat()
            final_state["artifacts"] = self._collect_artifacts(final_state)
            self.telemetry.record_event(
                "workflow.completed",
                request_id=state["request_id"],
                status=final_state.get("status", "unknown"),
                iterations=str(final_state.get("iteration", 0)),
            )
            self._record_workflow_metrics(final_state)
            self.tracker.finish(state["request_id"], final_state)
            return final_state

    async def resume(self, request_id: str) -> Dict[str, Any]:
        """从 SQLite checkpoint 恢复并继续执行工作流。"""
        self.tracker.update(request_id, status="resumed")
        with self.telemetry.span("orchestrator.resume", {"request_id": request_id}):
            graph = self._build_graph()
            config = self._thread_config(request_id)
            snapshot = await graph.aget_state(config)
            if snapshot is None or not snapshot.next:
                # 任务已完成或不存在未执行任务，直接取最新状态
                final_state = dict(snapshot.values) if snapshot else {}
            else:
                final_state = await graph.ainvoke(None, config)
                if final_state is None:
                    snapshot = await graph.aget_state(config)
                    final_state = dict(snapshot.values) if snapshot else {}
            final_state["finished_at"] = datetime.now().isoformat()
            final_state["artifacts"] = self._collect_artifacts(final_state)
            self._record_workflow_metrics(final_state)
            self.tracker.finish(request_id, final_state)
            return final_state

    async def approve_devops(self, request_id: str, approve: bool = True) -> Dict[str, Any]:
        """审批并继续执行 DevOps 部署节点。

        适用于 workflow 在 _devops_node 因缺少人工审批而进入 awaiting_approval 状态后，
        由管理员通过 API 调用继续。
        """
        if approve:
            self.approval_store.approve(request_id)
        else:
            self.approval_store.reject(request_id)
            final_state = {"request_id": request_id, "status": "rejected", "devops": {"approved": False}}
            self.tracker.finish(request_id, final_state)
            return final_state

        graph = self._build_graph()
        config = self._thread_config(request_id)
        snapshot = await graph.aget_state(config)
        if snapshot is None:
            return {"request_id": request_id, "status": "not_found", "error": "checkpoint not found"}

        state = dict(snapshot.values)
        state["status"] = "working"
        final_state = await self._devops_node(state)
        final_state["finished_at"] = datetime.now().isoformat()
        final_state["artifacts"] = self._collect_artifacts(final_state)
        self._record_workflow_metrics(final_state)
        self.tracker.finish(request_id, final_state)
        return final_state

    def get_approval_status(self, request_id: str) -> str:
        return self.approval_store.get_status(request_id)

    def list_checkpoints(self, request_id: str) -> List[Dict[str, Any]]:
        """返回指定 request_id 的历史 checkpoint 列表。"""
        config: Dict[str, Any] = {"configurable": {"thread_id": request_id}}
        return [
            {
                "checkpoint_id": tuple_item.config["configurable"].get("checkpoint_id"),
                "metadata": tuple_item.metadata,
            }
            for tuple_item in self.checkpointer.list(config)
        ]

    async def run_stream(
        self,
        requirement: str,
        request_id: Optional[str] = None,
        language: Optional[str] = "python",
    ) -> AsyncIterator[str]:
        """流式执行编排，SSE 格式输出每个节点的事件。"""
        state = self._build_state(requirement, request_id, language=language)
        if self.guard.is_duplicate(state["request_id"]):
            yield f"data: {json.dumps({'event': 'duplicate', 'request_id': state['request_id']}, ensure_ascii=False)}\n\n"
            return

        state["memory"] = await self.agents["memory"].run(state)
        graph = self._build_graph()
        config = self._thread_config(state["request_id"])

        yield f"data: {json.dumps({'event': 'start', 'request_id': state['request_id'], 'workspace': state['workspace']}, ensure_ascii=False)}\n\n"

        # LangGraph 0.2.0 支持 astream_events，失败则降级到普通 ainvoke
        try:
            async for event in graph.astream_events(state, config, version="v1"):
                kind = event.get("event")
                name = event.get("name", "")
                if kind in ("on_node_start", "on_node_end"):
                    payload = {
                        "event": kind,
                        "node": name,
                        "request_id": state["request_id"],
                    }
                    if kind == "on_node_end" and "data" in event and "state" in event["data"]:
                        node_state = event["data"]["state"]
                        payload["iteration"] = node_state.get("iteration", 0)
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            # 降级：直接执行并输出结果
            final_state = await graph.ainvoke(state, config=config)
            yield f"data: {json.dumps({'event': 'fallback', 'error': str(exc), 'status': final_state.get('status')}, ensure_ascii=False)}\n\n"
            final_state["finished_at"] = datetime.now().isoformat()
            final_state["artifacts"] = self._collect_artifacts(final_state)
            yield f"data: {json.dumps({'event': 'final', 'request_id': state['request_id'], **final_state}, ensure_ascii=False)}\n\n"
            return

        final_state = await graph.ainvoke(state, config=config)
        final_state["finished_at"] = datetime.now().isoformat()
        final_state["artifacts"] = self._collect_artifacts(final_state)
        yield f"data: {json.dumps({'event': 'final', 'status': final_state.get('status'), 'request_id': state['request_id'], 'workspace': state['workspace']}, ensure_ascii=False)}\n\n"

    async def _architect_node(self, state: GraphState) -> GraphState:
        state["iteration"] = state.get("iteration", 0) + 1
        state["status"] = "working"
        state["architect"] = await self._run_agent("architect", state)
        return state

    async def _coder_node(self, state: GraphState) -> GraphState:
        state["coder"] = await self._run_agent("coder", state)
        return state

    async def _tester_docs_node(self, state: GraphState) -> GraphState:
        tester, docs = await asyncio.gather(
            self._run_agent("tester", state),
            self._run_agent("docs", state),
        )
        state["tester"] = tester
        state["docs"] = docs
        return state

    async def _reviewer_node(self, state: GraphState) -> GraphState:
        state["reviewer"] = await self._run_agent("reviewer", state)
        record = {
            "iteration": state.get("iteration", 0),
            "architect": state.get("architect"),
            "coder": state.get("coder"),
            "tester": state.get("tester"),
            "docs": state.get("docs"),
            "reviewer": state.get("reviewer"),
        }
        state["history"] = (state.get("history", []) + [record])[-5:]
        review = state.get("reviewer") or {}
        passed = _review_passed(review)
        # 在节点内设置状态（条件边函数不应修改状态）
        if passed:
            state["status"] = "completed"
        elif state.get("iteration", 0) >= self.max_iterations:
            state["status"] = "failed"
        else:
            state["status"] = "working"
        self.memory.remember(
            f"review_iter_{state.get('iteration', 0)}",
            review.get("output", ""),
            session_id=state.get("request_id", "default"),
            layer="working",
        )
        return state

    def _should_continue(self, state: GraphState) -> str:
        review = state.get("reviewer") or {}
        if not _review_passed(review):
            if state.get("iteration", 0) >= self.max_iterations:
                return "end"
            return "continue"

        # reviewer 通过后，若启用 Security Agent，还需通过安全审查
        if self.enable_security:
            security = state.get("security") or {}
            if not _review_passed(security):
                if state.get("iteration", 0) >= self.max_iterations:
                    return "end"
                return "continue"

        return "end"

    async def _product_manager_node(self, state: GraphState) -> GraphState:
        state["product_manager"] = await self._run_agent("product_manager", state)
        return state

    async def _dba_node(self, state: GraphState) -> GraphState:
        state["dba"] = await self._run_agent("dba", state)
        return state

    async def _security_node(self, state: GraphState) -> GraphState:
        state["security"] = await self._run_agent("security", state)
        return state

    async def _devops_node(self, state: GraphState) -> GraphState:
        devops_result = await self._run_agent("devops", state)
        request_id = state.get("request_id", "default")
        runner = self.devops_runner or DevOpsRunner(
            dry_run=Settings.devops_dry_run(),
            timeout=Settings.devops_timeout(),
        )
        workspace = Path(state.get("workspace", Settings.workspace_dir() / request_id))

        # 仅在需要真实执行时触发人工审批
        dry_run = getattr(runner, "dry_run", Settings.devops_dry_run())
        if not dry_run and Settings.human_approval_required() and not self.approval_store.is_approved(request_id):
            self.approval_store.request_approval(request_id)
            devops_result["needs_approval"] = True
            devops_result["approved"] = False
            devops_result["deployment"] = {
                "deployed": False,
                "status": "awaiting_approval",
                "note": "等待人工审批后才能执行真实部署",
            }
            state["status"] = "awaiting_approval"
            state["devops"] = devops_result
            return state

        deployment = await asyncio.to_thread(runner.run, request_id, workspace)
        devops_result["deployment"] = deployment
        devops_result["needs_approval"] = False
        devops_result["approved"] = True
        state["devops"] = devops_result
        return state

    async def _run_agent(self, name: str, state: GraphState) -> Dict[str, Any]:
        agent = self.agents[name]
        request_id = state.get("request_id", "")
        self.tracker.update(
            request_id,
            current_agent=name,
            iteration=state.get("iteration", 0),
            status="working",
        )
        with self.telemetry.span(f"agent.{name}", {"agent": name, "request_id": request_id}):
            if asyncio.iscoroutinefunction(agent.run):
                result = await agent.run(state)
            else:
                result = agent.run(state)
            status = "error" if result and not result.get("success", True) else "ok"
            self.telemetry.collector.counter(
                "agent_runs_total",
                "Total number of agent runs",
                labelnames=["agent", "status"],
            ).inc(agent=name, status=status)
            return result

    def _record_workflow_metrics(self, state: GraphState) -> None:
        request_id = state.get("request_id", "")
        iterations = state.get("iteration", 0)
        status = state.get("status", "unknown")
        review = state.get("reviewer") or {}
        review_passed = _review_passed(review)

        self.telemetry.collector.gauge("workflow_iterations", "Workflow iteration count").set(
            iterations, request_id=request_id
        )
        self.telemetry.collector.counter(
            "workflow_total",
            "Total number of workflow runs",
            labelnames=["status"],
        ).inc(status=status)
        self.telemetry.collector.counter(
            "review_decisions_total",
            "Total number of review decisions",
            labelnames=["passed"],
        ).inc(passed=str(review_passed).lower())

    @staticmethod
    def _collect_artifacts(state: GraphState) -> Dict[str, Any]:
        tester = state.get("tester") or {}
        return {
            "workspace": state.get("workspace", ""),
            "design": (state.get("architect") or {}).get("output", ""),
            "design_file": (state.get("architect") or {}).get("design_file"),
            "code_files": (state.get("coder") or {}).get("files", []),
            "test_files": tester.get("files", []),
            "doc_files": (state.get("docs") or {}).get("files", []),
            "review_report": (state.get("reviewer") or {}).get("report_file"),
            "review_passed": _review_passed(state.get("reviewer") or {}),
            # 保留原始测试 stdout 便于排查；tester.output 已被替换为摘要
            "tests": tester.get("report", tester.get("output", "")),
            "docs": (state.get("docs") or {}).get("output", ""),
            "review": (state.get("reviewer") or {}).get("output", ""),
            "devops": (state.get("devops") or {}).get("output", "") if state.get("devops") else "",
            "product_manager": (state.get("product_manager") or {}).get("output", "") if state.get("product_manager") else "",
            "prd_file": (state.get("product_manager") or {}).get("prd_file"),
            "security_report": (state.get("security") or {}).get("report_file"),
            "security_passed": _review_passed(state.get("security") or {}),
            "schema_files": (state.get("dba") or {}).get("files", []),
        }
```

## 附录 K：模型与 MCP 配置

### K.1 `config/model.yaml`

```yaml
# 各 Agent 使用的 LLM 模型版本，必须锁定到具体版本号，禁止使用滚动标签

architect:
  model: gpt-4-0613
  temperature: 0.2

coder:
  model: gpt-4-turbo-2024-04-09
  temperature: 0.1

reviewer:
  model: gpt-4o-2024-08-06
  temperature: 0.2

tester:
  model: gpt-4-0613
  temperature: 0.2

docs:
  model: gpt-3.5-turbo-0125
  temperature: 0.3

devops:
  model: gpt-4-0613
  temperature: 0.2

product_manager:
  model: gpt-4-0613
  temperature: 0.3

security:
  model: gpt-4o-2024-08-06
  temperature: 0.2

dba:
  model: gpt-4-0613
  temperature: 0.2
```

### K.2 `config/mcp.yaml`

```yaml
mcp_servers:
  filesystem:
    command: python
    args: ["-m", "mcp_server_filesystem", "./workspace"]
    allowed_paths:
      - "./workspace"
  github:
    api_key_env: GITHUB_TOKEN
  terminal:
    timeout: 5
    whitelist:
      - python
      - pytest
      - git
      - ls
      - cat
      - echo
      - "docker build"
  db:
    connection_env: DATABASE_URL
  conda:
    command: conda
```



## 附录 M：`HumanApprovalStore`（`human_approval.py` 全文）

```python
"""Human-in-the-Loop 审批状态管理。

支持 SQLite 持久化，以便 Orchestrator、Server、Resume 等独立实例共享审批状态。
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from dev_agent_system.config import Settings


class HumanApprovalStore:
    """基于 SQLite 的人工审批状态存储。"""

    _instance: Optional["HumanApprovalStore"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls, db_path: Optional[Path] = None) -> "HumanApprovalStore":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._db_path = db_path or Settings.approval_db()
                    cls._instance._init_db()
        return cls._instance

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS approvals (
                    request_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _upsert(self, request_id: str, status: str) -> None:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                """
                INSERT INTO approvals (request_id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(request_id) DO UPDATE SET
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (request_id, status, now, now),
            )
            conn.commit()

    def request_approval(self, request_id: str) -> None:
        """将 request_id 标记为等待审批。"""
        self._upsert(request_id, "pending")

    def approve(self, request_id: str) -> None:
        """批准指定 request_id。"""
        self._upsert(request_id, "approved")

    def reject(self, request_id: str) -> None:
        """拒绝指定 request_id。"""
        self._upsert(request_id, "rejected")

    def is_approved(self, request_id: str) -> bool:
        return self.get_status(request_id) == "approved"

    def get_status(self, request_id: str) -> str:
        with sqlite3.connect(str(self._db_path)) as conn:
            cur = conn.execute(
                "SELECT status FROM approvals WHERE request_id = ?",
                (request_id,),
            )
            row = cur.fetchone()
        return row[0] if row else "not_found"

    def list_pending(self) -> List[Dict[str, Any]]:
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT request_id, status, created_at, updated_at FROM approvals WHERE status = 'pending' ORDER BY created_at DESC"
            )
            return [dict(row) for row in cur.fetchall()]
```
## 附录 L：模块文件清单

- `dev_agent_system/__init__.py`
- `dev_agent_system/a2a_client.py`
- `dev_agent_system/a2a_node.py`
- `dev_agent_system/agents.py`
- `dev_agent_system/checkpoint.py`
- `dev_agent_system/config.py`
- `dev_agent_system/dashboard.py`
- `dev_agent_system/devops.py`
- `dev_agent_system/eval.py`
- `dev_agent_system/llm.py`
- `dev_agent_system/llm_providers.py`
- `dev_agent_system/main.py`
- `dev_agent_system/mcp.py`
- `dev_agent_system/memory.py`
- `dev_agent_system/metrics.py`
- `dev_agent_system/orchestrator.py`
- `dev_agent_system/router.py`
- `dev_agent_system/schemas.py`
- `dev_agent_system/security.py`
- `dev_agent_system/security_scanner.py`
- `dev_agent_system/server.py`
- `dev_agent_system/skills.py`
- `dev_agent_system/telemetry.py`
- `dev_agent_system/templates.py`
- `dev_agent_system/tracker.py`
- `dev_agent_system/tui.py`
- `tests/test_a2a.py`
- `tests/test_checkpoint.py`
- `tests/test_dashboard.py`
- `tests/test_devops.py`
- `tests/test_eval.py`
- `tests/test_flow.py`
- `tests/test_llm.py`
- `tests/test_memory.py`
- `tests/test_metrics.py`
- `tests/test_multilang.py`
- `tests/test_new_agents.py`
- `tests/test_security.py`
- `tests/test_security_scanner.py`
- `tests/test_server.py`
- `tests/test_server_skills.py`
- `tests/test_skills.py`
- `tests/test_telemetry.py`
- `tests/test_templates.py`
- `tests/test_tui.py`

