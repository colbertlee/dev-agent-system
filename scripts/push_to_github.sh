#!/usr/bin/env bash
# push_to_github.sh — 检查 → 提交 → 推送到 GitHub，并可选创建 PR
# 用法：
#   bash scripts/push_to_github.sh "本次提交说明"

set -e

MESSAGE="${1:-chore: update from multi-agent system}"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "❌ 当前目录不是 Git 仓库"
    exit 1
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD)

echo "==================== GitHub 推送检查 ===================="

# 分支规范检查
case "$BRANCH" in
    main|dev|feature/*|hotfix/*)
        echo "✅ 当前分支 $BRANCH 符合命名规范"
        ;;
    *)
        echo "❌ 当前分支 $BRANCH 不符合规范（main / dev / feature/* / hotfix/*）"
        exit 1
        ;;
esac

# 运行测试
echo "[1/4] 运行 pytest..."
python -m pytest tests -q || { echo "❌ pytest 未通过"; exit 1; }
echo "✅ pytest 通过"

# 提交并推送
echo "[2/4] 添加并提交..."
git add -A
git commit -m "$MESSAGE" || { echo "⚠️ 无变更需要提交"; exit 0; }

echo "[3/4] 推送到 origin $BRANCH..."
git push origin "$BRANCH"

# 自动创建 PR（仅在 feature/* 或 hotfix/* 分支且 gh 已安装）
echo "[4/4] 检查是否需要创建 PR..."
if [[ "$BRANCH" == feature/* || "$BRANCH" == hotfix/* ]]; then
    if command -v gh >/dev/null 2>&1; then
        gh pr create --title "$MESSAGE" --body "$(cat <<'EOF'
## Summary
- 由多 Agent 系统 `scripts/push_to_github.sh` 自动生成
- 已通过本地 pytest 检查

## Test plan
- [x] `python -m pytest tests -q` 通过

Generated with Devin
EOF
)" || echo "⚠️ PR 创建失败或已存在"
    else
        echo "⚠️ 未安装 GitHub CLI (gh)，跳过 PR 自动创建"
    fi
fi

echo "==================== 推送完成 ===================="
