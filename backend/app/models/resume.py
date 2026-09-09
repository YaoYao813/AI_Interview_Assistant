from pydantic import BaseModel, Field


class ResumeChatRequest(BaseModel):
    """简历对话追问请求"""
    resume_text: str = Field(..., min_length=20, max_length=15000, description="简历原始文本")
    analysis_result: dict = Field(..., description="上一步的分析报告")
    message: str = Field(..., min_length=1, max_length=2000, description="用户追问")
    history: list[dict] = Field(default_factory=list, description="本轮历史的最近 N 条消息")
