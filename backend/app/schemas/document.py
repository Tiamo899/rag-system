"""文档相关 Pydantic 模型。"""
import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class DocumentOut(BaseModel):
    id: uuid.UUID
    kb_id: uuid.UUID
    filename: str
    original_name: str
    file_type: str
    file_size: int | None
    status: str
    chunk_count: int
    valid_from: date | None = None
    valid_to: date | None = None
    version_no: str | None = None
    superseded_by: uuid.UUID | None = None
    supersedes_doc_id: uuid.UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentUpdate(BaseModel):
    valid_from: date | None = None
    valid_to: date | None = None
    version_no: str | None = Field(default=None, max_length=50)


class DocumentChunkOut(BaseModel):
    id: uuid.UUID
    doc_id: uuid.UUID
    title: str | None
    chunk_index: int
    content: str
    token_count: int | None
    es_doc_id: str | None

    model_config = {"from_attributes": True}


class SearchResultOut(BaseModel):
    chunk_id: str
    doc_id: str
    doc_name: str | None
    kb_name: str | None
    title: str | None
    chunk_index: int
    content: str
    score: float
