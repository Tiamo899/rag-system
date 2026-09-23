"""用户管理 Pydantic 模型。"""
import uuid

from pydantic import BaseModel, EmailStr, Field

from app.schemas.auth import UserOut


class UserCreate(BaseModel):
    username: str = Field(
        min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_]+$",
        description="仅字母/数字/下划线",
    )
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    role_ids: list[uuid.UUID] = []
    status: int = Field(default=1, ge=0, le=1)


class UserUpdate(BaseModel):
    """全字段可选，靠 exclude_unset 支持局部更新。"""

    username: str | None = Field(
        default=None, min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_]+$"
    )
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=6, max_length=128)
    status: int | None = Field(default=None, ge=0, le=1)
    role_ids: list[uuid.UUID] | None = None


class UserPage(BaseModel):
    items: list[UserOut]
    total: int
    page: int
    page_size: int
