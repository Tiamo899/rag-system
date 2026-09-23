"""FastAPI 应用入口。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.elasticsearch import close_es, get_es
from app.core.exceptions import register_exception_handlers
from app.db.seed import ensure_seed_data
from app.db.session import AsyncSessionLocal, engine
from app.services.search.es_index import ensure_index


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 依赖服务（ES/PG）未启动时不阻断，打印告警；容器就绪后重试即可
    try:
        await ensure_index(get_es())
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] ES 索引初始化失败（检查 ES 是否已启动）: {exc}")
    try:
        async with AsyncSessionLocal() as session:
            await ensure_seed_data(session)
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] 种子数据初始化失败（检查 PG 是否已启动）: {exc}")
    yield
    await close_es()
    # 释放连接池（避免 TestClient 跨模块复用已绑定旧事件循环的连接）
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="RAG Knowledge Base API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
