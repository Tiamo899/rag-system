"""用户管理 API：列表（分页+搜索）/ 创建 / 更新（角色/状态/密码）/ 删除。

护栏：不能禁用/删除自己，不能删除 admin 账号，仅 *:* 持有者可授予 admin 角色。
"""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.auth import _to_user_out
from app.core.deps import require_permission
from app.core.exceptions import AppError, NotFoundError
from app.core.security.password import hash_password
from app.core.security.rbac import collect_permissions
from app.db.session import get_db
from app.models import ChatSession, Document, KnowledgeBase, Role, User
from app.schemas.auth import UserOut
from app.schemas.users import UserCreate, UserPage, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


async def _get_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    """按 id 查用户（含 roles），查不到 404。"""
    user = (
        await db.execute(
            select(User).options(selectinload(User.roles)).where(User.id == user_id)
        )
    ).scalar_one_or_none()
    if user is None:
        raise NotFoundError("用户不存在")
    return user


async def _load_roles(db: AsyncSession, role_ids: list[uuid.UUID]) -> list[Role]:
    if not role_ids:
        return []
    return (await db.execute(select(Role).where(Role.id.in_(role_ids)))).scalars().all()


def _ensure_no_admin_escalation(operator: User, roles: list[Role]) -> None:
    """安全护栏：仅 *:* 持有者（admin）可授予 admin 角色，防提权。"""
    if any(r.name == "admin" for r in roles) and "*:*" not in collect_permissions(operator.roles):
        raise AppError("无权授予管理员角色", code="FORBIDDEN_ADMIN", status_code=403)


@router.get("", response_model=UserPage)
async def list_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    search: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("user:manage")),
):
    conditions = []
    if search:
        conditions.append(
            or_(User.username.ilike(f"%{search}%"), User.email.ilike(f"%{search}%"))
        )
    total = await db.scalar(select(func.count(User.id)).where(*conditions))
    rows = (
        await db.execute(
            select(User)
            .options(selectinload(User.roles))
            .where(*conditions)
            .order_by(User.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return UserPage(
        items=[_to_user_out(u) for u in rows],
        total=total or 0,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("user:manage")),
):
    existing = (
        await db.execute(
            select(User).where(
                or_(User.username == body.username, User.email == body.email)
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise AppError("用户名或邮箱已被注册", code="USER_EXISTS", status_code=409)

    roles = await _load_roles(db, body.role_ids)
    _ensure_no_admin_escalation(user, roles)

    new_user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        status=body.status,
        roles=roles,
    )
    db.add(new_user)
    await db.commit()
    return _to_user_out(await _get_user(db, new_user.id))


@router.put("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("user:manage")),
):
    target = await _get_user(db, user_id)
    data = body.model_dump(exclude_unset=True)

    if data.get("status") == 0 and target.id == user.id:
        raise AppError("不能禁用当前登录账号", code="SELF_DISABLE", status_code=400)

    # 改用户名/邮箱前查重（避免 unique 约束冲突落成 500）
    if "username" in data or "email" in data:
        conflict = (
            await db.execute(
                select(User).where(
                    or_(
                        User.username == data.get("username"),
                        User.email == data.get("email"),
                    ),
                    User.id != target.id,
                )
            )
        ).scalar_one_or_none()
        if conflict is not None:
            raise AppError("用户名或邮箱已被占用", code="USER_EXISTS", status_code=409)

    if data.get("password"):
        target.password_hash = hash_password(data["password"])
    if "role_ids" in data:
        roles = await _load_roles(db, data["role_ids"])
        _ensure_no_admin_escalation(user, roles)
        target.roles = roles
    for key in ("username", "email", "status"):
        if key in data:
            setattr(target, key, data[key])

    await db.commit()
    return _to_user_out(await _get_user(db, target.id))


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("user:manage")),
):
    target = await _get_user(db, user_id)
    if target.id == user.id:
        raise AppError("不能删除当前登录账号", code="SELF_DELETE", status_code=400)
    if any(r.name == "admin" for r in target.roles):
        raise AppError("不能删除管理员账号", code="ADMIN_DELETE", status_code=400)

    # 该用户创建的内容不能随账号静默消失：先让管理员转移或删除
    owned_kbs = await db.scalar(
        select(func.count(KnowledgeBase.id)).where(KnowledgeBase.created_by == target.id)
    ) or 0
    owned_docs = await db.scalar(
        select(func.count(Document.id)).where(Document.created_by == target.id)
    ) or 0
    if owned_kbs or owned_docs:
        raise AppError(
            f"该用户创建了 {owned_kbs} 个知识库、{owned_docs} 篇文档，"
            "请先删除这些内容或转移归属后再删除账号",
            code="USER_HAS_CONTENT",
            status_code=409,
        )

    # 会话随账号一起清理（chat_messages 由外键 CASCADE 跟随 session 删除）
    await db.execute(delete(ChatSession).where(ChatSession.user_id == target.id))
    await db.delete(target)
    await db.commit()
