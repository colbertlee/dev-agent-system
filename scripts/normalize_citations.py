"""把 Markdown 文档中 <ref_file> / <ref_snippet> 的绝对路径统一改为项目相对路径。

用法：
    python scripts/normalize_citations.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def normalize_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    def _replace(match: re.Match) -> str:
        raw = match.group(1)
        # 兼容 Windows 反斜杠与正斜杠
        raw = raw.replace("\\", "/")
        source = Path(raw)
        if source.is_absolute():
            try:
                rel = source.relative_to(ROOT)
                return match.group(0).replace(match.group(1), str(rel).replace("\\", "/"))
            except ValueError:
                pass
        # 已经是相对路径：统一正斜杠
        return match.group(0).replace(match.group(1), raw)

    text = re.sub(r'<ref_file\s+file="([^"]+)"\s*/?>', _replace, text, flags=re.IGNORECASE)
    text = re.sub(r'<ref_snippet\s+file="([^"]+)"\s+lines="([^"]+)"\s*/?>', _replace, text, flags=re.IGNORECASE)

    path.write_text(text, encoding="utf-8")
    print(f"已规范化：{path}")


def main() -> None:
    docs_dir = ROOT / "docs"
    for md in [ROOT / "README.md", ROOT / "AGENTS.md", ROOT / "ARCHITECTURE.md", ROOT / "CONTRIBUTE.md"] + list(docs_dir.glob("*.md")):
        if "normalize_citations" in md.name:
            continue
        normalize_file(md)


if __name__ == "__main__":
    main()
