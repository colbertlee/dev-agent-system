"""LLM Provider 抽象与实现：OpenAI、DeepSeek、Ollama（本地模型）、Mock。"""
from __future__ import annotations

import abc
import json
import re
from typing import Any, AsyncIterator, Callable, Dict, Iterator, Optional, Union

import httpx

try:
    import openai as _openai
except ImportError:  # pragma: no cover
    _openai = None


class LLMProvider(abc.ABC):
    """LLM 调用抽象层，支持同步/异步流式与非流式。"""

    def __init__(self, model: str) -> None:
        self.model = model

    @abc.abstractmethod
    def chat(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        """同步非流式对话，返回完整回复字符串。"""
        raise NotImplementedError

    @abc.abstractmethod
    def stream(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> Iterator[str]:
        """同步流式生成器，逐 token 输出。"""
        raise NotImplementedError

    @abc.abstractmethod
    async def astream(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> AsyncIterator[str]:
        """异步流式生成器，逐 token 输出。"""
        raise NotImplementedError

    @staticmethod
    def _messages(system: str, user: str) -> List[Dict[str, str]]:
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]


class OpenAIProvider(LLMProvider):
    """OpenAI 兼容 API Provider，支持 DeepSeek 等 OpenAI 格式服务。"""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 2,
        client: Any = None,
        async_client: Any = None,
    ) -> None:
        if _openai is None:
            raise ImportError("openai package is required for OpenAIProvider")
        super().__init__(model)
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = client or _openai.OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )
        self._async_client = async_client or _openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )

    def _build_kwargs(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        json_mode: bool = False,
    ) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "model": model or self.model,
            "messages": self._messages(system, user),
            "stream": stream,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if json_mode and not stream:
            kwargs["response_format"] = {"type": "json_object"}
        return kwargs

    def chat(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        kwargs = self._build_kwargs(system, user, model=model, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode)
        resp = self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    def stream(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> Iterator[str]:
        kwargs = self._build_kwargs(system, user, model=model, temperature=temperature, max_tokens=max_tokens, stream=True, json_mode=json_mode)
        for chunk in self._client.chat.completions.create(**kwargs):
            delta = (chunk.choices[0].delta.content or "") if chunk.choices else ""
            if delta:
                yield delta

    async def astream(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> AsyncIterator[str]:
        kwargs = self._build_kwargs(system, user, model=model, temperature=temperature, max_tokens=max_tokens, stream=True, json_mode=json_mode)
        response = await self._async_client.chat.completions.create(**kwargs)
        async for chunk in response:
            delta = (chunk.choices[0].delta.content or "") if chunk.choices else ""
            if delta:
                yield delta


class OllamaProvider(LLMProvider):
    """Ollama 本地模型 Provider，通过 /api/chat 调用。"""

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        timeout: float = 30.0,
        client: Optional[httpx.Client] = None,
        async_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        super().__init__(model)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = client
        self._async_client = async_client

    def _build_body(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        json_mode: bool = False,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "model": model or self.model,
            "messages": self._messages(system, user),
            "stream": stream,
        }
        if json_mode:
            body["format"] = "json"
        options: Dict[str, Any] = {}
        if temperature is not None:
            options["temperature"] = temperature
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        if options:
            body["options"] = options
        return body

    def chat(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        body = self._build_body(system, user, model=model, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode)
        url = f"{self.base_url}/api/chat"
        client = self._client or httpx.Client()
        try:
            resp = client.post(url, json=body, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "")
        finally:
            if self._client is None:
                client.close()

    def _iter_lines(self, response: httpx.Response) -> Iterator[str]:
        for line in response.iter_lines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if data.get("done"):
                break
            content = (data.get("message") or {}).get("content", "")
            if content:
                yield content

    def stream(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> Iterator[str]:
        body = self._build_body(system, user, model=model, temperature=temperature, max_tokens=max_tokens, stream=True, json_mode=json_mode)
        url = f"{self.base_url}/api/chat"
        client = self._client or httpx.Client()
        try:
            with client.stream("POST", url, json=body, timeout=self.timeout) as resp:
                resp.raise_for_status()
                yield from self._iter_lines(resp)
        finally:
            if self._client is None:
                client.close()

    async def astream(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> AsyncIterator[str]:
        body = self._build_body(system, user, model=model, temperature=temperature, max_tokens=max_tokens, stream=True, json_mode=json_mode)
        url = f"{self.base_url}/api/chat"
        client = self._async_client or httpx.AsyncClient()
        try:
            async with client.stream("POST", url, json=body, timeout=self.timeout) as resp:
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if data.get("done"):
                        break
                    content = (data.get("message") or {}).get("content", "")
                    if content:
                        yield content
        finally:
            if self._async_client is None:
                await client.aclose()


class MockProvider(LLMProvider):
    """Mock Provider，用于测试与未配置真实密钥时的降级。"""

    def __init__(
        self,
        model: str = "mock",
        response: Optional[Union[str, Callable[[str, str, str], str]]] = None,
    ) -> None:
        super().__init__(model)
        self.response = response

    def _render(self, system: str, user: str, model: str) -> str:
        if callable(self.response):
            return self.response(system, user, model)
        if isinstance(self.response, str):
            return self.response
        return (
            f"[MOCK {model}] 未配置 LLM_API_KEY 或未安装 openai 包，\n"
            f"系统摘要：{system[:80]}...\n"
            f"输入摘要：{user[:160]}..."
        )

    def _split(self, text: str) -> Iterator[str]:
        # 保留空格，按单词/标点拆分，模拟 token 级流式
        parts = re.split(r"(\s+)", text)
        for part in parts:
            if part:
                yield part

    def chat(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        return self._render(system, user, model or self.model)

    def stream(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> Iterator[str]:
        text = self._render(system, user, model or self.model)
        yield from self._split(text)

    async def astream(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> AsyncIterator[str]:
        text = self._render(system, user, model or self.model)
        for token in self._split(text):
            yield token
