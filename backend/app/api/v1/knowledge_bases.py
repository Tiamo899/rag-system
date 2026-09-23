"""知识库 CRUD 接口。"""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_permission
from app.core.exceptions import ForbiddenError, NotFoundError
from app.db.session import get_db
from app.models import KnowledgeBase, User
from app.schemas.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseOut,
    KnowledgeBaseUpdate,
)

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


@router.get("", response_model=list[KnowledgeBaseOut])
async def list_knowledge_bases(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("kb:read")),
):
    result = await db.execute(select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=KnowledgeBaseOut, status_code=201)
async def create_knowledge_base(
    body: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("kb:create")),
):
    kb = KnowledgeBase(
        name=body.name,
        description=body.description,
        icon=body.icon,
        color=body.color,
        chunk_size=body.chunk_size,
        chunk_overlap=body.chunk_overlap,
        created_by=user.id,
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return kb


async def _get_kb(db: AsyncSession, kb_id: uuid.UUID) -> KnowledgeBase:
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise NotFoundError("知识库不存在")
    return kb


@router.get("/{kb_id}", response_model=KnowledgeBaseOut)
async def get_knowledge_base(
    kb_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("kb:read")),
):
    return await _get_kb(db, kb_id)


@router.put("/{kb_id}", response_model=KnowledgeBaseOut)
async def update_knowledge_base(
    kb_id: uuid.UUID,
    body: KnowledgeBaseUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("kb:update")),
):
    kb = await _get_kb(db, kb_id)
    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(kb, key, value)
    await db.commit()
    await db.refresh(kb)
    return kb


@router.delete("/{kb_id}", status_code=204)
async def delete_knowledge_base(
    kb_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("kb:delete")),
):
    kb = await _get_kb(db, kb_id)
    # 先清 ES（该知识库下所有分块），再删 DB（级联文档/分块）
    try:
        from app.core.config import get_settings
        from app.core.elasticsearch import get_es

        await get_es().delete_by_query(
            index=get_settings().es_index,
            query={"term": {"kb_id": str(kb_id)}},
            refresh=True,
        )
    except Exception:  # noqa: BLE001
        pass
    await db.delete(kb)
    await db.commit()
