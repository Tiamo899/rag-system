"""混合检索测试接口。"""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.deps import require_permission
from app.models import User
from app.schemas.document import SearchResultOut
from app.services.search.hybrid import hybrid_search

router = APIRouter(prefix="/search", tags=["search"])


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    kb_id: uuid.UUID
    top_k: int = Field(default=5, ge=1, le=20)
    search_type: str = Field(
        default="hybrid", pattern=r"^(hybrid|vector|keyword)$"
    )


@router.post("", response_model=list[SearchResultOut])
async def search(
    body: SearchRequest,
    _user: User = Depends(require_permission("kb:read")),
):
    return await hybrid_search(
        body.query, str(body.kb_id), body.top_k, body.search_type
    )
