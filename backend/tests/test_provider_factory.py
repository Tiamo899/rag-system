"""Provider 工厂选型测试（不依赖容器）。"""
import pytest

from app.core.config import get_settings
from app.core.exceptions import ProviderError
from app.services.embedding import factory as emb_factory
from app.services.embedding.mock import MockEmbedding
from app.services.embedding.openai_adapter import OpenAIEmbedding
from app.services.llm import factory as llm_factory
from app.services.llm.mock import MockLLM
from app.services.llm.openai_adapter import OpenAICompatibleLLM


def _set(monkeypatch, **kw):
    settings = get_settings()
    for k, v in kw.items():
        monkeypatch.setattr(settings, k, v)
    emb_factory.get_embedding_provider.cache_clear()
    llm_factory.get_llm_provider.cache_clear()


def test_embedding_factory_openai(monkeypatch):
    _set(monkeypatch, embedding_provider="openai", embedding_api_key="k",
         embedding_base_url="https://x", embedding_model="m")
    assert isinstance(emb_factory.get_embedding_provider(), OpenAIEmbedding)


def test_embedding_factory_mock(monkeypatch):
    _set(monkeypatch, embedding_provider="mock")
    assert isinstance(emb_factory.get_embedding_provider(), MockEmbedding)


def test_embedding_factory_openai_missing_key(monkeypatch):
    _set(monkeypatch, embedding_provider="openai", embedding_api_key="")
    with pytest.raises(ProviderError) as ei:
        emb_factory.get_embedding_provider()
    assert ei.value.code == "PROVIDER_KEY_MISSING"


def test_llm_factory_openai(monkeypatch):
    _set(monkeypatch, llm_provider="openai", llm_api_key="k",
         llm_base_url="https://x", llm_model="m")
    assert isinstance(llm_factory.get_llm_provider(), OpenAICompatibleLLM)


def test_llm_factory_mock(monkeypatch):
    _set(monkeypatch, llm_provider="mock")
    assert isinstance(llm_factory.get_llm_provider(), MockLLM)


def test_llm_factory_openai_missing_key(monkeypatch):
    _set(monkeypatch, llm_provider="openai", llm_api_key="")
    with pytest.raises(ProviderError) as ei:
        llm_factory.get_llm_provider()
    assert ei.value.code == "PROVIDER_KEY_MISSING"


def test_current_model_name(monkeypatch):
    from app.api.v1.chat import _current_model_name

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "llm_model", "deepseek-v4-flash")
    assert _current_model_name() == "deepseek-v4-flash"
    monkeypatch.setattr(settings, "llm_provider", "mock")
    assert _current_model_name() == "mock"
