#!/usr/bin/env bash
# pre-release-check.sh — 框架一预发布检查脚本
# 运行步骤：pytest → 检查 model.yaml 无 latest → CHANGELOG 已更新 → 备份 ChromaDB
# 每步输出绿色 ✅ 或红色 ❌

set -u

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'
PASS="${GREEN}✅${NC}"
FAIL="${RED}❌${NC}"

STATUS=0

print_ok() { echo -e "${PASS} $1"; }
print_ko() { echo -e "${FAIL} $1"; STATUS=1; }

echo "==================== 预发布检查 ===================="

# 1. 运行 pytest（优先 python -m pytest，兼容虚拟环境）
if python -m pytest -q >/dev/null 2>&1; then
    print_ok "pytest 全部通过"
else
    print_ko "pytest 未通过（或无测试可收集 / pytest 未安装）"
fi

# 2. 检查 config/model.yaml 不包含 latest
if [ -f "config/model.yaml" ]; then
    if grep -qiE "\blatest\b" config/model.yaml; then
        print_ko "config/model.yaml 中检测到 'latest'，请锁定到具体版本"
    else
        print_ok "config/model.yaml 未包含 'latest'"
    fi
else
    print_ko "config/model.yaml 不存在（需要创建并锁定模型版本）"
fi

# 3. 检查 CHANGELOG.md 是否包含版本记录
if [ -f "CHANGELOG.md" ] && grep -qE '^##\s*\[[0-9]+\.[0-9]+\.[0-9]+' CHANGELOG.md; then
    print_ok "CHANGELOG.md 已包含版本记录"
else
    print_ko "CHANGELOG.md 不存在或未包含语义化版本记录（如 ## [1.0.0]）"
fi

# 4. 备份 ChromaDB
CHROMA_DIR="chroma_data"
BACKUP_BASE="backups"
BACKUP_DIR="${BACKUP_BASE}/kb_$(date +%Y%m%d_%H%M%S)"
if [ -d "$CHROMA_DIR" ]; then
    mkdir -p "$BACKUP_DIR"
    if cp -r "$CHROMA_DIR" "$BACKUP_DIR/"; then
        print_ok "ChromaDB 已备份到 ${BACKUP_DIR}"
    else
        print_ko "ChromaDB 备份失败"
    fi
else
    print_ko "ChromaDB 数据目录 ${CHROMA_DIR} 不存在，无法备份"
fi

echo "===================================================="
if [ "$STATUS" -eq 0 ]; then
    echo -e "${GREEN}预发布检查全部通过${NC}"
else
    echo -e "${RED}预发布检查存在失败项，请修复后再发布${NC}"
fi
exit "$STATUS"
