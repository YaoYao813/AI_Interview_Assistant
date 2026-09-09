from fastapi import APIRouter

from app.models.common import ApiResponse
from app.models.interview import InterviewRequest
from app.services.interview_service import InterviewService

router = APIRouter(prefix="/interview", tags=["模拟面试"])


@router.post("/start", response_model=ApiResponse)
async def start_interview(req: InterviewRequest):
    service = InterviewService()
    result = await service.start_session(req)
    return ApiResponse(data=result)


@router.post("/evaluate", response_model=ApiResponse)
async def evaluate_answer(session_id: str, question: str, answer: str):
    service = InterviewService()
    result = await service.evaluate(session_id, question, answer)
    return ApiResponse(data=result)
