"""Embedding 工厂：按 EMBEDDING_PROVIDER 配置切换实现（唯一入口）。"""
from functools import lru_cache

from app.core.config import get_settings
from app.core.exceptions import ProviderError
from app.services.embedding.base import BaseEmbedding


@lru_cache
def get_embedding_provider() -> BaseEmbedding:
    settings = get_settings()
    if settings.embedding_provider == "openai":
        if not settings.embedding_api_key:
            raise ProviderError(
                "EMBEDDING_PROVIDER=openai 但未配置 EMBEDDING_API_KEY：请在 "
                "backend/.env 填写，或把 EMBEDDING_PROVIDER 改回 mock",
                code="PROVIDER_KEY_MISSING",
            )
        from app.services.embedding.openai_adapter import OpenAIEmbedding

        return OpenAIEmbedding(
            settings.embedding_dim,
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
            model=settings.embedding_model,
        )
    # 默认 mock
    from app.services.embedding.mock import MockEmbedding

    return MockEmbedding(settings.embedding_dim)
