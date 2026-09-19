from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse

from app.api.deps import get_interview_svc
from app.models.common import ApiResponse
from app.models.interview import EvaluateRequest, InterviewRequest
from app.services.interview_service import InterviewService

router = APIRouter(prefix="/interview", tags=["模拟面试"])


@router.post("/start", response_model=ApiResponse)
async def start_interview(
    role: str = Form(...),
    topics: str = Form(""),
    difficulty: str = Form("medium"),
    file: UploadFile | None = File(None),
    interview_svc: InterviewService = Depends(get_interview_svc),
):
    resume_text = ""
    if file is not None and file.filename:
        content = await file.read()
        resume_text = await interview_svc.parse_resume(content, file.filename)

    req = InterviewRequest(
        role=role,
        topics=[t.strip() for t in topics.split(",") if t.strip()],
        difficulty=difficulty,
        resume_text=resume_text,
    )
    result = await interview_svc.start_session(req)
    return ApiResponse(data=result)


@router.post("/evaluate", response_model=ApiResponse)
async def evaluate_answer(
    req: EvaluateRequest,
    interview_svc: InterviewService = Depends(get_interview_svc),
):
    result = await interview_svc.evaluate(req.session_id, req.answer)
    return ApiResponse(data=result)


@router.post("/evaluate/stream")
async def evaluate_answer_stream(
    req: EvaluateRequest,
    interview_svc: InterviewService = Depends(get_interview_svc),
):
    # 会话校验在建立流之前完成，无效会话仍返回 404
    generator = await interview_svc.prepare_evaluate_stream(req.session_id, req.answer)
    return StreamingResponse(generator, media_type="text/event-stream")
