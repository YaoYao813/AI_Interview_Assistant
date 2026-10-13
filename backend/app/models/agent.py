"""Agent 对话模块的 Pydantic 模型（请求）"""
from pydantic import BaseModel, Field

from app.models.knowledge import HistoryMessage


class AgentChatRequest(BaseModel):
    """Agent 对话请求。

    无状态：请求级数据（简历文本、历史）全部随请求带回，服务端不存会话。
    会话（Redis）集成留给阶段 4 的「模拟面试动态追问」——那时才有真正的需求。
    """

    message: str = Field(..., min_length=1, max_length=2000, description="用户本轮消息")
    resume_text: str | None = Field(
        default=None,
        max_length=15000,
        description="简历文本（可选）。简历不在会话里，需要 analyse_resume 时随请求带回",
    )
    history: list[HistoryMessage] = Field(
        default_factory=list, description="对话历史（最近 N 条）"
    )
