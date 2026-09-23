"""OpenAI 兼容 Embedding 适配器（text-embedding-3-small 等）。

base_url 兼容两种形态：
- 含 /v1：https://api.openai.com/v1  →  POST /v1/embeddings
- 不含 /v1：自建网关/兼容服务        →  POST {base}/embeddings
拼接规则：去掉末尾 "/" 后直接拼 "/embeddings"，不自动补 /v1。
"""
import httpx

from app.core.exceptions import ProviderError
from app.services.embedding.base import BaseEmbedding
from app.services.provider_http import raise_provider_error, wrap_network_error

_EMBED_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class OpenAIEmbedding(BaseEmbedding):
    def __init__(
        self,
        dims: int,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "text-embedding-3-small",
        client: httpx.AsyncClient | None = None,  # 测试注入 MockTransport 用
    ):
        super().__init__(dims)
        if not api_key:
            raise ProviderError(
                "OpenAIEmbedding 缺少 api_key：请配置 EMBEDDING_API_KEY，"
                "或把 EMBEDDING_PROVIDER 设回 mock",
                code="PROVIDER_KEY_MISSING",
            )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=_EMBED_TIMEOUT)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        try:
            resp = await self._client.post(
                f"{self.base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self.model, "input": texts},
            )
        except httpx.HTTPError as exc:
            raise wrap_network_error("Embedding", exc) from exc

        if resp.status_code >= 400:
            raise_provider_error("Embedding", resp)

        data = resp.json().get("data") or []
        if len(data) != len(texts):
            raise ProviderError(
                f"Embedding 响应数量不符：期望 {len(texts)} 条，实际 {len(data)} 条",
                code="PROVIDER_RESPONSE_INVALID",
            )

        vectors: list[list[float]] = []
        for item in data:
            vec = item.get("embedding")
            if not isinstance(vec, list) or len(vec) != self.dims:
                actual = len(vec) if isinstance(vec, list) else "N/A"
                raise ProviderError(
                    f"Embedding 维度不符：期望 {self.dims}，实际 {actual}。"
                    "若更换了 embedding 模型，请同步改 EMBEDDING_DIM 并删除 ES 索引重建",
                    code="EMBEDDING_DIM_MISMATCH",
                )
            vectors.append(vec)
        return vectors

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
