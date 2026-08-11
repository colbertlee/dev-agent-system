"""LLM 客户端：兼容 OpenAI 风格 API，未配置时降级为 MOCK，支持流式输出。"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterator, Optional


class LLMClient:
    """轻量级 OpenAI 兼容 LLM 客户端，支持 timeout、重试、流式输出与参数覆盖。"""

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

    def is_mock(self) -> bool:
        return self._client is None

    @staticmethod
    def _mask(text: str) -> str:
        """PII 脱敏：API Key、手机号、密码。"""
        text = re.sub(r"sk-[a-zA-Z0-9]{20,}", "[API_KEY_REDACTED]", text)
        text = re.sub(r"1[3-9]\d{9}", "[PHONE_REDACTED]", text)
        text = re.sub(r"password[:=]\s*\S+", "password=[REDACTED]", text, flags=re.I)
        return text

    def chat(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        system = self._mask(system)
        user = self._mask(user)
        if self._client is None:
            return (
                f"[MOCK {model or self.model}] 未配置 LLM_API_KEY 或 openai 包未安装，\n"
                f"系统摘要：{system[:80]}...\n"
                f"输入摘要：{user[:160]}..."
            )

        try:
            kwargs: Dict[str, Any] = {
                "model": model or self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
            if temperature is not None:
                kwargs["temperature"] = temperature
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            resp = self._client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except Exception as e:  # noqa: BLE001
            return f"[LLM ERROR] {e}"

    async def astream(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ):
        """异步流式生成器，对外 yield token 字符串。"""
        system = self._mask(system)
        user = self._mask(user)
        if self._client is None:
            yield f"[MOCK {model or self.model}] 未配置 LLM_API_KEY"
            return

        try:
            kwargs: Dict[str, Any] = {
                "model": model or self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": True,
            }
            if temperature is not None:
                kwargs["temperature"] = temperature
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens

            stream = self._client.chat.completions.create(**kwargs)
            for chunk in stream:
                delta = (chunk.choices[0].delta.content or "") if chunk.choices else ""
                if delta:
                    yield delta
        except Exception as e:  # noqa: BLE001
            yield f"[LLM ERROR] {e}"

    def stream(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Iterator[str]:
        """同步流式生成器。"""
        system = self._mask(system)
        user = self._mask(user)
        if self._client is None:
            yield f"[MOCK {model or self.model}] 未配置 LLM_API_KEY"
            return

        try:
            kwargs: Dict[str, Any] = {
                "model": model or self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": True,
            }
            if temperature is not None:
                kwargs["temperature"] = temperature
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens

            stream = self._client.chat.completions.create(**kwargs)
            for chunk in stream:
                delta = (chunk.choices[0].delta.content or "") if chunk.choices else ""
                if delta:
                    yield delta
        except Exception as e:  # noqa: BLE001
            yield f"[LLM ERROR] {e}"


class MockLLM:
    """固定返回，用于测试与降级演示。"""

    def __init__(self, response: str = "[MOCK] 收到请求"):
        self.response = response

    def chat(self, system: str, user: str) -> str:
        return self.response

    async def astream(self, system: str, user: str):
        for token in self.response:
            yield token

    def stream(self, system: str, user: str):
        for token in self.response:
            yield token
