"""把项目 Markdown 文档转换为响应式、带目录、支持暗色模式的离线 HTML。

用法示例：
    python scripts/generate_docs.py docs/agent_generator_spec.md
    python scripts/generate_docs.py docs/agent_framework_retrospective.md --output docs/agent_framework_retrospective.html
"""
from __future__ import annotations

import argparse
import os
import re
import unicodedata
from pathlib import Path

import markdown
from markdown.extensions.fenced_code import FencedCodeExtension
from markdown.extensions.tables import TableExtension
from markdown.extensions.toc import TocExtension


ROOT = Path(__file__).resolve().parent.parent


def _slugify(value: str, separator: str = "-") -> str:
    """保留中文字符、ASCII 字母/数字的 slugify，与现有 HTML 风格兼容。"""
    value = value.strip().lower()
    # 把非字母数字中文字符统一替换为分隔符
    value = re.sub(r"[^\w\u4e00-\u9fff]+", separator, value)
    value = re.sub(rf"{re.escape(separator)}+", separator, value)
    return value.strip(separator)


def _extract_first_h1(html: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL)
    if not m:
        return ""
    # 去掉 permalink 锚点和段落符号
    text = re.sub(r'<a[^>]*class=["\']anchor["\'][^>]*>.*?</a>', '', m.group(1), flags=re.DOTALL)
    text = re.sub(r"<.*?>", "", text)
    text = text.replace("¶", "").replace("&para;", "").strip()
    return text


def _title_from_path(path: Path) -> str:
    mapping = {
        "agent_generator_spec.md": "Agent 生成器规范",
        "agent_framework_retrospective.md": "Agent 架构四要素与 Prompting 规范",
        "README.md": "dev_agent_system",
        "AGENTS.md": "多 Agent 系统开发过程指导",
    }
    return mapping.get(path.name, path.stem.replace("_", " ").title())


def _subtitle_from_path(path: Path) -> str:
    mapping = {
        "agent_generator_spec.md": "可复现当前多 Agent 系统的生成规范",
        "agent_framework_retrospective.md": "反推版（截至 v0.22.0）",
        "README.md": "基于框架一_软件开发多Agent系统实现的完整多 Agent 开发框架",
    }
    return mapping.get(path.name, "")


