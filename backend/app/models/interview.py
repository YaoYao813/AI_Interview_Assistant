from pydantic import BaseModel, Field


class InterviewRequest(BaseModel):
    """开始面试请求"""
    role: str = Field(..., min_length=1, max_length=100, description="目标岗位")
    topics: list[str] = Field(default_factory=list, description="重点考察方向（可选）")
    difficulty: str = Field("medium", description="难度：easy/medium/hard")
    resume_text: str = Field("", max_length=15000, description="简历文本（用于基于简历出题）")


class EvaluateRequest(BaseModel):
    """答题评价请求"""
    session_id: str = Field(..., min_length=1, description="会话ID")
    answer: str = Field(..., min_length=1, max_length=8000, description="候选人回答")
