"""知识库表。"""
import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class KnowledgeBase(Base, TimestampMixin):
    __tablename__ = "knowledge_bases"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    icon: Mapped[str] = mapped_column(String(50), default="database")
    color: Mapped[str] = mapped_column(String(20), default="#1890ff")
    embedding_model: Mapped[str] = mapped_column(String(100), default="mock")
    chunk_size: Mapped[int] = mapped_column(Integer, default=500)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=50)
    status: Mapped[int] = mapped_column(Integer, default=1)
    # 可见范围：public=登录用户均可访问；restricted=仅 allowed_roles / allowed_users 与创建人
    visibility: Mapped[str] = mapped_column(String(20), default="public")
    allowed_roles: Mapped[list] = mapped_column(JSONB, default=list)
    allowed_users: Mapped[list] = mapped_column(JSONB, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

