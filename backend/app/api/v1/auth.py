"""认证接口：注册 / 登录 / 刷新 / 当前用户。"""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user
from app.core.exceptions import AppError, UnauthorizedError
from app.core.security.jwt import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.core.security.password import hash_password, verify_password
from app.db.session import get_db
from app.models import Role, User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _to_user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        email=user.email,
        status=user.status,
        roles=[r.name for r in user.roles],
        role_ids=[r.id for r in user.roles],
        created_at=user.created_at,
    )


def _token_response(user: User) -> TokenResponse:
    roles = [r.name for r in user.roles]
    return TokenResponse(
        access_token=create_access_token(user.id, roles),
        refresh_token=create_refresh_token(user.id, roles),
        user=_to_user_out(user),
    )


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    body: RegisterRequest, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    existing = (
        await db.execute(
            select(User).where(
                or_(User.username == body.username, User.email == body.email)
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise AppError("用户名或邮箱已被注册", code="USER_EXISTS", status_code=409)

    viewer_role = (
        await db.execute(select(Role).where(Role.name == "viewer"))
    ).scalar_one()
    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        roles=[viewer_role],
    )
    db.add(user)
    await db.commit()
    # 重新按 id 查询并显式加载 roles（避免对关系属性的懒加载，async 引擎下会炸）
    user = (
        await db.execute(
            select(User).options(selectinload(User.roles)).where(User.id == user.id)
        )
    ).scalar_one()
    return _token_response(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    user = (
        await db.execute(
            select(User)
            .options(selectinload(User.roles))
            .where(User.username == body.username)
        )
    ).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise UnauthorizedError("用户名或密码错误")
    if user.status != 1:
        raise UnauthorizedError("账号已被禁用")
    return _token_response(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    try:
        payload = decode_token(body.refresh_token)
    except Exception:  # noqa: BLE001
        raise UnauthorizedError("刷新令牌无效或已过期")
    if payload.get("type") != "refresh":
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
    return _token_response(user)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return _to_user_out(user)
