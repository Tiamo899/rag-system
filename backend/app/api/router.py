"""聚合 /api/v1 各模块路由。"""
from fastapi import APIRouter

from app.api.v1 import (
    auth,
    chat,
    documents,
    knowledge_bases,
    roles,
    search,
    system_configs,
    users,
    stats,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(knowledge_bases.router)
api_router.include_router(documents.router)
api_router.include_router(search.router)
api_router.include_router(chat.router)
api_router.include_router(roles.router)
api_router.include_router(users.router)
api_router.include_router(system_configs.router)
api_router.include_router(stats.router)
