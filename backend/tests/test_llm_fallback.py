"""LLM 主备模型链路测试（MockTransport，不依赖真实网络）。

覆盖：主模型 429 → 切备用；主模型 4xx（如模型下线）→ 切备用；
鉴权失败不切（同一套 key 换模型无意义）；流式切换只在未出字前发生。
"""
import json

import httpx
import pytest

from app.core.exceptions import ProviderError
from app.services.llm.openai_adapter import OpenAICompatibleLLM

PRIMARY = "glm-4.7-flash"
BACKUP = "glm-4-flash-250414"


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _llm(handler):
    # max_retries=0：不等待退避，测试聚焦“换模型”而不是“同模型重试”
    return OpenAICompatibleLLM(
        api_key="k",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model=PRIMARY,
        fallback_models=[BACKUP],
        client=_client(handler),
        max_retries=0,
    )


@pytest.mark.asyncio
async def test_generate_switches_on_rate_limit():
    def handler(req: httpx.Request) -> httpx.Response:
        model = json.loads(req.content)["model"]
        if model == PRIMARY:
            return httpx.Response(429, json={"error": {"code": "1305"}})
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "备用模型作答 [1]"}}]}
        )

    llm = _llm(handler)
    assert await llm.generate("问题：x") == "备用模型作答 [1]"
    assert llm.last_model == BACKUP


@pytest.mark.asyncio
async def test_generate_switches_on_model_gone():
    def handler(req: httpx.Request) -> httpx.Response:
        model = json.loads(req.content)["model"]
        if model == PRIMARY:
            return httpx.Response(400, json={"error": {"message": "unknown model"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    llm = _llm(handler)
    assert await llm.generate("问题：x") == "ok"
    assert llm.last_model == BACKUP


@pytest.mark.asyncio
async def test_auth_error_does_not_switch():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(json.loads(req.content)["model"])
        return httpx.Response(401, json={"error": {"message": "Invalid key"}})

    llm = _llm(handler)
    with pytest.raises(ProviderError) as ei:
        await llm.generate("问题：x")
    assert ei.value.code == "PROVIDER_AUTH_ERROR"
    assert calls == [PRIMARY]  # 没有拿备用模型再撞一次鉴权


@pytest.mark.asyncio
async def test_generate_all_models_exhausted():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"code": "1305"}})

    llm = _llm(handler)
    with pytest.raises(ProviderError) as ei:
        await llm.generate("问题：x")
    assert ei.value.code == "PROVIDER_RATE_LIMITED"


@pytest.mark.asyncio
async def test_stream_switches_before_first_token():
    sse = (
        'data: {"choices":[{"delta":{"content":"备"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"用"}}]}\n\n'
        'data: [DONE]\n\n'
    )

    def handler(req: httpx.Request) -> httpx.Response:
        model = json.loads(req.content)["model"]
        if model == PRIMARY:
            return httpx.Response(429, json={"error": {"code": "1305"}})
        return httpx.Response(200, content=sse.encode())

    llm = _llm(handler)
    parts = [p async for p in llm.generate_stream("问题：x")]
    assert parts == ["备", "用"]
    assert llm.last_model == BACKUP


@pytest.mark.asyncio
async def test_empty_content_counts_as_failure_and_switches():
    """实测 glm-4.7-flash 拥堵时会返回 200 + 空 content（假成功），必须换模型。"""
    def handler(req: httpx.Request) -> httpx.Response:
        model = json.loads(req.content)["model"]
        if model == PRIMARY:
            return httpx.Response(200, json={"choices": [{"message": {"content": "  "}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "备用作答"}}]})

    llm = _llm(handler)
    assert await llm.generate("问题：x") == "备用作答"
    assert llm.last_model == BACKUP


@pytest.mark.asyncio
async def test_empty_content_on_all_models_raises():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})

    llm = _llm(handler)
    with pytest.raises(ProviderError) as ei:
        await llm.generate("问题：x")
    assert ei.value.code == "PROVIDER_RESPONSE_INVALID"


@pytest.mark.asyncio
async def test_stream_switches_when_model_returns_no_token():
    """流式 200 但零 token：也应换备用模型，而不是返回空答案。"""
    sse = 'data: {"choices":[{"delta":{"content":"备"}}]}\n\ndata: [DONE]\n\n'

    def handler(req: httpx.Request) -> httpx.Response:
        model = json.loads(req.content)["model"]
        if model == PRIMARY:
            return httpx.Response(200, content=b"data: [DONE]\n\n")
        return httpx.Response(200, content=sse.encode())

    llm = _llm(handler)
    parts = [p async for p in llm.generate_stream("问题：x")]
    assert parts == ["备"]
    assert llm.last_model == BACKUP


@pytest.mark.asyncio
async def test_single_model_behavior_unchanged():
    """不配置备用模型时，失败即抛，和改造前一致。"""
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"code": "1305"}})

    llm = OpenAICompatibleLLM(
        api_key="k", model=PRIMARY, client=_client(handler), max_retries=0
    )
    assert llm.models == [PRIMARY]
    with pytest.raises(ProviderError) as ei:
        await llm.generate("问题：x")
    assert ei.value.code == "PROVIDER_RATE_LIMITED"
