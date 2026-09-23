"""FastAPI 依赖：当前用户、权限校验。"""
import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security.jwt import decode_token
from app.core.security.rbac import collect_permissions, permission_match
from app.db.session import get_db
from app.models import User

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise UnauthorizedError("未提供认证令牌")
    try:
        payload = decode_token(credentials.credentials)
    except Exception:  # noqa: BLE001
        raise UnauthorizedError("令牌无效或已过期")
    if payload.get("type") != "access":
        raise UnauthorizedError("令牌类型错误")
    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except (ValueError, TypeError):
        raise UnauthorizedError("令牌载荷非法")

    user = (
        await db.execute(
            select(User)
            .options(selectinload(User.roles))
            .where(User.id == user_id)
        )
    ).scalar_one_or_none()
    if user is None or user.status != 1:
        raise UnauthorizedError("用户不存在或已禁用")
    return user


def require_permission(permission: str):
    """返回一个依赖：校验当前用户是否拥有指定权限。用法：
    `user: User = Depends(require_permission("doc:vectorize"))`
    """
    async def checker(user: User = Depends(get_current_user)) -> User:
        perms = collect_permissions(user.roles)
        if not permission_match(permission, perms):
            raise ForbiddenError(f"缺少权限：{permission}")
        return user

    return checker
