"""
API v1 路由聚合
所有子模块路由在这里统一注册
"""
from fastapi import APIRouter

from app.api.v1.interview import router as interview_router
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.rag import router as rag_router
from app.api.v1.resume import router as resume_router
from app.api.v1.roadmap import router as roadmap_router

api_v1_router = APIRouter()

api_v1_router.include_router(knowledge_router)
api_v1_router.include_router(rag_router)
api_v1_router.include_router(interview_router)
api_v1_router.include_router(resume_router)
api_v1_router.include_router(roadmap_router)


@api_v1_router.get("/ping")
async def ping():
    """API v1 联通性测试"""
    return {"message": "pong", "version": "v1"}
