#!/usr/bin/env bash
# release.sh — 发布流程：检查 → 升级版本 → 提交 → 打 tag
# 用法：
#   bash scripts/release.sh patch
#   bash scripts/release.sh minor
#   bash scripts/release.sh major

set -u

PART=${1:-patch}

if [ "$PART" != "patch" ] && [ "$PART" != "minor" ] && [ "$PART" != "major" ]; then
    echo "用法: bash scripts/release.sh {patch|minor|major}"
    exit 1
fi

echo "==================== 发布流程 ($PART) ===================="

echo "[1/3] 运行预发布检查..."
bash pre-release-check.sh || { echo "预发布检查未通过"; exit 1; }

echo "[2/3] 检查 Git SOP..."
bash scripts/git-sop-check.sh || { echo "Git SOP 检查未通过"; exit 1; }

echo "[3/3] 升级版本号..."
python scripts/bump-version.py "$PART"

NEW_VERSION=$(grep -oE '__version__\s*=\s*"[0-9]+\.[0-9]+\.[0-9]+"' dev_agent_system/__init__.py | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')

echo ""
echo "版本已升级到 v$NEW_VERSION"
echo "请完成以下手动步骤："
echo "  1. 编辑 CHANGELOG.md 填充本次变更内容"
echo "  2. git add -A"
echo "  3. git commit -m \"release: bump version to $NEW_VERSION\""
echo "  4. git tag -a v$NEW_VERSION -m \"release v$NEW_VERSION\""
echo "  5. git push origin main --tags"
echo ""
echo "如需备份 ChromaDB 和 prompts，请执行 pre-release-check.sh 中的备份步骤。"
