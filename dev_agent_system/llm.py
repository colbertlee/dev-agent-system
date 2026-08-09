"""LLM 客户端：兼容 OpenAI 风格 API，未配置时降级为 MOCK。"""
from __future__ import annotations

import os
import re
from typing import Optional


class LLMClient:
    """轻量级 OpenAI 兼容 LLM 客户端，支持 timeout 与重试。"""

    def __init__(self, model: Optional[str] = None):
        self.model = model or os.getenv("LLM_MODEL", "deepseek-chat")
        self._client = None
        self._init_client()

    def _init_client(self) -> None:
        try:
            from openai import OpenAI
        except ImportError:
            return
        api_key = os.getenv("LLM_API_KEY")
        base_url = os.getenv("LLM_BASE_URL")
        if api_key:
            timeout = int(os.getenv("LLM_TIMEOUT", "30"))
            max_retries = int(os.getenv("LLM_MAX_RETRIES", "2"))
            self._client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
                max_retries=max_retries,
            )

    @staticmethod
    def _mask(text: str) -> str:
        """PII 脱敏：API Key、手机号、密码。"""
        text = re.sub(r"sk-[a-zA-Z0-9]{20,}", "[API_KEY_REDACTED]", text)
        text = re.sub(r"1[3-9]\d{9}", "[PHONE_REDACTED]", text)
        text = re.sub(r"password[:=]\s*\S+", "password=[REDACTED]", text, flags=re.I)
        return text

    def chat(self, system: str, user: str) -> str:
        system = self._mask(system)
        user = self._mask(user)
        if self._client is None:
            return (
                f"[MOCK {self.model}] 未配置 LLM_API_KEY 或 openai 包未安装，\n"
                f"系统摘要：{system[:80]}...\n"
                f"输入摘要：{user[:160]}..."
            )
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return resp.choices[0].message.content or ""
        except Exception as e:  # noqa: BLE001
            return f"[LLM ERROR] {e}"


class MockLLM:
    """固定返回，用于测试与降级演示。"""

    def __init__(self, response: str = "[MOCK] 收到请求"):
        self.response = response

    def chat(self, system: str, user: str) -> str:
        return self.response
