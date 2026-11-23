"""混合检索测试与链路调试接口。"""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_permission
from app.db.session import get_db
from app.models import User
from app.schemas.document import SearchResultOut
from app.services.access import get_visible_kb, visible_kb_ids
from app.services.search.hybrid import hybrid_search
from app.services.search.trace import trace_search

router = APIRouter(prefix="/search", tags=["search"])


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    kb_id: uuid.UUID | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    search_type: str = Field(
        default="hybrid", pattern=r"^(hybrid|vector|keyword)$"
    )


class DebugSearchRequest(SearchRequest):
    """调试台请求：可选覆盖阈值，便于对比不同阈值下的判定结果。"""

    rrf_threshold: float | None = Field(default=None, ge=0, le=1)
    cos_threshold: float | None = Field(default=None, ge=-1, le=1)


async def _resolve_scope(
    db: AsyncSession, user: User, kb_id: uuid.UUID | None
) -> tuple[str | None, list[str] | None]:
    """把请求范围收敛到「当前用户可见」：点名单库校验权限，否则下发可见库集合。"""
    if kb_id is not None:
        kb = await get_visible_kb(db, kb_id, user)
        return str(kb.id), None
    return None, await visible_kb_ids(db, user)


@router.post("", response_model=list[SearchResultOut])
async def search(
    body: SearchRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("kb:read")),
):
    scoped_kb_id, kb_ids = await _resolve_scope(db, user, body.kb_id)
    return await hybrid_search(
        body.query, scoped_kb_id, body.top_k, body.search_type, kb_ids
    )


@router.post("/debug")
async def debug_search(
    body: DebugSearchRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("kb:read")),
):
    """检索链路可视化：两路召回明细 → RRF 融合 → 余弦校验 → 阈值判定 → 上下文拼装。"""
    scoped_kb_id, kb_ids = await _resolve_scope(db, user, body.kb_id)
    return await trace_search(
        body.query,
        scoped_kb_id,
        body.top_k,
        body.search_type,
        body.rrf_threshold,
        body.cos_threshold,
        kb_ids,
    )
