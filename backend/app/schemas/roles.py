"""角色管理 Pydantic 模型。"""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class RoleCreate(BaseModel):
    name: str = Field(
        min_length=1, max_length=50, pattern=r"^[a-zA-Z0-9_]+$",
        description="仅字母/数字/下划线",
    )
    description: str | None = None
    permissions: list[str] = []


class RoleUpdate(BaseModel):
    name: str | None = Field(
        default=None, min_length=1, max_length=50, pattern=r"^[a-zA-Z0-9_]+$"
    )
    description: str | None = None
    permissions: list[str] | None = None


class RoleOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    permissions: list[str]
    user_count: int
    created_at: datetime
    updated_at: datetime
