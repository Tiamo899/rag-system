"""知识库访问控制：可见范围判定与检索过滤集合。

规则：
- admin（持有 `*:*`）可见全部知识库；
- public 知识库对所有登录用户可见；
- restricted 知识库仅对 allowed_roles 命中的角色、创建人可见；
- 未命中时按「不存在」处理，避免泄露知识库是否存在。
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.security.rbac import collect_permissions
from app.models import KnowledgeBase, User


def is_superuser(user: User) -> bool:
    return "*:*" in collect_permissions(user.roles)


def user_role_names(user: User) -> set[str]:
    return {r.name for r in (user.roles or [])}


def can_view_kb(kb: KnowledgeBase, user: User) -> bool:
    if is_superuser(user):
        return True
    if (kb.visibility or "public") == "public":
        return True
    if kb.created_by is not None and kb.created_by == user.id:
        return True
    if str(user.id) in {str(u) for u in (kb.allowed_users or [])}:
        return True
    return bool(set(kb.allowed_roles or []) & user_role_names(user))


async def visible_kb_ids(db: AsyncSession, user: User) -> list[str] | None:
    """返回当前用户可见的知识库 id 列表；None 表示不受限（admin）。"""
    if is_superuser(user):
        return None
    rows = (
        await db.execute(
            select(
                KnowledgeBase.id,
                KnowledgeBase.visibility,
                KnowledgeBase.allowed_roles,
                KnowledgeBase.allowed_users,
                KnowledgeBase.created_by,
            )
        )
    ).all()
    roles = user_role_names(user)
    uid = str(user.id)
    return [
        str(r.id)
        for r in rows
        if (r.visibility or "public") == "public"
        or (r.created_by is not None and r.created_by == user.id)
        or uid in {str(u) for u in (r.allowed_users or [])}
        or bool(set(r.allowed_roles or []) & roles)
    ]


async def get_visible_kb(db: AsyncSession, kb_id: uuid.UUID, user: User) -> KnowledgeBase:
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise NotFoundError("知识库不存在")
    if not can_view_kb(kb, user):
        raise ForbiddenError("无权访问该知识库")
    return kb


async def ensure_kb_visible(db: AsyncSession, kb_id: uuid.UUID, user: User) -> None:
    await get_visible_kb(db, kb_id, user)


async def ensure_doc_kb_visible(db: AsyncSession, kb_id: uuid.UUID, user: User) -> None:
    await ensure_kb_visible(db, kb_id, user)
