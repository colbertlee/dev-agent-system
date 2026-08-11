"""模型路由：按 Agent 与提示复杂度选择模型和参数。"""
from __future__ import annotations

import os
from typing import Any, Dict, Tuple

from dev_agent_system.config import Settings


class ModelRouter:
    """根据 config/model.yaml 和运行时提示长度选择最合适的模型。"""

    def __init__(self) -> None:
        self._config = Settings.model_config()

    def resolve(self, agent_name: str, prompt: str = "") -> Tuple[str, Dict[str, Any]]:
        """返回 (model_name, generation_kwargs)。"""
        cfg = self._config.get(agent_name, {})
        model = cfg.get("model", os.getenv("LLM_MODEL", "deepseek-chat"))
        temperature = cfg.get("temperature", 0.2)
        max_tokens = cfg.get("max_tokens")

        # 自适应路由：提示过长或明确标记复杂时切到更大模型
        if cfg.get("adaptive"):
            threshold = cfg.get("long_prompt_threshold", 4000)
            complexity = cfg.get("default_complexity", "medium")
            if len(prompt) > threshold or complexity == "high":
                model = cfg.get("large_model", model)
                temperature = cfg.get("large_temperature", temperature)
            elif len(prompt) < 500:
                model = cfg.get("fast_model", model)
                temperature = cfg.get("fast_temperature", temperature)

        kwargs: Dict[str, Any] = {"temperature": temperature}
        if max_tokens is not None:
            kwargs["max_tokens"] = int(max_tokens)
        return model, kwargs

    def agent_temperature(self, agent_name: str) -> float:
        return self._config.get(agent_name, {}).get("temperature", 0.2)
