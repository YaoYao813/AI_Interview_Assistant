"""
知识库模块 Pydantic 模型（请求/响应）
类比 Java 的 DTO/VO
"""
from typing import Optional
from pydantic import BaseModel, Field


# ========== 请求模型 ==========

class HistoryMessage(BaseModel):
    """历史消息"""
    role: str = "user"
    content: str = ""


class ChatRequest(BaseModel):
    """RAG 问答请求"""
    question: str = Field(..., min_length=1, max_length=2000, description="用户问题")
    top_k: int = Field(default=5, ge=1, le=20, description="返回文档块数量")
    threshold: float = Field(default=0.3, ge=0.0, le=1.0, description="相似度阈值（0=不过滤）")
    history: list[HistoryMessage] = Field(default=[], description="对话历史（最近N条）")


# ========== 响应模型 ==========

class SourceInfo(BaseModel):
    """引用来源信息"""
    index: int
    document: str
    content: str
    similarity: Optional[float] = None


class ChatResponse(BaseModel):
    """RAG 问答响应"""
    answer: str
    sources: list[SourceInfo] = []
    has_knowledge: bool = False
    token_count: int = 0


class DocumentUploadResponse(BaseModel):
    """文档上传响应"""
    document_id: str
    filename: str
    chunk_count: int
    status: str


class DocumentItem(BaseModel):
    """文档列表项"""
    document_id: str
    filename: str
    chunk_count: int
    created_at: str = ""


class DocumentListResponse(BaseModel):
    """文档列表响应"""
    documents: list[DocumentItem]
    total: int


class StatisticResponse(BaseModel):
    """知识库统计响应"""
    document_count: int
    chunk_count: int


class DeleteResponse(BaseModel):
    """删除响应"""
    success: bool = True
    affected_count: int = 0
