"""LLM 工厂：按 LLM_PROVIDER 配置切换实现。"""
from functools import lru_cache

from app.core.config import get_settings
from app.core.exceptions import ProviderError
from app.services.llm.base import BaseLLM


@lru_cache
def get_llm_provider() -> BaseLLM:
    settings = get_settings()
    if settings.llm_provider == "openai":
        if not settings.llm_api_key:
            raise ProviderError(
                "LLM_PROVIDER=openai 但未配置 LLM_API_KEY：请在 backend/.env "
                "填写，或把 LLM_PROVIDER 改回 mock",
                code="PROVIDER_KEY_MISSING",
            )
        from app.services.llm.openai_adapter import OpenAICompatibleLLM

        return OpenAICompatibleLLM(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            fallback_models=[
                m.strip() for m in settings.llm_fallback_models.split(",") if m.strip()
            ],
        )
    from app.services.llm.mock import MockLLM

    return MockLLM()
