"""语义化版本自动升级脚本。

用法：
    python scripts/bump-version.py patch
    python scripts/bump-version.py minor
    python scripts/bump-version.py major

作用：
1. 读取 dev_agent_system/__init__.py 中的 __version__
2. 按 Semantic Versioning 递增版本号
3. 在 CHANGELOG.md 中插入新的 ## [x.y.z] 空模板
4. 打印新版本
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT_FILE = ROOT / "dev_agent_system" / "__init__.py"
CHANGELOG_FILE = ROOT / "CHANGELOG.md"


def read_version() -> str:
    text = INIT_FILE.read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*["\']([0-9]+\.[0-9]+\.[0-9]+)["\']', text)
    if not m:
        raise RuntimeError(f"未在 {INIT_FILE} 找到 __version__")
    return m.group(1)


def bump(current: str, part: str) -> str:
    major, minor, patch = map(int, current.split("."))
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"未知版本部分: {part}")


def write_version(new_version: str) -> None:
    text = INIT_FILE.read_text(encoding="utf-8")
    new_text = re.sub(
        r'(__version__\s*=\s*["\'])[0-9]+\.[0-9]+\.[0-9]+(["\'])',
        rf"\g<1>{new_version}\g<2>",
        text,
    )
    INIT_FILE.write_text(new_text, encoding="utf-8")


def insert_changelog_section(new_version: str) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    new_section = f"\n## [{new_version}] - {today}\n\n### Added\n\n### Changed\n\n### Fixed\n\n### Security\n\n### Model Changes\n"
    text = CHANGELOG_FILE.read_text(encoding="utf-8")
    # 在第一个 ## [ 之前插入
    match = re.search(r"\n## \[", text)
    if match:
        idx = match.start()
        new_text = text[:idx] + new_section + text[idx:]
    else:
        new_text = text + new_section
    CHANGELOG_FILE.write_text(new_text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="语义化版本升级")
    parser.add_argument("part", choices=["major", "minor", "patch"], help="升级部分")
    args = parser.parse_args()

    current = read_version()
    new = bump(current, args.part)
    write_version(new)
    insert_changelog_section(new)
    print(f"版本已从 {current} 升级到 {new}")
    print(f"已更新：{INIT_FILE}\n已更新：{CHANGELOG_FILE}")
    print("请继续编辑 CHANGELOG.md 填充本次变更内容，然后提交并打 tag。")


if __name__ == "__main__":
    main()
