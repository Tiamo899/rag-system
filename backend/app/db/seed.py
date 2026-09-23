"""种子数据：admin/editor/viewer 三角色 + 默认 admin 账号 + 默认系统配置（幂等）。"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security.password import hash_password
from app.core.security.rbac import ROLE_PERMISSIONS
from app.models import Role, SystemConfig, User

DESCRIPTIONS = {
    "admin": "超级管理员，拥有全部权限",
    "editor": "编辑者：可管理知识库/上传向量化文档、发起对话",
    "viewer": "访客：仅可查看与对话",
}

DEFAULT_SYSTEM_CONFIGS: dict[str, tuple[str, str]] = {
    "llm.provider": ("mock", "大模型供应商：mock|openai"),
    "llm.api_key": ("", "大模型 API Key（暂不生效）"),
    "llm.base_url": ("", "大模型 API 地址"),
    "llm.model": ("", "模型名称"),
    "embedding.provider": ("mock", "向量模型供应商"),
    "embedding.model": ("text-embedding-ada-002", "向量模型"),
    "chunk.size": ("500", "默认分块大小(tokens)"),
    "chunk.overlap": ("50", "默认分块重叠(tokens)"),
}


async def ensure_seed_data(session: AsyncSession) -> None:
    settings = get_settings()

    roles: dict[str, Role] = {}
    for name, perms in ROLE_PERMISSIONS.items():
        role = (
            await session.execute(select(Role).where(Role.name == name))
        ).scalar_one_or_none()
        if role is None:
            role = Role(name=name, permissions=list(perms), description=DESCRIPTIONS[name])
            session.add(role)
        roles[name] = role
    await session.flush()

    admin_user = (
        await session.execute(
            select(User).where(User.username == settings.default_admin_username)
        )
    ).scalar_one_or_none()
    if admin_user is None:
        admin_user = User(
            username=settings.default_admin_username,
            email=f"{settings.default_admin_username}@local.dev",
            password_hash=hash_password(settings.default_admin_password),
            roles=[roles["admin"]],
        )
        session.add(admin_user)

    for key, (value, desc) in DEFAULT_SYSTEM_CONFIGS.items():
        if (
            await session.scalar(
                select(SystemConfig).where(SystemConfig.key == key)
            )
        ) is None:
            session.add(SystemConfig(key=key, value=value, description=desc))

    await session.commit()