def _build_template(title: str, subtitle: str, toc: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
:root {{
  --bg: #f6f8fa;
  --fg: #1f2328;
  --muted: #656d76;
  --card: #ffffff;
  --border: #d1d9e0;
  --accent: #0969da;
  --accent-light: #ddf4ff;
  --code-bg: #f3f4f6;
  --shadow: 0 2px 8px rgba(31, 35, 40, 0.04);
  --radius: 10px;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #0d1117;
    --fg: #c9d1d9;
    --muted: #8b949e;
    --card: #161b22;
    --border: #30363d;
    --accent: #58a6ff;
    --accent-light: #112538;
    --code-bg: #21262d;
    --shadow: 0 2px 8px rgba(0, 0, 0, 0.25);
  }}
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
  background: var(--bg);
  color: var(--fg);
  line-height: 1.7;
}}
header {{
  background: linear-gradient(135deg, var(--accent), #0550ae);
  color: #fff;
  padding: 2.5rem 1.5rem;
  text-align: center;
  box-shadow: var(--shadow);
}}
header h1 {{ margin: 0 0 .5rem; font-size: 1.9rem; }}
header p {{ margin: 0; opacity: .9; font-size: 1rem; }}
.layout {{
  max-width: 1180px;
  margin: 0 auto;
  padding: 1.5rem;
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 1.5rem;
}}
aside.toc {{
  position: sticky;
  top: 1rem;
  align-self: start;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1rem;
  box-shadow: var(--shadow);
  max-height: calc(100vh - 2rem);
  overflow-y: auto;
}}
aside.toc h2 {{ margin: 0 0 .8rem; font-size: 1rem; color: var(--fg); }}
aside.toc ul {{ list-style: none; padding: 0; margin: 0; }}
aside.toc li {{ margin: .35rem 0; }}
aside.toc a {{ text-decoration: none; color: var(--muted); font-size: .88rem; display: block; padding: .15rem 0; }}
aside.toc a:hover {{ color: var(--accent); }}
aside.toc ul ul {{ padding-left: .8rem; }}
main {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 2rem 2.4rem;
  box-shadow: var(--shadow);
  min-width: 0;
}}
main h1 {{ font-size: 1.75rem; margin-top: 0; border-bottom: 2px solid var(--accent); padding-bottom: .5rem; }}
main h2 {{ font-size: 1.4rem; margin-top: 2.2rem; padding-bottom: .35rem; border-bottom: 1px solid var(--border); }}
main h3 {{ font-size: 1.15rem; margin-top: 1.6rem; color: var(--accent); }}
main h4 {{ font-size: 1.05rem; margin-top: 1.3rem; }}
main p {{ margin: .9rem 0; }}
main a {{ color: var(--accent); text-decoration: none; }}
main a:hover {{ text-decoration: underline; }}
main ul, main ol {{ margin: .8rem 0; padding-left: 1.5rem; }}
main li {{ margin: .35rem 0; }}
main blockquote {{
  border-left: 4px solid var(--accent);
  background: var(--accent-light);
  padding: .75rem 1rem;
  margin: 1rem 0;
  border-radius: 0 var(--radius) var(--radius) 0;
}}
table {{
  width: 100%;
  border-collapse: collapse;
  margin: 1rem 0;
  font-size: .92rem;
}}
th, td {{
  border: 1px solid var(--border);
  padding: .65rem .85rem;
  text-align: left;
  vertical-align: top;
}}
th {{ background: var(--bg); font-weight: 600; }}
tr:nth-child(even) {{ background: rgba(0,0,0,.015); }}
@media (prefers-color-scheme: dark) {{ tr:nth-child(even) {{ background: rgba(255,255,255,.025); }} }}
pre {{
  background: var(--code-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1rem;
  overflow-x: auto;
  font-size: .88rem;
}}
code {{
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  background: var(--code-bg);
  padding: .15rem .35rem;
  border-radius: 4px;
  font-size: .9em;
}}
pre code {{ background: transparent; padding: 0; font-size: .88rem; }}
main img {{ max-width: 100%; }}
.anchor {{
  margin-left: .4rem;
  color: var(--muted);
  font-size: .8em;
  text-decoration: none;
  visibility: hidden;
}}
h1:hover .anchor, h2:hover .anchor, h3:hover .anchor {{ visibility: visible; }}
@media (max-width: 860px) {{
  .layout {{ grid-template-columns: 1fr; }}
  aside.toc {{ position: static; max-height: none; margin-bottom: 1rem; }}
  main {{ padding: 1.2rem; }}
}}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  {f"<p>{subtitle}</p>" if subtitle else ""}
</header>
<div class="layout">
<aside class="toc">
  <h2>目录</h2>
{toc}
</aside>
<main>
{body}
</main>
</div>
</body>
</html>
"""


def _convert_citations(body: str, output_dir: Path) -> str:
    """把 <ref_file> / <ref_snippet> 等自闭合 XML 引用转成相对 HTML 链接。"""

    def _href_and_display(raw: str) -> tuple[str, str]:
        raw = raw.replace("\\", "/")
        source = Path(raw)
        if source.is_absolute():
            try:
                rel_to_root = source.relative_to(ROOT)
                display = str(rel_to_root).replace("\\", "/")
            except ValueError:
                display = source.name
        else:
            display = raw
            source = ROOT / raw
        href = os.path.relpath(source, output_dir).replace("\\", "/")
        return href, display

    def _file_link(match: re.Match) -> str:
        href, display = _href_and_display(match.group(1))
        return f'<a class="ref" href="{href}">{display}</a>'

    body = re.sub(r'<ref_file\s+file="([^"]+)"\s*/?>', _file_link, body, flags=re.IGNORECASE)
    body = re.sub(
        r'<ref_snippet\s+file="([^"]+)"\s+lines="([^"]+)"\s*/?>',
        lambda m: f'<a class="ref" href="{_href_and_display(m.group(1))[0]}#L{m.group(2)}">{Path(m.group(1)).name}:{m.group(2)}</a>',
        body,
        flags=re.IGNORECASE,
    )
    return body


def generate(input_path: Path, output_path: Path | None = None) -> Path:
    input_path = input_path.resolve()
    text = input_path.read_text(encoding="utf-8")

    md = markdown.Markdown(
        extensions=[
            FencedCodeExtension(),
            TableExtension(),
            TocExtension(slugify=_slugify, marker="[TOC]", permalink=True, permalink_class="anchor", permalink_title="Permanent link"),
        ],
    )
    body = md.convert(text)
    body = _convert_citations(body, output_dir=(output_path or input_path.with_suffix(".html")).parent.resolve())
    toc = md.toc or ""
    # 去掉 markdown 自动套上的 <div class="toc"> 外壳，只保留内部 <ul>
    toc_inner = re.sub(r"^\s*<div[^>]*class=[\"']toc[\"'][^>]*>", "", toc)
    toc_inner = re.sub(r"</div>\s*$", "", toc_inner)

    title = _extract_first_h1(body) or _title_from_path(input_path)
    subtitle = _subtitle_from_path(input_path)

    if output_path is None:
        output_path = input_path.with_suffix(".html")
    output_path.write_text(
        _build_template(title, subtitle, toc_inner, body),
        encoding="utf-8",
    )
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="生成项目 Markdown 文档的离线 HTML")
    parser.add_argument("input", type=Path, help="输入 Markdown 文件")
    parser.add_argument("--output", "-o", type=Path, default=None, help="输出 HTML 文件（默认与输入同名 .html）")
    args = parser.parse_args()

    out = generate(args.input, args.output)
    print(f"已生成：{out}")


if __name__ == "__main__":
    main()
