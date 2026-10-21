"""模拟面试「动态追问」Agent 端点（阶段 4）

纯新增入口 /interview/agent/*：
  - 与旗舰 /interview/* 的【线性】流程并存，互不复用、互不影响。
  - 会话校验放在「建立 SSE 流之前」，无效会话仍返回真 404（照抄旗舰 prepare_evaluate_stream）。
"""
from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse

from app.api.deps import get_interview_agent_svc, get_interview_svc
from app.models.common import ApiResponse
from app.models.interview_agent import AgentAnswerRequest, AgentReportRequest
from app.services.interview_agent_service import InterviewAgentService
from app.services.interview_service import InterviewService

router = APIRouter(prefix="/interview/agent", tags=["模拟面试 Agent"])


@router.post("/start", response_model=ApiResponse)
async def start_agent_interview(
    role: str = Form(...),
    jd: str = Form(""),
    difficulty: str = Form("medium"),
    file: UploadFile | None = File(None),
    agent_svc: InterviewAgentService = Depends(get_interview_agent_svc),
    interview_svc: InterviewService = Depends(get_interview_svc),
):
    # 复用旗舰的简历解析（纯文件→文本，无会话状态），不复制 PDF 逻辑
    resume_text = ""
    if file is not None and file.filename:
        content = await file.read()
        resume_text = await interview_svc.parse_resume(content, file.filename)

    result = await agent_svc.start(
        role=role,
        jd_text=jd,
        difficulty=difficulty,
        resume_text=resume_text,
    )
    return ApiResponse(data=result)


@router.post("/answer/stream")
async def answer_agent_interview(
    req: AgentAnswerRequest,
    agent_svc: InterviewAgentService = Depends(get_interview_agent_svc),
):
    # 会话校验在建立流之前完成，无效会话仍返回 404
    generator = await agent_svc.answer_stream(req.session_id, req.answer)
    return StreamingResponse(generator, media_type="text/event-stream")


@router.post("/report", response_model=ApiResponse)
async def agent_interview_report(
    req: AgentReportRequest,
    agent_svc: InterviewAgentService = Depends(get_interview_agent_svc),
):
    result = await agent_svc.report(req.session_id)
    return ApiResponse(data=result)
