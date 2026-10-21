"""面试 Agent 请求模型（阶段 4）

只服务 /interview/agent/* 动态追问端点，与旗舰 /interview/* 的模型互不影响。
"""
from pydantic import BaseModel, Field


class AgentAnswerRequest(BaseModel):
    """候选人作答一轮"""
    session_id: str = Field(..., min_length=1, max_length=64)
    answer: str = Field(..., min_length=1, max_length=8000)


class AgentReportRequest(BaseModel):
    """结题报告"""
    session_id: str = Field(..., min_length=1, max_length=64)
