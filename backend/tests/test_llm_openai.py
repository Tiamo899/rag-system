"""OpenAI 兼容 LLM 适配器测试（MockTransport，不依赖真实网络/容器）。"""
import json

import httpx
import pytest

from app.core.exceptions import ProviderError
from app.services.llm.openai_adapter import OpenAICompatibleLLM


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_missing_key():
    with pytest.raises(ProviderError) as ei:
        OpenAICompatibleLLM(api_key="")
    assert ei.value.code == "PROVIDER_KEY_MISSING"


@pytest.mark.asyncio
async def test_generate_ok():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/chat/completions"
        assert req.headers["authorization"] == "Bearer k"
        body = json.loads(req.content)
        assert body["model"] == "deepseek-v4-flash"
        assert body["temperature"] == 0.3  # 默认 temperature 不得漂移
        assert body["messages"][0]["role"] == "system"
        assert body["messages"][1] == {"role": "user", "content": "问题：你好"}
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "你好 [1]"}}]},
        )

    llm = OpenAICompatibleLLM(
        api_key="k", base_url="https://api.deepseek.com", model="deepseek-v4-flash",
        client=_client(handler),
    )
    assert await llm.generate("问题：你好") == "你好 [1]"


@pytest.mark.asyncio
async def test_empty_choices():
    def handler(req):
        return httpx.Response(200, json={"choices": []})

    llm = OpenAICompatibleLLM(api_key="k", client=_client(handler))
    with pytest.raises(ProviderError) as ei:
        await llm.generate("问题：x")
    assert ei.value.code == "PROVIDER_RESPONSE_INVALID"


@pytest.mark.asyncio
async def test_empty_content():
    def handler(req):
        return httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})

    llm = OpenAICompatibleLLM(api_key="k", client=_client(handler))
    with pytest.raises(ProviderError) as ei:
        await llm.generate("问题：x")
    assert ei.value.code == "PROVIDER_RESPONSE_INVALID"


@pytest.mark.asyncio
async def test_auth_error():
    def handler(req):
        return httpx.Response(401, json={"error": {"message": "Invalid key"}})

    llm = OpenAICompatibleLLM(api_key="bad", client=_client(handler))
    with pytest.raises(ProviderError) as ei:
        await llm.generate("问题：x")
    assert ei.value.code == "PROVIDER_AUTH_ERROR"


@pytest.mark.asyncio
async def test_rate_limited():
    def handler(req):
        return httpx.Response(429, text="rate limit")

    llm = OpenAICompatibleLLM(api_key="k", client=_client(handler))
    with pytest.raises(ProviderError) as ei:
        await llm.generate("问题：x")
    assert ei.value.code == "PROVIDER_RATE_LIMITED"


@pytest.mark.asyncio
async def test_generate_stream_ok():
    sse = (
        'data: {"choices":[{"delta":{"content":"你"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"好"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":""}}]}\n\n'  # 空 delta 跳过
        'data: [DONE]\n\n'
    )

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/chat/completions"
        body = json.loads(req.content)
        assert body["stream"] is True
        return httpx.Response(200, content=sse.encode())

    llm = OpenAICompatibleLLM(api_key="k", client=_client(handler))
    parts = [p async for p in llm.generate_stream("问题：你好")]
    assert parts == ["你", "好"]


@pytest.mark.asyncio
async def test_generate_stream_auth_error():
    def handler(req):
        return httpx.Response(401, json={"error": {"message": "Invalid key"}})

    llm = OpenAICompatibleLLM(api_key="bad", client=_client(handler))
    with pytest.raises(ProviderError) as ei:
        async for _ in llm.generate_stream("问题：x"):
            pass
    assert ei.value.code == "PROVIDER_AUTH_ERROR"
