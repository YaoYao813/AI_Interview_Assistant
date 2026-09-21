"""
知识库管理 API 路由
职责：文档上传、删除、列表、统计
"""
from fastapi import APIRouter, Depends, File, Query, UploadFile

from app.api.deps import get_knowledge_svc
from app.models.common import ApiResponse
from app.services.knowledge_service import KnowledgeService

router = APIRouter(prefix="/knowledge", tags=["知识库管理"])


@router.post("/upload", response_model=ApiResponse)
async def upload_document(
    file: UploadFile = File(...),
    knowledge_svc: KnowledgeService = Depends(get_knowledge_svc),
):
    content = await file.read()
    result = await knowledge_svc.upload_document_from_bytes(content, file.filename)
    return ApiResponse(data=result)


@router.get("/documents", response_model=ApiResponse)
async def list_documents(
    limit: int = Query(20, ge=1, le=200, description="每页条数"),
    offset: int = Query(0, ge=0, description="偏移量"),
    keyword: str = Query("", description="按文件名子串过滤"),
    format: str = Query("", description="按扩展名过滤，如 .pdf"),
    knowledge_svc: KnowledgeService = Depends(get_knowledge_svc),
):
    result = knowledge_svc.list_documents(
        limit=limit,
        offset=offset,
        keyword=keyword,
        extension=format or None,
    )
    return ApiResponse(data=result)


@router.delete("/documents/{document_id}", response_model=ApiResponse)
async def delete_document(
    document_id: str,
    knowledge_svc: KnowledgeService = Depends(get_knowledge_svc),
):
    affected = knowledge_svc.delete_document(document_id)
    return ApiResponse(data={
        "success": True,
        "affected_count": affected,
    })


@router.get("/statistics", response_model=ApiResponse)
async def get_statistics(
    knowledge_svc: KnowledgeService = Depends(get_knowledge_svc),
):
    result = knowledge_svc.get_statistics()
    return ApiResponse(data=result)
