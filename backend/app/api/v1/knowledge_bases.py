"""知识库 CRUD 接口。"""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_permission
from app.core.exceptions import AppError, ForbiddenError, NotFoundError
from app.core.security.rbac import collect_permissions, permission_match
from app.db.session import get_db
from app.models import KnowledgeBase, Role, User
from app.schemas.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseOut,
    KnowledgeBaseUpdate,
)
from app.services.access import get_visible_kb, visible_kb_ids

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


async def _validate_grants(
    db: AsyncSession,
    role_names: list[str] | None,
    user_ids: list[uuid.UUID] | None,
) -> None:
    """受限范围必须是真实存在的角色与用户，避免前端自由输入写入脏数据。"""
    if role_names:
        existing = set((await db.execute(select(Role.name))).scalars().all())
        bad = [r for r in role_names if r not in existing]
        if bad:
            raise AppError(
                f"角色不存在：{', '.join(bad)}", code="INVALID_ROLE", status_code=400
            )
    if user_ids:
        found = {
            str(uid)
            for uid in (await db.execute(
                select(User.id).where(User.id.in_(list(user_ids)))
            )).scalars().all()
        }
        bad = [str(uid) for uid in user_ids if str(uid) not in found]
        if bad:
            raise AppError(
                f"用户不存在：{', '.join(bad)}", code="INVALID_USER", status_code=400
            )


@router.get("/access-options")
async def access_options(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("kb:read")),
):
    """受限范围的可选值：角色全量；用户仅对有 user:manage 权限的调用方下发。"""
    roles = (await db.execute(select(Role.name).order_by(Role.name))).scalars().all()
    can_grant_users = permission_match("user:manage", collect_permissions(user.roles))
    users: list[dict] = []
    if can_grant_users:
        rows = (
            await db.execute(
                select(User.id, User.username, User.email)
                .where(User.status == 1)
                .order_by(User.username)
                .limit(500)
            )
        ).all()
        users = [{"id": str(r.id), "username": r.username, "email": r.email} for r in rows]
    return {"roles": list(roles), "users": users, "can_grant_users": can_grant_users}


@router.get("", response_model=list[KnowledgeBaseOut])
async def list_knowledge_bases(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("kb:read")),
):
    allowed = await visible_kb_ids(db, user)
    stmt = select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc())
    if allowed is not None:
        if not allowed:
            return []
        stmt = stmt.where(KnowledgeBase.id.in_([uuid.UUID(k) for k in allowed]))
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("", response_model=KnowledgeBaseOut, status_code=201)
async def create_knowledge_base(
    body: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("kb:create")),
):
    await _validate_grants(db, body.allowed_roles, body.allowed_users)
    kb = KnowledgeBase(
        name=body.name,
        description=body.description,
        icon=body.icon,
        color=body.color,
        chunk_size=body.chunk_size,
        chunk_overlap=body.chunk_overlap,
        visibility=body.visibility,
        allowed_roles=body.allowed_roles,
        allowed_users=[str(u) for u in body.allowed_users],
        created_by=user.id,
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return kb


async def _get_kb(db: AsyncSession, kb_id: uuid.UUID, user: User | None = None) -> KnowledgeBase:
    if user is not None:
        return await get_visible_kb(db, kb_id, user)
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise NotFoundError("知识库不存在")
    return kb


@router.get("/{kb_id}", response_model=KnowledgeBaseOut)
async def get_knowledge_base(
    kb_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("kb:read")),
):
    return await _get_kb(db, kb_id, user)


@router.put("/{kb_id}", response_model=KnowledgeBaseOut)
async def update_knowledge_base(
    kb_id: uuid.UUID,
    body: KnowledgeBaseUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("kb:update")),
):
    kb = await _get_kb(db, kb_id, user)
    data = body.model_dump(exclude_unset=True)
    if "allowed_roles" in data or "allowed_users" in data:
        await _validate_grants(
            db,
            data.get("allowed_roles", kb.allowed_roles),
            data.get("allowed_users", kb.allowed_users),
        )
    if "allowed_users" in data and data["allowed_users"] is not None:
        data["allowed_users"] = [str(u) for u in data["allowed_users"]]
    for key, value in data.items():
        setattr(kb, key, value)
    await db.commit()
    await db.refresh(kb)
    return kb


@router.delete("/{kb_id}", status_code=204)
async def delete_knowledge_base(
    kb_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("kb:delete")),
):
    kb = await _get_kb(db, kb_id, user)
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
