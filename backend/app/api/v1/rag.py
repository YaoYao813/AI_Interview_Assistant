"""
RAG 问答 API 路由
职责：知识问答（非流式 + SSE 流式）
"""
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_rag_svc
from app.models.common import ApiResponse
from app.models.knowledge import ChatRequest
from app.services.rag_service import RAGService

router = APIRouter(prefix="/rag", tags=["RAG 问答"])


@router.post("/chat", response_model=ApiResponse)
async def chat(
    req: ChatRequest,
    rag_svc: RAGService = Depends(get_rag_svc),
):
    history_dicts = [h.model_dump() for h in req.history] if req.history else None
    result = await rag_svc.answer(
        question=req.question,
        top_k=req.top_k,
        threshold=req.threshold,
        history=history_dicts,
    )
    return ApiResponse(data=result)


@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    rag_svc: RAGService = Depends(get_rag_svc),
):
    history_dicts = [h.model_dump() for h in req.history] if req.history else None
    return StreamingResponse(
        rag_svc.answer_stream(
            question=req.question,
            top_k=req.top_k,
            threshold=req.threshold,
            history=history_dicts,
        ),
        media_type="text/event-stream",
    )
