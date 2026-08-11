"""统一配置加载：.env 环境变量 + YAML 配置文件。"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """简单解析 .env 文件并写入 os.environ（仅当变量不存在时）。"""
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def load_yaml(rel_path: str) -> Dict[str, Any]:
    """加载项目根目录下的 YAML 文件。"""
    path = ROOT / rel_path
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# 启动时尝试加载 .env（如果存在）
_load_dotenv(ROOT / ".env")


class Settings:
    """运行期配置集合。"""

    @staticmethod
    def model_config() -> Dict[str, Any]:
        return load_yaml("config/model.yaml")

    @staticmethod
    def mcp_config() -> Dict[str, Any]:
        return load_yaml("config/mcp.yaml")

    @staticmethod
    def agent_model(agent_name: str, fallback: str = "deepseek-chat") -> str:
        """获取指定 Agent 的模型版本，优先 config/model.yaml，其次环境变量，最后 fallback。"""
        cfg = Settings.model_config()
        return cfg.get(agent_name, {}).get("model", os.getenv("LLM_MODEL", fallback))

    @staticmethod
    def mcp_servers() -> Dict[str, Any]:
        return Settings.mcp_config().get("mcp_servers", {})

    @staticmethod
    def llm_api_key() -> str:
        return os.getenv("LLM_API_KEY", "")

    @staticmethod
    def llm_base_url() -> str:
        return os.getenv("LLM_BASE_URL", "")

    @staticmethod
    def llm_timeout() -> int:
        return int(os.getenv("LLM_TIMEOUT", "30"))

    @staticmethod
    def llm_max_retries() -> int:
        return int(os.getenv("LLM_MAX_RETRIES", "2"))

    @staticmethod
    def workspace_dir() -> Path:
        return Path(os.getenv("WORKSPACE_DIR", str(ROOT / "workspace"))).resolve()

    @staticmethod
    def memory_dir() -> Path:
        return Path(os.getenv("MEMORY_DIR", str(ROOT / "memory_store"))).resolve()

    @staticmethod
    def memory_backend() -> str:
        return os.getenv("MEMORY_BACKEND", "sqlite").lower()

    @staticmethod
    def context_compress_threshold() -> int:
        return int(os.getenv("CONTEXT_COMPRESS_THRESHOLD", "6000"))

    @staticmethod
    def context_window_limit() -> int:
        return int(os.getenv("CONTEXT_WINDOW_LIMIT", "8000"))

    @staticmethod
    def sanitize(text: str) -> str:
        """PII 脱敏。"""
        text = re.sub(r"sk-[a-zA-Z0-9]{20,}", "[API_KEY_REDACTED]", text)
        text = re.sub(r"1[3-9]\d{9}", "[PHONE_REDACTED]", text)
        text = re.sub(r"password[:=]\s*\S+", "password=[REDACTED]", text, flags=re.I)
        return text
