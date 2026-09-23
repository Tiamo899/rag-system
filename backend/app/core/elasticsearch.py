"""ES 异步客户端单例。本地开发：无认证、纯 http。"""
from elasticsearch import AsyncElasticsearch

from app.core.config import get_settings

_settings = get_settings()

_es: AsyncElasticsearch | None = None


def get_es() -> AsyncElasticsearch:
    global _es
    if _es is None:
        _es = AsyncElasticsearch(_settings.es_url, request_timeout=30)
    return _es


async def close_es() -> None:
    global _es
    if _es is not None:
        await _es.close()
        _es = None
