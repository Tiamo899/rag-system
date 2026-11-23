"""知识库相关 Pydantic 模型。"""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    icon: str = "database"
    color: str = "#1890ff"
    chunk_size: int = Field(default=500, ge=50, le=2000, description="分块大小(tokens)")
    chunk_overlap: int = Field(default=50, ge=0, le=500, description="分块重叠(tokens)")
    visibility: Literal["public", "restricted"] = "public"
    allowed_roles: list[str] = Field(default_factory=list, description="restricted 时可见的角色名")
    allowed_users: list[uuid.UUID] = Field(default_factory=list, description="restricted 时可见的用户")

    @field_validator("allowed_roles")
    @classmethod
    def _dedup_roles(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(r.strip() for r in v if r and r.strip()))

    @field_validator("allowed_users")
    @classmethod
    def _dedup_users(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        return list(dict.fromkeys(v))


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    chunk_size: int | None = Field(default=None, ge=50, le=2000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=500)
    visibility: Literal["public", "restricted"] | None = None
    allowed_roles: list[str] | None = None
    allowed_users: list[uuid.UUID] | None = None

    @field_validator("allowed_roles")
    @classmethod
    def _dedup_roles(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return list(dict.fromkeys(r.strip() for r in v if r and r.strip()))

    @field_validator("allowed_users")
    @classmethod
    def _dedup_users(cls, v: list[uuid.UUID] | None) -> list[uuid.UUID] | None:
        if v is None:
            return None
        return list(dict.fromkeys(v))


class KnowledgeBaseOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    icon: str
    color: str
    chunk_size: int
    chunk_overlap: int
    status: int
    visibility: str = "public"
    allowed_roles: list[str] = Field(default_factory=list)
    allowed_users: list[uuid.UUID] = Field(default_factory=list)
    created_by: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}
