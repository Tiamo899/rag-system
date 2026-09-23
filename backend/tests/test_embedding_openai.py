"""OpenAI 兼容 Embedding 适配器测试（MockTransport，不依赖真实网络/容器）。"""
import json

import httpx
import pytest

from app.core.exceptions import ProviderError
from app.services.embedding.openai_adapter import OpenAIEmbedding

DIMS = 1536


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_missing_key():
    with pytest.raises(ProviderError) as ei:
        OpenAIEmbedding(DIMS, api_key="", base_url="https://api.test.com/v1")
    assert ei.value.code == "PROVIDER_KEY_MISSING"


@pytest.mark.asyncio
async def test_embed_texts_ok():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/embeddings"
        assert req.headers["authorization"] == "Bearer test-key"
        body = json.loads(req.content)
        assert body["model"] == "text-embedding-3-small"
        return httpx.Response(
            200,
            json={"data": [{"embedding": [0.1] * DIMS} for _ in body["input"]], "model": "m"},
        )

    emb = OpenAIEmbedding(
        DIMS, api_key="test-key", base_url="https://api.test.com/v1",
        model="text-embedding-3-small", client=_client(handler),
    )
    vecs = await emb.embed_texts(["第一段", "第二段"])
    assert len(vecs) == 2 and all(len(v) == DIMS for v in vecs)


@pytest.mark.asyncio
async def test_base_url_without_v1():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        return httpx.Response(200, json={"data": [{"embedding": [0.0] * DIMS}], "model": "m"})

    emb = OpenAIEmbedding(DIMS, api_key="k", base_url="https://api.test.com",
                          client=_client(handler))
    await emb.embed_texts(["x"])
    assert seen["path"] == "/embeddings"


@pytest.mark.asyncio
async def test_dim_mismatch_raises():
    def handler(req):
        return httpx.Response(200, json={"data": [{"embedding": [0.0] * 512}], "model": "m"})

    emb = OpenAIEmbedding(DIMS, api_key="k", client=_client(handler))
    with pytest.raises(ProviderError) as ei:
        await emb.embed_texts(["x"])
    assert ei.value.code == "EMBEDDING_DIM_MISMATCH"


@pytest.mark.asyncio
async def test_auth_error():
    def handler(req):
        return httpx.Response(401, json={"error": {"message": "Invalid API key"}})

    emb = OpenAIEmbedding(DIMS, api_key="bad", client=_client(handler))
    with pytest.raises(ProviderError) as ei:
        await emb.embed_texts(["x"])
    assert ei.value.code == "PROVIDER_AUTH_ERROR"
    assert "API Key" in ei.value.message


@pytest.mark.asyncio
async def test_rate_limited():
    def handler(req):
        return httpx.Response(429, text="rate limit")

    emb = OpenAIEmbedding(DIMS, api_key="k", client=_client(handler))
    with pytest.raises(ProviderError) as ei:
        await emb.embed_texts(["x"])
    assert ei.value.code == "PROVIDER_RATE_LIMITED"


@pytest.mark.asyncio
async def test_network_error():
    def handler(req):
        raise httpx.ConnectError("boom", request=req)

    emb = OpenAIEmbedding(DIMS, api_key="k", client=_client(handler))
    with pytest.raises(ProviderError) as ei:
        await emb.embed_texts(["x"])
    assert ei.value.code == "PROVIDER_NETWORK_ERROR"
