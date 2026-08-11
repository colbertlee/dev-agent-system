# tools_spec.md

## 1. 概述

`dev_agent_system` 的 Agent 通过 **MCP 风格工具**与外部环境交互。所有工具由 `ToolSandbox` 统一注册、校验、执行，并提供白名单、黑名单、路径隔离与超时保护。

工具统一通过 `MCPToolRegistry` 调用：

```python
from dev_agent_system.mcp import MCPToolRegistry

tools = MCPToolRegistry()
result = tools.call("write_file", path="main.py", content="...", base_dir="workspace/xxx")
# 异步上下文使用 ainvoke
# result = await tools.ainvoke("write_file", ...)
```

## 2. 工具清单

| 工具名 | 描述 | 同步/异步 | 风险等级 |
|---|---|---|---|
| `read_file` | 读取指定路径文件内容 | 同步 | 低 |
| `write_file` | 写入文件到指定 base_dir | 异步 | 中 |
| `run_command` | 在 base_dir 下执行白名单命令 | 同步 | 高 |

## 3. 通用字段

所有工具返回统一结构：

```json
{
  "success": true,
  "error": "",
  "...": ""
}
```

- `success`: 是否成功执行
- `error`: 失败原因
- 其余字段为工具特定输出

## 4. read_file

### 4.1 描述

读取 `base_dir` 下的文本文件，拒绝目录穿越。

### 4.2 JSON Schema

```json
{
  "name": "read_file",
  "description": "读取 base_dir 下的文本文件",
  "input": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "相对 base_dir 的文件路径"
      },
      "base_dir": {
        "type": "string",
        "description": "工作目录，默认 ToolSandbox.WORK_DIR"
      }
    },
    "required": ["path"]
  },
  "output": {
    "type": "object",
    "properties": {
      "success": { "type": "boolean" },
      "error": { "type": "string" },
      "content": { "type": "string" }
    },
    "required": ["success"]
  }
}
```

### 4.3 示例

```json
// 输入
{
  "path": "main.py",
  "base_dir": "workspace/abc-123"
}

// 成功输出
{
  "success": true,
  "content": "def add(a, b):\n    return a + b\n"
}

// 失败输出
{
  "success": false,
  "error": "路径越界"
}
```

## 5. write_file

### 5.1 描述

将 `content` 写入 `base_dir` 下的 `path`，自动创建父目录，拒绝目录穿越。

### 5.2 JSON Schema

```json
{
  "name": "write_file",
  "description": "写入文件到 base_dir，自动创建父目录",
  "input": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "相对 base_dir 的文件路径"
      },
      "content": {
        "type": "string",
        "description": "文件内容"
      },
      "base_dir": {
        "type": "string",
        "description": "工作目录，默认 ToolSandbox.WORK_DIR"
      }
    },
    "required": ["path", "content"]
  },
  "output": {
    "type": "object",
    "properties": {
      "success": { "type": "boolean" },
      "error": { "type": "string" },
      "path": { "type": "string" }
    },
    "required": ["success"]
  }
}
```

### 5.3 示例

```json
// 输入
{
  "path": "main.py",
  "content": "def main():\n    print('hello')\n",
  "base_dir": "workspace/abc-123"
}

// 输出
{
  "success": true,
  "path": "C:/.../workspace/abc-123/main.py"
}
```

## 6. run_command

### 6.1 描述

在 `base_dir` 下执行命令，仅允许白名单前缀，黑名单正则拦截。

### 6.2 白名单前缀

```python
ALLOWED_PREFIXES = (
    "python",
    "pytest",
    "git",
    "ls",
    "cat",
    "echo",
    "docker build",
)
```

### 6.3 黑名单正则

```python
BLACKLIST = re.compile(
    r"(rm\s+-rf\s*/|>\s*/dev/null\s*;|&&\s*rm\b|\|\s*sh\b|curl\s+.*\|.*sh|\|\s*bash|wget\s+-O-)",
    re.I,
)
```

### 6.4 JSON Schema

```json
{
  "name": "run_command",
  "description": "执行白名单命令并返回输出",
  "input": {
    "type": "object",
    "properties": {
      "command": {
        "type": "string",
        "description": "待执行命令"
      },
      "timeout": {
        "type": "integer",
        "description": "最大执行秒数",
        "default": 5
      },
      "base_dir": {
        "type": "string",
        "description": "执行目录，默认 ToolSandbox.WORK_DIR"
      }
    },
    "required": ["command"]
  },
  "output": {
    "type": "object",
    "properties": {
      "success": { "type": "boolean" },
      "error": { "type": "string" },
      "returncode": { "type": "integer" },
      "stdout": { "type": "string" },
      "stderr": { "type": "string" }
    },
    "required": ["success"]
  }
}
```

### 6.5 示例

```json
// 输入
{
  "command": "pytest -q",
  "base_dir": "workspace/abc-123",
  "timeout": 15
}

// 输出
{
  "success": true,
  "returncode": 0,
  "stdout": ".\n1 passed in 0.01s",
  "stderr": ""
}
```

## 7. 错误码约定

| 错误信息 | 含义 |
|---|---|
| `路径越界` | 试图访问 `base_dir` 之外 |
| `文件不存在` | `read_file` 目标不存在 |
| `空命令` | `run_command` 输入为空 |
| `命令命中黑名单` | 命中危险模式正则 |
| `仅允许以 (...) 开头的命令` | 命令不在白名单前缀 |
| `命令执行超过 N 秒` | 命令超时 |
| `未知工具: xxx` | `MCPToolRegistry` 未注册该工具 |
| `工具 xxx 是异步的...` | 在同步上下文调用了异步工具 |

## 8. 扩展方式

```python
# 在运行时注册新工具
tools = MCPToolRegistry()
tools.register("my_tool", my_tool_function)

# 返回值必须包含 {"success": bool, "error": str, ...}
```

新增工具后，请同步更新：

- `docs/tools_spec.md`
- `tests/` 中补充边界与安全测试
- `AGENTS.md` 第 4 节“如何新增一个 Agent/工具”
