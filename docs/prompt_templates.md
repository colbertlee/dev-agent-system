# prompt_templates.md

## 1. 版本化管理原则

`dev_agent_system/prompts.yaml` 是系统提示词（System Prompt）的唯一真实来源。所有 Agent 在运行时通过 `agents.py` 的 `_load_prompt()` 加载对应提示词。

版本化规则：

1. **单一来源**：不要硬编码 prompt；所有修改必须写入 `prompts.yaml`。
2. **变更可追溯**：修改 Prompt 时应单独 commit，类型使用 `model` 或 `docs`，并在 `CHANGELOG.md` 中说明原因。
3. **影响评估**：修改 Prompt 后必须运行 `pytest`，因为它可能改变 Agent 输出格式（尤其是 JSON 结构）。
4. **备份与回滚**：重要 Prompt 变更前，建议复制旧版本到 `docs/prompt_history/<version>/prompts.yaml`。

## 2. Prompt 结构

`prompts.yaml` 使用 YAML 键值对，键为 Agent 小写名称，值为 `|` 多行字符串：

```yaml
architect: |
  你是 Architect Agent（系统架构师）。
  ...

coder: |
  你是 Coder Agent（代码实现引擎）。
  ...
```

## 3. 当前 Prompt 清单

| Agent | 文件键 | 核心职责 | 输出约束 | JSON Mode / `report_schema` |
|---|---|---|---|---|
| ProductManager | `product_manager` | 需求澄清、PRD、用户故事、验收标准 | Markdown 代码块 `# file: prd.md` + JSON | 否 |
| Architect | `architect` | 需求分析、架构设计、技术选型 | JSON：`{modules, api_contract, tech_stack, mermaid, notes}` | 是 / `DesignOutput` |
| DBA | `dba` | 数据库 Schema 与迁移脚本 | SQL 代码块 + JSON：`{tables, notes}` | 是 / `DBAReport` |
| Coder | `coder` | 代码实现、自测 | 代码块 + JSON 报告：`{files, report}` | 是 / `AgentOutput` |
| Tester | `tester` | 生成并执行 pytest | 代码块 + JSON 测试报告 | 是 / `AgentOutput` |
| Reviewer | `reviewer` | 独立审查代码/测试/文档 | JSON：`{severity, passed, issues, suggestions}` | 是 / `ReviewReport` |
| Security | `security` | 独立安全审查 | JSON：`{severity, passed, issues, suggestions}` | 是 / `ReviewReport` |
| Docs | `docs` | 生成 README / API 文档 | Markdown 代码块，文件头：`# file: README.md` | 否 |
| DevOps | `devops` | CI/CD、部署配置 | Dockerfile / docker-compose / GitHub Actions 配置 | 否 |

## 4. 输出格式约定

为了让下游 Agent 与 `postprocess` 正确解析，每个 Prompt 必须明确指定输出格式。

### 4.1 代码块规范

代码块必须包含前导文件头，并置于 fenced code block 中：

```markdown
# file: path/to/file.py
```python
def add(a, b):
    return a + b
```
```

`BaseAgent._extract_code_blocks()` 会同时解析 `file/path/filename:` 头部与 ` ``` ` 之间的内容。

### 4.2 JSON 报告规范

所有 JSON 报告应使用独立的 ` ```json ` 块，并尽量只包含一层嵌套，避免 LLM 生成不可解析的结构：

```markdown
```json
{"severity": "low", "passed": true, "issues": [], "suggestions": []}
```
```

### 4.3 JSON Mode 与 Pydantic 校验

- `LLMClient.chat(..., json_mode=True)` 会在 OpenAI/DeepSeek 请求中注入 `response_format={"type": "json_object"}`，在 Ollama 请求中注入 `format="json"`。
- `BaseAgent` 通过 `report_schema` 字段绑定 Pydantic 模型；收到 LLM 输出后先调用 `_parse_json_output`，解析失败时兼容 Markdown 代码块并给出 fallback。
- 提示词中应明确要求“必须且仅输出合法 JSON”，避免 LLM 附带说明文字导致解析失败。
- 兼容策略：即使 `json_mode` 失败，`_extract_json` 仍会从 Markdown 代码块中抢救第一个 `{}` 或 `[]`。

## 5. Prompt 调优 checklist

修改任一 Prompt 后，请确认：

- [ ] `python -m pytest tests -q` 通过
- [ ] 相关 Agent 的 `postprocess` 仍能正确解析输出
- [ ] 如果启用了 `json_mode` 或修改了 `report_schema`，同步更新 `tests/` 中的 mock 响应
- [ ] 在 `CHANGELOG.md` / `RELEASE_NOTES.md` 中记录 Prompt 变更原因与预期影响

## 6. 扩展新 Agent Prompt

新增 Agent 时：

1. 在 `dev_agent_system/agents.py` 中继承 `BaseAgent`。
2. 在 `prompts.yaml` 添加 `<agent_name>:` 键。
3. 在 `dev_agent_system/agent_cards.json` 更新技能描述。
4. 在 `tests/` 中补充至少一个输入/解析测试。
5. 更新本文件 `当前 Prompt 清单` 表格。

## 7. 相关文件

- `dev_agent_system/prompts.yaml` —— 真实 Prompt 源文件
- `dev_agent_system/agents.py` —— Prompt 加载与 `postprocess` 解析
- `docs/tools_spec.md` —— 工具调用输出格式
- `CONTRIBUTE.md` —— Prompt 变更提交规范
