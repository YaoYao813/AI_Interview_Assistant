"""
API 依赖注入
类比 Spring 的 @Autowired / @Bean

FastAPI 的 Depends() 机制：
  - 每个请求自动调用工厂函数，注入 Service 实例
  - 支持替换（测试时 override）
"""
from app.services.knowledge_service import get_knowledge_service, KnowledgeService
from app.services.rag_service import get_rag_service, RAGService
from app.services.resume_service import ResumeService, get_resume_service


def get_knowledge_svc() -> KnowledgeService:
    """注入 KnowledgeService"""
    return get_knowledge_service()


def get_rag_svc() -> RAGService:
    """注入 RAGService"""
    return get_rag_service()


def get_resume_svc() -> ResumeService:
    return get_resume_service()