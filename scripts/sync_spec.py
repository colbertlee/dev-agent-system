"""自动同步 `docs/agent_generator_spec.md` 与 `docs/agent_framework_retrospective.md` 中的源码附录和版本信息。

用法：
    python scripts/sync_spec.py
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "docs" / "agent_generator_spec.md"
RETRO = ROOT / "docs" / "agent_framework_retrospective.md"


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def fence(content: str, lang: str = "python") -> str:
    return f"```{lang}\n{content.rstrip()}\n```"


def extract_node(source: str, name: str) -> str:
    """用 AST 提取 source 中顶层 class / function / assignment 的完整源码。"""
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    for node in tree.body:
        node_name = getattr(node, "name", None)
        if node_name == name:
            start = node.lineno - 1
            end = getattr(node, "end_lineno", None)
            if end is None:
                # 老版本 AST 没有 end_lineno，则缩进匹配
                return _fallback_extract(source, name)
            return "".join(lines[start:end]).rstrip()
        # 处理形如 _FALLBACK_PROMPTS 的全局赋值
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if getattr(target, "id", None) == name:
                    start = node.lineno - 1
                    end = getattr(node, "end_lineno", node.lineno)
                    return "".join(lines[start:end]).rstrip()
    return _fallback_extract(source, name)


def _fallback_extract(source: str, name: str) -> str:
    """AST end_lineno 不可用时，按缩进简单匹配顶层 class/def/assign。"""
    pattern = rf"^(class {re.escape(name)}|def {re.escape(name)}|{re.escape(name)}\s*=)\b.*?(?=\n(?=\S)|\Z)"
    m = re.search(pattern, source, re.MULTILINE | re.DOTALL)
    return m.group(0).rstrip() if m else f"# {name} not found"


def replace_after_heading(text: str, heading: str, new_code: str, lang: str = "python") -> str:
    """heading 之后第一个 fenced code block 替换为 new_code。"""
    escaped = re.escape(heading)
    pattern = re.compile(rf"({escaped}\n\n)```(?:\w+)?\n.*?```", re.DOTALL)
    if not pattern.search(text):
        print(f"[warn] heading not found or no code block: {heading}")
        return text
    return pattern.sub(lambda m: f"{m.group(1)}{fence(new_code, lang)}", text, count=1)


def update_spec() -> None:
    text = SPEC.read_text(encoding="utf-8")

    # 1. 版本刷新
    text = text.replace("v0.20.0", "v0.22.0")
    text = text.replace("`dev_agent_system` v0.20.0", "`dev_agent_system` v0.22.0")

    # 2. 顶部摘要
    if "json_mode" not in text[:1200]:
        text = re.sub(
            r"所有内容均来自现有代码、测试与文档，不引入未实现功能。",
            "所有内容均来自现有代码、测试与文档，不引入未实现功能。\n\n> 本版同步了 v0.21.0/v0.22.0 新增能力：LLM `json_mode` 结构化输出、`BaseAgent.report_schema` Pydantic 校验、Human-in-the-Loop 审批门、以及 `summary_budget` 状态摘要。",
            text,
            count=1,
        )

    # 3. GraphState status 说明
    text = re.sub(
        r'status: str,               # submitted / working / completed / failed',
        'status: str,               # submitted / working / completed / failed / awaiting_approval',
        text,
    )
    text = re.sub(
        r'\*\*A2A 协议\*\* `dev_agent_system/schemas.py`',
        '**A2A 协议** `dev_agent_system/schemas.py`（新增 `awaiting_approval` 状态，用于 Human-in-the-Loop）',
        text,
    )

    # 4. 工作流说明
    text = re.sub(
        r"devops_node \(可选 enable_devops，仅在通过时\)",
        "approval_gate -> devops_node （可选 enable_devops；真实部署需 HumanApprovalStore 审批）",
        text,
    )

    # 5. 附录源码重抽
    appendix_files = [
        ("## 附录 A：完整 `prompts.yaml`", "dev_agent_system/prompts.yaml", "yaml"),
        ("## 附录 B：完整 `agent_cards.json`", "dev_agent_system/agent_cards.json", "json"),
        ("## 附录 C：A2A 与内部状态数据模型（`schemas.py` 全文）", "dev_agent_system/schemas.py", "python"),
        ("## 附录 D：多语言项目模板（`templates.py` 全文）", "dev_agent_system/templates.py", "python"),
        ("## 附录 E：MCP 工具沙箱与注册中心（`mcp.py` 全文）", "dev_agent_system/mcp.py", "python"),
        ("## 附录 F：安全扫描与脱敏（`security.py` 全文）", "dev_agent_system/security.py", "python"),
        ("## 附录 G：三层记忆实现（`memory.py` 全文）", "dev_agent_system/memory.py", "python"),
        ("## 附录 H：LLM 抽象与 Provider（`llm.py` 全文）", "dev_agent_system/llm.py", "python"),
        ("## 附录 I：`BaseAgent` 生命周期（`agents.py` 节选）", "dev_agent_system/agents.py", "python"),
        ("## 附录 J：LangGraph 编排器（`orchestrator.py` 全文）", "dev_agent_system/orchestrator.py", "python"),
    ]
    for heading, rel, lang in appendix_files:
        text = replace_after_heading(text, heading, read(rel), lang)

    # 6. llm_providers.py 小节
    text = replace_after_heading(
        text,
        "### H.1 LLM Provider 实现（`llm_providers.py`）",
        read("dev_agent_system/llm_providers.py"),
        "python",
    )

    # 7. config 文件子节
    text = replace_after_heading(
        text,
        "### K.1 `config/model.yaml`",
        read("config/model.yaml"),
        "yaml",
    )
    text = replace_after_heading(
        text,
        "### K.2 `config/mcp.yaml`",
        read("config/mcp.yaml"),
        "yaml",
    )

    # 8. 新增 human_approval.py 附录
    if "## 附录 M：`HumanApprovalStore`" not in text:
        ha_block = (
            "\n\n## 附录 M：`HumanApprovalStore`（`human_approval.py` 全文）\n\n"
            + fence(read("dev_agent_system/human_approval.py"), "python")
            + "\n"
        )
        text = text.replace("## 附录 L：模块文件清单", ha_block + "## 附录 L：模块文件清单", 1)

    # 9. 逐 Agent 实现要点替换
    agents_source = read("dev_agent_system/agents.py")
    mapping = [
        ("#### 3.1.3 实现要点", "ProductManagerAgent"),
        ("#### 3.2.3 实现要点", "ArchitectAgent"),
        ("#### 3.3.3 实现要点", "DBAAgent"),
        ("#### 3.4.3 实现要点", "CoderAgent"),
        ("#### 3.5.3 实现要点", "TesterAgent"),
        ("#### 3.6.3 实现要点", "ReviewerAgent"),
        ("#### 3.7.3 实现要点", "SecurityAgent"),
        ("#### 3.8.3 实现要点", "DocsAgent"),
        ("#### 3.9.3 实现要点", "DevOpsAgent"),
    ]
    for heading, class_name in mapping:
        code = extract_node(agents_source, class_name)
        text = replace_after_heading(text, heading, code, "python")

    # 10. BaseAgent 生命周期小节（若存在可替换为完整 agents.py，已在附录 I 处理）
    # 仅补充 summary 说明
    if "_summarize_result" not in text[:6000]:
        text = re.sub(
            r"- `postprocess`：子类重写，解析输出、调用 MCP 工具、写入产物。",
            "- `postprocess`：子类重写，解析输出、调用 MCP 工具、写入产物。\n- `_summarize_result`：把运行结果按 `summary_budget` 压缩为合法 JSON，替换原始 `output` 后进入下游 state/memory。",
            text,
        )

    # 11. 附录 L 模块清单追加
    if "human_approval.py" not in text:
        text = text.replace(
            "- `dev_agent_system/eval.py`",
            "- `dev_agent_system/human_approval.py`\n- `dev_agent_system/eval.py`",
            1,
        )
        text = text.replace(
            "- `tests/test_a2a.py`",
            "- `tests/test_a2a.py`\n- `tests/test_context_compression.py`",
            1,
        )

    SPEC.write_text(text, encoding="utf-8")
    print(f"已更新：{SPEC}")


def update_retro() -> None:
    if not RETRO.exists():
        return
    text = RETRO.read_text(encoding="utf-8")

    # 版本范围
    text = text.replace("v0.13.0 ~ v0.19.0", "v0.13.0 ~ v0.22.0")
    text = re.sub(
        r"未引入任何尚未实现的功能",
        "并补充了 v0.21.0/v0.22.0 的结构化输出、Human-in-the-Loop 与状态摘要说明",
        text,
        count=1,
    )

    # 把容易失步的 <ref_snippet file=... lines=.../> 转为 <ref_file file=.../>
    text = re.sub(
        r'<ref_snippet file="([^"]+)" lines="[^"]+"\s*/?>',
        r'<ref_file file="\1" />',
        text,
    )

    # 新增 v0.21/v0.22 落地小节
    new_section = """\n\n---\n\n## 1.5 v0.21.0 / v0.22.0 新增四要素落地\n\n### 1.5.1 结构化输出与 Pydantic 校验（JSON Mode）\n\n- `LLMClient.chat(system, user, json_mode=True)` 在 OpenAI/DeepSeek 请求中注入 `response_format={"type": "json_object"}`，在 Ollama 中注入 `format="json"`。 <ref_file file="dev_agent_system/llm.py" />\n- `BaseAgent.json_output` 与 `report_schema` 让子类声明是否强制 JSON 及对应的 Pydantic 模型。 <ref_file file="dev_agent_system/agents.py" />\n- `_parse_json_output` 兼容纯 JSON、Markdown 内嵌 JSON 与已解析 dict；校验失败时仍返回原 dict 供降级。\n\n### 1.5.2 Human-in-the-Loop 审批\n\n- 新增 `HumanApprovalStore`，把 `pending/approved/rejected` 状态持久化到 SQLite，路径由 `APPROVAL_DB` 环境变量控制。 <ref_file file="dev_agent_system/human_approval.py" />\n- `Orchestrator._devops_node` 在真实部署（`DEVOPS_DRY_RUN=false`）前检查审批状态，未审批时返回 `awaiting_approval`。 <ref_file file="dev_agent_system/orchestrator.py" />\n- `server.py` 暴露 `/tasks/{request_id}/approval`、`/approve`、`/reject` 端点。 <ref_file file="dev_agent_system/server.py" />\n\n### 1.5.3 Agent 间状态摘要（Context Compression v2）\n\n- `BaseAgent.summary_budget` 为每个 Agent 配置摘要长度上限，避免原始 LLM 输出进入下游 prompt/checkpoint。 <ref_file file="dev_agent_system/agents.py" />\n- `_summarize_result` 丢弃 `output/workspace/model/llm_kwargs` 等元数据，递归截断长字符串/列表，保证合法 JSON。\n- `_truncate_for_summary` 自适应调整截断粒度，`Orchestrator._collect_artifacts` 优先保留 `tester.report` 供排障。 <ref_file file="dev_agent_system/orchestrator.py" />\n\n"""
    if "## 1.5 v0.21.0 / v0.22.0" not in text:
        text = text.replace("## 2. Coder Agent Prompting 模板", new_section + "## 2. Coder Agent Prompting 模板", 1)

    # 核查表追加
    if "HumanApprovalStore" not in text:
        text = re.sub(
            r"(\| 工作流与异常处理 \| LangGraph DAG.*?\| `orchestrator.py` \|\n)",
            r"\1| 结构化输出 | `json_mode` + `report_schema` + Pydantic 校验 | `llm.py`, `llm_providers.py`, `agents.py`, `schemas.py` |\n| 人工审批 | `HumanApprovalStore` + 审批 API | `human_approval.py`, `orchestrator.py`, `server.py` |\n| 状态摘要 | `summary_budget` + `_summarize_result` + `_truncate_for_summary` | `agents.py`, `orchestrator.py` |\n",
            text,
        )

    RETRO.write_text(text, encoding="utf-8")
    print(f"已更新：{RETRO}")


def main() -> None:
    update_spec()
    update_retro()


if __name__ == "__main__":
    main()
