from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import StreamingResponse

from app.api.deps import get_resume_svc
from app.models.common import ApiResponse
from app.models.resume import ResumeChatRequest
from app.services.resume_service import ResumeService

router = APIRouter(prefix="/resume", tags=["简历分析"])


@router.post("/analyse", response_model=ApiResponse)
async def analyse(
    file: UploadFile = File(...),
    resume_svc: ResumeService = Depends(get_resume_svc),
):
    content = await file.read()
    result = await resume_svc.analyze_from_bytes(content, file.filename or "resume.pdf")
    return ApiResponse(data=result)


@router.post("/chat", response_model=ApiResponse)
async def chat(
    req: ResumeChatRequest,
    resume_svc: ResumeService = Depends(get_resume_svc),
):
    reply = await resume_svc.chat(
        resume_text=req.resume_text,
        analysis_result=req.analysis_result,
        message=req.message,
        history=req.history,
    )
    return ApiResponse(data={"reply": reply})


@router.post("/chat/stream")
async def chat_stream(
    req: ResumeChatRequest,
    resume_svc: ResumeService = Depends(get_resume_svc),
):
    return StreamingResponse(
        resume_svc.chat_stream(
            resume_text=req.resume_text,
            analysis_result=req.analysis_result,
            message=req.message,
            history=req.history,
        ),
        media_type="text/event-stream",
    )
