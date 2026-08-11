"""LLM 客户端：自动选择 OpenAI / DeepSeek / Ollama / Mock Provider，支持流式输出。"""
from __future__ import annotations

import os
import re
from typing import Any, AsyncIterator, Iterator, Optional, Union

from dev_agent_system.config import Settings
from dev_agent_system.llm_providers import LLMProvider, MockProvider, OllamaProvider, OpenAIProvider


def _openai_available() -> bool:
    try:
        import openai  # noqa: F401
        return True
    except ImportError:
        return False


class LLMClient:
    """轻量级 LLM 客户端，根据环境变量自动选择 Provider。"""

    def __init__(
        self,
        model: Optional[str] = None,
        provider: Optional[Union[str, LLMProvider]] = None,
    ):
        self.model = model or Settings.llm_model()
        self.provider = self._resolve_provider(provider)

    def _resolve_provider(self, provider: Optional[Union[str, LLMProvider]]) -> LLMProvider:
        if isinstance(provider, LLMProvider):
            return provider

        provider_name = (provider or Settings.llm_provider() or "").lower()
        if provider_name == "openai" or provider_name == "deepseek":
            return self._openai_provider()
        if provider_name == "ollama":
            return self._ollama_provider()
        if provider_name == "mock":
            return MockProvider(model=self.model)

        # 自动推断：未配置真实 LLM 时降级为 MOCK
        if self.model and self.model.startswith("ollama/"):
            return self._ollama_provider(model=self.model.split("/", 1)[1])
        if Settings.llm_api_key() and _openai_available():
            return self._openai_provider()

        return MockProvider(model=self.model)

    def _openai_provider(self, model: Optional[str] = None) -> OpenAIProvider:
        return OpenAIProvider(
            model=model or self.model,
            api_key=Settings.llm_api_key(),
            base_url=Settings.llm_base_url() or None,
            timeout=Settings.llm_timeout(),
            max_retries=Settings.llm_max_retries(),
        )

    def _ollama_provider(self, model: Optional[str] = None) -> OllamaProvider:
        return OllamaProvider(
            model=model or self.model,
            base_url=Settings.ollama_url(),
            timeout=Settings.llm_timeout(),
        )

    def is_mock(self) -> bool:
        return isinstance(self.provider, MockProvider)

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
        try:
            return self.provider.chat(
                system,
                user,
                model=model or self.model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:  # noqa: BLE001
            return f"[LLM ERROR] {e}"

    def stream(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Iterator[str]:
        system = self._mask(system)
        user = self._mask(user)
        try:
            yield from self.provider.stream(
                system,
                user,
                model=model or self.model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:  # noqa: BLE001
            yield f"[LLM ERROR] {e}"

    async def astream(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        system = self._mask(system)
        user = self._mask(user)
        try:
            async for token in self.provider.astream(
                system,
                user,
                model=model or self.model,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                if token:
                    yield token
        except Exception as e:  # noqa: BLE001
            yield f"[LLM ERROR] {e}"


class MockLLM:
    """固定返回，用于测试与降级演示（兼容旧接口）。"""

    def __init__(self, response: str = "[MOCK] 收到请求"):
        self.response = response
        self._provider = MockProvider(response=response)

    def chat(self, system: str, user: str) -> str:
        return self._provider.chat(system, user)

    async def astream(self, system: str, user: str):
        async for token in self._provider.astream(system, user):
            yield token

    def stream(self, system: str, user: str):
        yield from self._provider.stream(system, user)
