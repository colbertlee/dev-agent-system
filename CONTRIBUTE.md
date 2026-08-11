# CONTRIBUTE.md

## 1. 开发哲学

- **先写测试，再写实现**：所有新功能应包含单元/集成测试，并确保 `pytest` 通过。
- **文档先行**：修改 Prompt、模型版本、Agent Card、工具 Schema 前，先更新对应文档。
- **可降级优先**：新增依赖应为可选，未安装时系统自动降级到本地实现。
- **安全第一**：不得绕过 `ToolSandbox` 直接执行 LLM 生成的命令或文件操作。

## 2. 代码规范

### 2.1 Python 风格

- 使用 **4 空格缩进**，最大行宽 **120 字符**（项目未强制，但建议）。
- 类型注解：`from __future__ import annotations`，使用 `Optional`、`Dict`、`List` 等兼容 Python 3.9。
- 异常处理：捕获具体异常；若必须 `except Exception`，加 `# noqa: BLE001` 并记录原因。
- 导入顺序：标准库 → 第三方 → 项目内部。

### 2.2 禁止事项

- 禁止在仓库中提交 API Key、密码、`.env` 真实值。
- 禁止引入未经审计的最新版本依赖；新依赖版本应发布至少 7 天。
- 禁止直接修改 `main` 分支；所有变更通过 `dev` 或 `feature/*` 分支合并。
- 禁止 `rm -rf`、`| sh` 等危险命令绕过沙箱执行。

### 2.3 单元测试

```bash
python -m pytest tests -q
```

- 新增 Agent：在 `tests/` 中补充输入输出格式测试。
- 新增工具：在 `tests/` 中补充权限、路径隔离、黑名单测试。
- 修改编排器：运行完整 DAG 集成测试 `test_flow.py`。

## 3. Git 提交格式

采用 [Conventional Commits](https://www.conventionalcommits.org/)：

```
<type>(<scope>): <short description>

<body>

Refs: #issue-id
```

### 3.1 type 说明

| type | 用途 |
|---|---|
| `feat` | 新功能、新 Agent、新路由 |
| `fix` | Bug 修复 |
| `docs` | 仅文档变更 |
| `style` | 代码格式、无逻辑变更 |
| `refactor` | 重构、性能优化 |
| `test` | 测试补充或修复 |
| `chore` | 构建、依赖、脚本更新 |
| `model` | Prompt、模型版本、Agent Card 变更 |

### 3.2 scope 建议

- `agent`: Agent 行为
- `orchestrator`: LangGraph 编排
- `mcp`: 工具沙箱
- `memory`: 记忆层
- `llm`: LLM 客户端 / 路由
- `server`: A2A 网关
- `docs`: 文档

### 3.3 示例

```
feat(agent): CoderAgent 写入代码文件并返回结构化报告

- 解析 LLM 输出的 ``` 代码块
- 通过 ToolSandbox.write_file 写入 workspace
- 返回 files / status / test_result / note

Refs: #12
```

## 4. 分支策略

采用 Trunk-Based 简化版：

```
main
  └── dev
       ├── feature/xxx
       └── hotfix/xxx
```

| 分支 | 规则 |
|---|---|
| `main` | 生产就绪版本，每次合并对应一次 Release，必须通过全部测试与 `pre-release-check.sh` |
| `dev` | 日常开发分支，功能完成后合并到 `main` |
| `feature/*` | 从 `dev` 切出，完成后合并回 `dev` |
| `hotfix/*` | 从 `main` 切出，修复后合并到 `main` 并同步回 `dev` |

## 5. 提交与推送脚本

```bash
# 预提交检查
bash pre-release-check.sh

# 一键提交并推送（Linux/macOS/Git Bash）
bash scripts/push_to_github.sh "feat(agent): 新增 xxx"

# Windows PowerShell
.\scripts\push_to_github.ps1 -Message "feat(agent): 新增 xxx"
```

`push_to_github.sh` / `.ps1` 会自动执行：

1. `python -m pytest tests -q`
2. `bash scripts/git-sop-check.sh` 分支名检查
3. `git add -A && git commit`
4. `git push origin <当前分支>`
5. 在 `feature/*` / `hotfix/*` 分支尝试 `gh pr create`

## 6. 版本发布流程

```bash
# 升级版本：patch / minor / major
python scripts/bump-version.py minor

# 手动完善 CHANGELOG.md 后，提交并打 tag
bash scripts/release.sh minor
```

`bump-version.py` 会自动：

- 更新 `dev_agent_system/__init__.py` 的 `__version__`
- 在 `CHANGELOG.md` 生成新版本的空模板

发布前必须完成：

- [ ] `python -m pytest tests -q` 全绿
- [ ] `config/model.yaml` 无 `latest`
- [ ] `CHANGELOG.md` 已填充本次变更
- [ ] `AGENTS.md` / `README.md` / `ARCHITECTURE.md` 已同步

## 7. Pull Request 模板

合并前请在 PR 描述中填写：

```markdown
## 变更摘要
- 新增/修改/删除了什么
- 为什么需要这次变更

## 测试
- [ ] `python -m pytest tests -q` 通过
- [ ] 新增/更新了相关测试
- [ ] 手动验证 CLI / API / A2A 节点

## 文档
- [ ] CHANGELOG.md 已更新
- [ ] AGENTS.md / README.md 已同步（如适用）
- [ ] Prompt / Agent Card / 模型版本已版本化（如适用）
```

## 8. 评审 checklist

- 代码是否遵循本项目安全规则？
- 新增依赖是否已锁定版本并在 `requirements.txt` 中说明？
- 是否有降级路径？（LLM/Memory/MCP 等）
- 是否影响 A2A 协议兼容性？
- 是否更新了测试与文档？
