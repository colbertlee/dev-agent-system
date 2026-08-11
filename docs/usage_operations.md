# usage_operations.md — 使用与运维手册

## 1. 快速启动

### 1.1 环境要求

- Python 3.9+
- `pip` 或 `venv`
- （可选）Redis 用于 production 记忆后端
- （可选）ChromaDB 用于长期语义记忆
- （可选）Docker / Docker Compose 用于容器化部署

### 1.2 安装依赖

```bash
# 创建虚拟环境（推荐）
python -m venv .venv
# Windows
.\.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

### 1.3 配置环境变量

复制模板并编辑：

```bash
cp .env.example .env
```

必填项：

| 变量 | 说明 | 示例 |
|---|---|---|
| `LLM_API_KEY` | 真实 LLM API Key | `sk-...` |
| `LLM_BASE_URL` | OpenAI 兼容 Base URL | `https://api.deepseek.com` |
| `LLM_MODEL` | 默认模型 | `deepseek-chat` |

可选项：

| 变量 | 说明 | 默认值 |
|---|---|---|
| `WORKSPACE_DIR` | 产物输出目录 | `./workspace` |
| `MEMORY_DIR` | 记忆持久化目录 | `./memory_store` |
| `MEMORY_BACKEND` | `sqlite` / `redis` / `chroma` | `sqlite` |
| `REDIS_URL` | Redis 连接地址 | `redis://localhost:6379/0` |
| `CONTEXT_COMPRESS_THRESHOLD` | 上下文压缩阈值（字符） | `6000` |
| `CONTEXT_WINDOW_LIMIT` | 上下文最大字符数 | `8000` |

## 2. 运行方式

### 2.1 CLI 单次执行

```bash
python -m dev_agent_system.main "开发一个加法模块" --max-iter 2 --output result.json
```

产物将写入 `workspace/<request_id>/`。

### 2.2 启动统一 A2A 网关

```bash
python -m dev_agent_system.server --host 0.0.0.0 --port 8000
```

核心端点：

| 端点 | 方法 | 说明 |
|---|---|---|
| `/health` | GET | 健康检查 |
| `/orchestrate` | POST | 完整 DAG 编排 |
| `/orchestrate/stream` | POST | SSE 流式编排 |
| `/rpc` | POST | JSON-RPC 风格调用 |
| `/{agent}/tasks` | POST | 单个 Agent 任务 |
| `/{agent}/stream` | POST | 单个 Agent SSE 流式 |

调用示例：

```bash
curl -X POST http://localhost:8000/orchestrate \
  -H "Content-Type: application/json" \
  -H "X-Internal-API-Key: dev-internal-key" \
  -d '{"description":"开发一个JWT登录模块","request_id":"req-001","max_iterations":3}'
```

### 2.3 启动独立 A2A 节点

```bash
python -m dev_agent_system.a2a_node --agent coder --port 8082
```

### 2.4 启动 6 节点集群

```bash
python scripts/run_a2a_cluster.py
```

## 3. Docker 部署

```bash
# 构建并启动
docker-compose up --build -d

# 查看日志
docker-compose logs -f dev-agent-system

# 停止
docker-compose down
```

挂载卷说明：

- `./workspace:/app/workspace` — 代码产物
- `./memory_store:/app/memory_store` — SQLite 记忆
- `./.env:/app/.env` — 环境变量

## 4. 运维检查清单

### 4.1 每日检查

- [ ] `docker-compose ps` 或进程是否存活
- [ ] 磁盘空间：`workspace/` 与 `memory_store/` 是否持续增长
- [ ] `LLM_API_KEY` 是否即将过期

### 4.2 每周检查

- [ ] 运行 `python -m pytest tests -q` 验证核心功能
- [ ] 检查 `config/model.yaml` 是否存在 `latest`
- [ ] 审查 `workspace/` 中是否有异常文件或目录穿越
- [ ] 检查日志中 `[LLM ERROR]` 频率

### 4.3 发布前检查

```bash
bash pre-release-check.sh
```

该脚本会执行：

1. `python -m pytest tests -q`
2. Python 语法检查
3. `config/model.yaml` 无 `latest`
4. `CHANGELOG.md` 非空

## 5. 监控与告警

### 5.1 结构化日志

所有 Agent 返回结构化 JSON，建议将 `orchestrator_result.json` 与运行日志收集到 ELK / Loki。

### 5.2 关键指标

| 指标 | 采集方式 | 告警阈值建议 |
|---|---|---|
| `iteration` | 结果 JSON | `>= max_iterations` 且未通过 |
| `tester.passed` / `failed` | 结果 JSON | `failed > 0` |
| `reviewer.passed` | 结果 JSON | `false` 连续出现 |
| LLM 响应时间 | 日志 | 超过 30s |
| 沙箱越界尝试 | 工具返回 `error` | 任何一次 |

### 5.3 健康检查

```bash
curl http://localhost:8000/health
```

## 6. 备份与恢复

### 6.1 备份内容

| 路径 | 说明 |
|---|---|
| `workspace/` | 生成的代码、测试、文档 |
| `memory_store/` | SQLite / ChromaDB 记忆 |
| `config/` | 模型与 MCP 配置 |
| `.env` | 环境变量（**不含** API Key 时应加密或排除） |

### 6.2 自动备份脚本示例

```bash
#!/bin/bash
# backup.sh
DEST="backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DEST"
cp -r workspace memory_store config "$DEST/"
# 不要明文备份 .env
```

## 7. 安全运维

- **API Key 管理**：使用环境变量或 secrets manager，禁止提交到 Git。
- **网络隔离**：生产环境限制 `server.py` / `a2a_node.py` 监听地址，避免 0.0.0.0 直接暴露公网。
- **沙箱审计**：定期审查 `workspace/` 与 `memory_store/` 权限，确保服务用户无法写入非预期目录。
- **模型版本锁定**：`config/model.yaml` 必须指定具体版本号，禁止 `latest`。

## 8. 故障排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| `未配置 LLM_API_KEY` | 未设置 API Key | 填写 `.env` 或环境变量 |
| `路径越界` | Agent 试图写入 workspace 之外 | 检查 Prompt 是否生成 `../` 路径 |
| `pytest` 无测试 | Tester 未生成 `test_*.py` | 检查 Coder 是否生成可识别代码块 |
| `Recursion limit reached` | LangGraph 默认递归限制 | 已在 `config` 中设置 `recursion_limit` |
| `无法解析 JSON 审查报告` | Reviewer 输出格式异常 | 检查 Prompt 与 LLM 输出 |
| Redis/ChromaDB 不可用 | 依赖未安装或服务未启动 | 自动降级到 SQLite，查看日志 |

## 9. 升级流程

```bash
# 拉取最新代码
git pull origin main

# 安装新依赖
pip install -r requirements.txt

# 运行测试
python -m pytest tests -q

# 若有数据库 schema 变更，按 CHANGELOG 说明迁移
# 重启服务
```

## 10. 获取帮助

- 项目文档：`README.md`、`ARCHITECTURE.md`、`CONTRIBUTE.md`
- 开发规则：`AGENTS.md`
- 工具规范：`docs/tools_spec.md`
- Prompt 管理：`docs/prompt_templates.md`
- Issue 与支持：<https://github.com/colbertlee/dev-agent-system/issues>
