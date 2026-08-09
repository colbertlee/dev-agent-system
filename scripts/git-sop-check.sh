#!/usr/bin/env bash
# git-sop-check.sh — 检查 Git 分支是否符合版本管理 SOP
# 用于 pre-release-check.sh 中或单独运行

set -u

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'
PASS="${GREEN}✅${NC}"
FAIL="${RED}❌${NC}"
STATUS=0

print_ok() { echo -e "${PASS} $1"; }
print_ko() { echo -e "${FAIL} $1"; STATUS=1; }

echo "==================== Git SOP 检查 ===================="

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    print_ko "当前目录不是 Git 仓库"
    exit 1
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD)

case "$BRANCH" in
    main)
        print_ok "当前分支为 main（生产就绪分支）"
        ;;
    dev)
        print_ok "当前分支为 dev（日常开发分支）"
        ;;
    feature/*|hotfix/*)
        print_ok "当前分支 $BRANCH 符合命名规范"
        ;;
    *)
        print_ko "当前分支 $BRANCH 不符合规范，应为 main / dev / feature/* / hotfix/*"
        ;;
esac

if git diff --quiet HEAD; then
    print_ok "工作区干净，无未提交变更"
else
    print_ko "工作区存在未提交变更，请先提交或暂存"
fi

if [ -f "CHANGELOG.md" ]; then
    print_ok "CHANGELOG.md 存在"
else
    print_ko "CHANGELOG.md 不存在"
fi

if [ -f "pre-release-check.sh" ]; then
    print_ok "pre-release-check.sh 存在"
else
    print_ko "pre-release-check.sh 不存在"
fi

echo "===================================================="
if [ "$STATUS" -eq 0 ]; then
    echo -e "${GREEN}Git SOP 检查通过${NC}"
else
    echo -e "${RED}Git SOP 检查未通过${NC}"
fi
exit "$STATUS"
