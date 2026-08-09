# push_to_github.ps1 — Windows 提交并推送到 GitHub，并可选创建 PR
# 用法：
#   .\scripts\push_to_github.ps1 "本次提交说明"

param(
    [string]$Message = "chore: update from multi-agent system"
)

$ErrorActionPreference = "Stop"

# 检查 Git 仓库
git rev-parse --is-inside-work-tree | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error "当前目录不是 Git 仓库"
}

$BRANCH = (git rev-parse --abbrev-ref HEAD).Trim()

Write-Host "==================== GitHub 推送检查 ===================="

# 分支规范检查
if ($BRANCH -notmatch "^(main|dev|feature/.+|hotfix/.+)$") {
    Write-Error "当前分支 $BRANCH 不符合规范（main / dev / feature/* / hotfix/*）"
}
Write-Host "✅ 当前分支 $BRANCH 符合命名规范"

# 运行测试
Write-Host "[1/4] 运行 pytest..."
python -m pytest tests -q
if ($LASTEXITCODE -ne 0) {
    Write-Error "pytest 未通过"
}
Write-Host "✅ pytest 通过"

# 提交并推送
Write-Host "[2/4] 添加并提交..."
git add -A
git commit -m "$Message"
if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠️ 无变更需要提交"
    exit 0
}

Write-Host "[3/4] 推送到 origin $BRANCH..."
git push origin $BRANCH

# 自动创建 PR（仅在 feature/* 或 hotfix/* 分支且 gh 已安装）
Write-Host "[4/4] 检查是否需要创建 PR..."
if ($BRANCH -match "^(feature|hotfix)/") {
    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if ($gh) {
        $body = @"
## Summary
- 由多 Agent 系统 `scripts/push_to_github.ps1` 自动生成
- 已通过本地 pytest 检查

## Test plan
- [x] `python -m pytest tests -q` 通过

Generated with Devin
"@
        gh pr create --title "$Message" --body "$body" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "⚠️ PR 创建失败或已存在"
        }
    } else {
        Write-Host "⚠️ 未安装 GitHub CLI (gh)，跳过 PR 自动创建"
    }
}

Write-Host "==================== 推送完成 ===================="
