"""
API 依赖注入
类比 Spring 的 @Autowired / @Bean

FastAPI 的 Depends() 机制：
  - 每个请求自动调用工厂函数，注入 Service 实例
  - 支持替换（测试时 override）
"""
from fastapi import Depends, Request

from app.repositories.cache import CacheRepository
from app.services.knowledge_service import get_knowledge_service, KnowledgeService
from app.services.rag_service import get_rag_service, RAGService
from app.services.resume_service import ResumeService, get_resume_service
from app.services.learning_service import LearningService, get_learning_service
from app.services.interview_service import InterviewService


def get_knowledge_svc() -> KnowledgeService:
    """注入 KnowledgeService"""
    return get_knowledge_service()


def get_rag_svc() -> RAGService:
    """注入 RAGService"""
    return get_rag_service()


def get_resume_svc() -> ResumeService:
    return get_resume_service()


def get_cache(request: Request) -> CacheRepository:
    """注入 Redis 缓存仓库（挂在 app.state.cache）"""
    return request.app.state.cache


def get_learning_svc(cache: CacheRepository = Depends(get_cache)) -> LearningService:
    """注入 LearningService（依赖 Redis 缓存路线图生成结果）

    cache 挂在单例上而不是构造时传入：单例只为了复用昂贵的 LLMService，
    若缓存只在首次构造时生效，先碰到单例的代码会让缓存静默失效。
    app.state.cache 全进程唯一，每次请求重复赋值是幂等的。
    """
    svc = get_learning_service()
    svc.cache = cache
    return svc


def get_interview_svc(cache: CacheRepository = Depends(get_cache)) -> InterviewService:
    """注入 InterviewService（依赖 Redis 缓存）"""
    return InterviewService(cache=cache)
