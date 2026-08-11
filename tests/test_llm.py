"""LLM 客户端与 Provider 单元测试。"""
from __future__ import annotations

import asyncio

import pytest

from dev_agent_system.llm import LLMClient
from dev_agent_system.llm_providers import MockProvider, OllamaProvider, OpenAIProvider


def test_client_defaults_to_mock_without_credentials(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "")
    client = LLMClient()
    assert client.is_mock()
    output = client.chat("system", "user")
    assert "[MOCK" in output


def test_client_respects_provider_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434")
    client = LLMClient(model="llama3")
    assert isinstance(client.provider, OllamaProvider)
    assert client.provider.model == "llama3"


def test_client_ollama_model_prefix_selects_ollama(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    client = LLMClient(model="ollama/llama3")
    assert isinstance(client.provider, OllamaProvider)
    assert client.provider.model == "llama3"


def test_mock_streaming():
    provider = MockProvider(model="mock", response="hello world")
    client = LLMClient(provider=provider)
    tokens = list(client.stream("sys", "user"))
    assert "".join(tokens) == "hello world"


def test_mock_astreaming():
    provider = MockProvider(model="mock", response="hello world")
    client = LLMClient(provider=provider)

    async def _collect():
        return [token async for token in client.astream("sys", "user")]

    tokens = asyncio.run(_collect())
    assert "".join(tokens) == "hello world"


def test_openai_provider_model_override():
    provider = MockProvider(model="mock")  # stand-in for provider injection
    client = LLMClient(provider=provider)
    output = client.chat("sys", "user", model="gpt-4")
    assert "[MOCK gpt-4" in output


def test_mask_redacts_api_key():
    text = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
    masked = LLMClient._mask(text)
    assert masked == "[API_KEY_REDACTED]"


def test_ollama_provider_build_body():
    provider = OllamaProvider(model="llama3", base_url="http://localhost:11434")
    body = provider._build_body(
        "你是一名架构师", "设计一个登录模块", temperature=0.5, max_tokens=256
    )
    assert body["model"] == "llama3"
    assert body["messages"][0]["role"] == "system"
    assert body["options"]["temperature"] == 0.5
    assert body["options"]["num_predict"] == 256


def test_ollama_provider_chat_mocked(monkeypatch):
    class FakeResponse:
        def json(self):
            return {"message": {"content": "hello from ollama"}}

        def raise_for_status(self):
            pass

    called = {}

    def fake_post(self, url, *, json, timeout):
        called["url"] = url
        called["json"] = json
        return FakeResponse()

    monkeypatch.setattr("httpx.Client.post", fake_post)
    monkeypatch.setattr("httpx.Client.close", lambda self: None)

    provider = OllamaProvider(model="llama3")
    output = provider.chat("sys", "user")
    assert output == "hello from ollama"
    assert called["url"] == "http://localhost:11434/api/chat"
    assert called["json"]["model"] == "llama3"


def test_openai_provider_build_kwargs():
    openai = pytest.importorskip("openai")
    provider = OpenAIProvider(
        model="deepseek-chat",
        api_key="test-key",
        base_url="https://api.deepseek.com",
    )
    kwargs = provider._build_kwargs(
        "sys", "user", model="gpt-4", temperature=0.2, max_tokens=100
    )
    assert kwargs["model"] == "gpt-4"
    assert kwargs["temperature"] == 0.2
    assert kwargs["max_tokens"] == 100
    assert kwargs["messages"][0]["content"] == "sys"
