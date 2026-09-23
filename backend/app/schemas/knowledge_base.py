"""知识库相关 Pydantic 模型。"""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    icon: str = "database"
    color: str = "#1890ff"
    chunk_size: int = Field(default=500, ge=50, le=2000, description="分块大小(tokens)")
    chunk_overlap: int = Field(default=50, ge=0, le=500, description="分块重叠(tokens)")


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    chunk_size: int | None = Field(default=None, ge=50, le=2000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=500)


class KnowledgeBaseOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    icon: str
    color: str
    chunk_size: int
    chunk_overlap: int
    status: int
    created_by: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}
