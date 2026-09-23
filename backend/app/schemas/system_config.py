"""系统配置 Pydantic 模型。"""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SystemConfigOut(BaseModel):
    id: uuid.UUID | None = None
    key: str
    value: str | None = None
    description: str | None = None
    env_key: str | None = None
    source: str = "env"
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class SystemConfigItem(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    value: str | None = None
    description: str | None = None


class SystemConfigBulkUpdate(BaseModel):
    configs: list[SystemConfigItem]
