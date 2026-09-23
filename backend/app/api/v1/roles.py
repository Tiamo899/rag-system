"""角色管理 API：列表（含用户数）/ 权限目录 / 创建 / 更新 / 删除。

内置角色（admin/editor/viewer）仅允许修改描述，禁止改名、改权限、删除。
有用户引用的角色禁止删除。
"""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_permission
from app.core.exceptions import AppError, NotFoundError
from app.core.security.rbac import ALL_PERMISSION_KEYS, BUILTIN_ROLES, PERMISSIONS_CATALOG
from app.db.session import get_db
from app.models import Role, User, user_roles
from app.schemas.roles import RoleCreate, RoleOut, RoleUpdate

router = APIRouter(prefix="/roles", tags=["roles"])


async def _get_role(db: AsyncSession, role_id: uuid.UUID) -> Role:
    role = await db.get(Role, role_id)
    if role is None:
        raise NotFoundError("角色不存在")
    return role


def _to_out(role: Role, user_count: int) -> RoleOut:
    return RoleOut(
        id=role.id,
        name=role.name,
        description=role.description,
        permissions=role.permissions or [],
        user_count=user_count,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


@router.get("/permissions")
async def list_permissions(
    _user: User = Depends(require_permission("role:manage")),
):
    """返回权限目录（按模块分组），供前端权限树渲染。"""
    return PERMISSIONS_CATALOG


@router.get("", response_model=list[RoleOut])
async def list_roles(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("role:manage")),
):
    stmt = (
        select(Role, func.count(user_roles.c.user_id))
        .outerjoin(user_roles, user_roles.c.role_id == Role.id)
        .group_by(Role.id)
        .order_by(Role.created_at.asc())
    )
    rows = (await db.execute(stmt)).all()
    return [_to_out(r, c) for r, c in rows]


@router.post("", response_model=RoleOut, status_code=201)
async def create_role(
    body: RoleCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("role:manage")),
):
    invalid = set(body.permissions) - ALL_PERMISSION_KEYS
    if invalid:
        raise AppError(f"未知权限点：{sorted(invalid)}", code="INVALID_PERMISSION", status_code=400)
    existing = await db.scalar(select(Role).where(Role.name == body.name))
    if existing is not None:
        raise AppError("角色名已存在", code="ROLE_EXISTS", status_code=409)

    role = Role(
        name=body.name,
        description=body.description,
        permissions=body.permissions,
    )
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return _to_out(role, 0)


@router.put("/{role_id}", response_model=RoleOut)
async def update_role(
    role_id: uuid.UUID,
    body: RoleUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("role:manage")),
):
    role = await _get_role(db, role_id)
    data = body.model_dump(exclude_unset=True)

    if role.name in BUILTIN_ROLES and ("name" in data or "permissions" in data):
        raise AppError("内置角色仅允许修改描述", code="BUILTIN_ROLE_FROZEN", status_code=400)
    if "permissions" in data:
        invalid = set(data["permissions"]) - ALL_PERMISSION_KEYS
        if invalid:
            raise AppError(f"未知权限点：{sorted(invalid)}", code="INVALID_PERMISSION", status_code=400)
    if "name" in data and data["name"] != role.name:
        existing = await db.scalar(select(Role).where(Role.name == data["name"]))
        if existing is not None:
            raise AppError("角色名已存在", code="ROLE_EXISTS", status_code=409)

    for key, value in data.items():
        setattr(role, key, value)
    await db.commit()
    await db.refresh(role)
    count = await db.scalar(
        select(func.count()).select_from(user_roles).where(user_roles.c.role_id == role.id)
    )
    return _to_out(role, count or 0)


@router.delete("/{role_id}", status_code=204)
async def delete_role(
    role_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("role:manage")),
):
    role = await _get_role(db, role_id)
    if role.name in BUILTIN_ROLES:
        raise AppError("内置角色不允许删除", code="BUILTIN_ROLE_FROZEN", status_code=400)
    refs = await db.scalar(
        select(func.count())
        .select_from(user_roles)
        .where(user_roles.c.role_id == role.id)
    )
    if refs:
        raise AppError("该角色仍有用户，无法删除", code="ROLE_IN_USE", status_code=400)
    await db.delete(role)
    await db.commit()
