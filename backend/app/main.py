import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_v1_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.repositories.cache import CacheRepository
from app.repositories.vector_store import VectorStoreRepository

logger = logging.getLogger(__name__)

# 单次依赖探测的超时：探测本身不能成为新的挂起源，
# Redis 半死不活（连得上但不回包）时必须靠自己超时中断。
DEPENDENCY_PROBE_TIMEOUT = 2.0


def _describe_exception(exc: Exception) -> str:
    """带上异常类型名：连接类异常的 str() 往往是空串，
    只写 `error: ` 的探针在排障时等于什么都没说。"""
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


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
    async def health_check(response: Response):
        """readiness 探针：真探依赖，任一不可用即 503。

        和 liveness 的区别：liveness 只问「进程还活着吗」，所以无条件 ok；
        readiness 问「现在能接流量吗」——依赖挂了就不能报 ok，
        否则编排器会继续把请求打到一个必然 500 的实例上。
        注意健康时返回 200 但 body 里也有 dependencies，排查时一眼能看出哪个挂了。
        """
        dependencies: dict[str, str] = {}

        try:
            await asyncio.wait_for(
                app.state.cache.ping(), timeout=DEPENDENCY_PROBE_TIMEOUT
            )
            dependencies["redis"] = "ok"
        except Exception as exc:
            logger.warning("健康检查：Redis 不可用: %s", exc)
            dependencies["redis"] = f"error: {_describe_exception(exc)}"

        try:
            app.state.vector_store.health_check()
            dependencies["vector_store"] = "ok"
        except Exception as exc:
            logger.warning("健康检查：向量库不可用: %s", exc)
            dependencies["vector_store"] = f"error: {_describe_exception(exc)}"

        healthy = all(v == "ok" for v in dependencies.values())
        if not healthy:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

        return {
            "status": "ok" if healthy else "degraded",
            "service": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "dependencies": dependencies,
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
