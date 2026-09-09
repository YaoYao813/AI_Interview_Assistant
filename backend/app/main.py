import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_v1_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.repositories.cache import CacheRepository
from app.repositories.vector_store import VectorStoreRepository

logger = logging.getLogger(__name__)


def _ensure_dirs() -> None:
    """确保数据目录存在，失败不阻塞启动"""
    for dir_path in (settings.UPLOAD_DIR, settings.CHROMA_PERSIST_DIR):
        try:
            os.makedirs(dir_path, exist_ok=True)
        except OSError as exc:
            logger.warning("无法创建目录 %s: %s", dir_path, exc)


def _setup_logging() -> None:
    level = logging.DEBUG if settings.DEBUG else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- Startup ----
    _setup_logging()
    logger.info("%s v%s 启动中...", settings.PROJECT_NAME, settings.VERSION)
    logger.info("LLM Model: %s", settings.LLM_MODEL)
    logger.info("Redis: %s:%s", settings.REDIS_HOST, settings.REDIS_PORT)
    logger.info("Chroma: %s", settings.CHROMA_PERSIST_DIR)

    _ensure_dirs()

    # 挂载共享资源到 app.state，供 deps 或路由直接使用
    app.state.cache = CacheRepository(settings.REDIS_URL)
    app.state.vector_store = VectorStoreRepository(
        settings.CHROMA_PERSIST_DIR, settings.CHROMA_COLLECTION
    )

    yield

    # ---- Shutdown ----
    await app.state.cache.redis.close()
    logger.info("%s 已关闭", settings.PROJECT_NAME)


def create_app() -> FastAPI:

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        lifespan=lifespan,
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_v1_router, prefix="/api/v1")
    register_exception_handlers(app)

    @app.get("/health", tags=["系统"])
    async def health_check():
        return {
            "status": "ok",
            "service": settings.PROJECT_NAME,
            "version": settings.VERSION,
        }

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
