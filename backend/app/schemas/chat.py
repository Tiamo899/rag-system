"""会话与消息 Pydantic 模型。"""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ChatSessionCreate(BaseModel):
    title: str | None = None
    kb_id: uuid.UUID | None = None


class ChatSessionOut(BaseModel):
    id: uuid.UUID
    title: str
    kb_id: uuid.UUID | None
    status: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChatMessageOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    sources: list = []
    model: str | None = None
    latency_ms: int | None = None
    feedback: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatSendRequest(BaseModel):
    content: str
    kb_id: uuid.UUID | None = None  # 可选：本条消息指定知识库，覆盖会话默认


class ChatFeedbackRequest(BaseModel):
    # null = 显式清除；like/dislike 用于切换
    feedback: Literal["like", "dislike"] | None = None
