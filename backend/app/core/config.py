"""应用配置：pydantic-settings 从 backend/.env 读取，字段名与 .env 一致。"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- 数据库 ----
    database_url: str = (
        "postgresql+asyncpg://rag:rag_dev_password@localhost:5432/rag_knowledge"
    )
    # Alembic 迁移用同步驱动（同库，避开 async 迁移样板）
    sync_database_url: str = (
        "postgresql+psycopg2://rag:rag_dev_password@localhost:5432/rag_knowledge"
    )

    # ---- Elasticsearch ----
    es_url: str = "http://localhost:9200"
    es_index: str = "rag_chunks"
    # 维度唯一事实来源：mock 向量 / ES mapping dims / 写入断言 都由它派生
    embedding_dim: int = 1536

    # ---- Redis ----
    redis_url: str = "redis://localhost:6379/0"

    # ---- JWT ----
    jwt_secret: str = "please-change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # ---- 模型 Provider ----
    embedding_provider: str = "mock"  # mock | openai
    llm_provider: str = "mock"        # mock | openai
    # 相关度阈值：hybrid 模式 score 是 RRF 融合分（量级 0.01-0.03），0.02 为 mock 实测值
    relevance_threshold: float = 0.30
    # 语义二次验证阈值：query 与 top chunk 的余弦相似度（RRF 分不可靠时兜底）。
    # RRF 或余弦任一达标即判定相关。bge-m3 实测：真相关 0.64+，真无关 <0.45
    relevance_cos_threshold: float = 0.5

    # ---- LLM（OpenAI 兼容 chat completions，默认 DeepSeek）----
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    # 2026-07 起 deepseek-chat 停用，官方模型为 deepseek-v4-flash / deepseek-v4-pro
    llm_model: str = "deepseek-v4-flash"

    # ---- Embedding（OpenAI 兼容 embeddings，默认 OpenAI）----
    embedding_api_key: str = ""
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"  # 1536 维，与 EMBEDDING_DIM 一致

    # ---- 默认管理员（首次启动种子）----
    default_admin_username: str = "admin"
    default_admin_password: str = "admin123"

    # ---- 应用 ----
    upload_dir: str = "data/uploads"
    max_upload_size_mb: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
