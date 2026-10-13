"""
Agent 对话 API 路由（阶段 3.4）

新增入口：POST /api/v1/agent/chat
旧端点（/rag/chat、/rag/chat/stream）一行不动——新功能一律走新入口。
"""
from fastapi import APIRouter, Depends

from app.api.deps import get_agent_svc
from app.models.agent import AgentChatRequest
from app.models.common import ApiResponse
from app.services.agent_service import AgentService

router = APIRouter(prefix="/agent", tags=["Agent 对话"])


@router.post("/chat", response_model=ApiResponse)
async def chat(
    req: AgentChatRequest,
    agent_svc: AgentService = Depends(get_agent_svc),
):
    """带工具的对话：模型自行决定是否调用知识库检索 / 简历分析 / 回答评分。

    非流式——工具轮次对用户不可见，只有最终答案是文本，没有可流的内容。
    """
    history = [h.model_dump() for h in req.history] if req.history else None
    result = await agent_svc.run(
        message=req.message,
        resume_text=req.resume_text,
        history=history,
    )
    return ApiResponse(data=result)
