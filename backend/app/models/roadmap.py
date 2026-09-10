from pydantic import BaseModel, Field


class RoadmapRequest(BaseModel):
    """学习路线生成请求"""
    target_role: str = Field(..., min_length=1, max_length=100, description="目标岗位")
    resume_text: str = Field("", max_length=15000, description="简历文本（可选）")


class RoadmapStep(BaseModel):
    topic: str
    description: str
    resources: list[str] = []


class RoadmapResult(BaseModel):
    target_role: str
    steps: list[RoadmapStep]
