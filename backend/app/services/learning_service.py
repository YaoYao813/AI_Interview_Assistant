from app.models.roadmap import RoadmapResult, RoadmapStep
from app.services.llm_service import LLMService


ROADMAP_SYSTEM_PROMPT = """你是一位资深的职业规划导师和技术教练。你的任务是根据用户的简历内容和目标岗位，
分析技能差距并生成一份结构化的学习路线图。

要求：
1. 分析目标岗位所需的核心技能
2. 对比用户现有简历中的技能，找出差距
3. 生成 5-10 个学习步骤，按优先级排序
4. 每个步骤需包含：主题、描述、推荐学习资源

请严格以 JSON 格式返回，结构如下：
{
  "target_role": "目标岗位",
  "steps": [
    {
      "topic": "学习主题",
      "description": "详细描述该步骤需要掌握的内容",
      "resources": ["推荐资源1", "推荐资源2"]
    }
  ]
}"""


class LearningService:
    """学习路线生成服务"""

    def __init__(self):
        self.llm = LLMService()

    async def generate_roadmap(
        self,
        target_role: str,
        resume_text: str = "",
    ) -> RoadmapResult:
        user_message = f"目标岗位：{target_role}\n\n"
        if resume_text:
            user_message += f"我的简历内容：\n{resume_text}\n\n"
        user_message += "请分析差距并生成学习路线图。"

        data = await self.llm.chat_json(ROADMAP_SYSTEM_PROMPT, user_message)
        return RoadmapResult(
            target_role=data.get("target_role", target_role),
            steps=[RoadmapStep(**s) for s in data.get("steps", [])],
        )

    async def analyze_gaps(
        self,
        target_role: str,
        resume_text: str,
    ) -> dict:
        system_prompt = """分析目标岗位与用户当前技能之间的差距。
返回 JSON：{"matched_skills": [...], "missing_skills": [...], "suggestion": "总体建议"}"""
        user_message = f"目标岗位：{target_role}\n简历内容：\n{resume_text}"
        return await self.llm.chat_json(system_prompt, user_message)
