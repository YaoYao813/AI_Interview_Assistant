import hashlib
import json
import logging

from app.models.roadmap import RoadmapResult, RoadmapStep
from app.repositories.cache import CacheRepository
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)

# 路线图内容只由 (目标岗位, 简历) 决定，且这是本项目最贵的 LLM 路径之一
# （要求输出大块结构化 JSON，前端超时给到 180s）。同一份输入反复生成既浪费 token
# 又让用户干等几分钟，缓存一天足够 —— 学习路线本身不会在一天内变化。
ROADMAP_CACHE_PREFIX = "learning:roadmap:"
ROADMAP_CACHE_TTL = 86400


def _roadmap_cache_key(target_role: str, resume_text: str) -> str:
    # 简历最长 15000 字，直接拼进 key 会让 Redis 里存一份冗长的键；
    # 摘要后长度固定，也顺带把换行等对 key 不友好的字符挡在外面。
    # 岗位长度前缀是为了消除拼接歧义：一段文本里的换行会让两个不同字段的边界
    # 无法还原，("a", "b\nc") 和 ("a\nb", "c") 就会撞进同一个 key。
    digest = hashlib.sha256(
        f"{len(target_role)}:{target_role}\n{resume_text}".encode("utf-8")
    ).hexdigest()
    return f"{ROADMAP_CACHE_PREFIX}{digest[:32]}"


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

    def __init__(self, cache: CacheRepository | None = None):
        self.llm = LLMService()
        # cache 由 deps.get_learning_svc 在每个请求上赋值，不作为构造参数固定下来：
        # 单例存在的理由只是复用构造昂贵的 LLMService，若把 cache 冻在首次构造时，
        # 任何在请求之前碰到单例的代码（测试、脚本、以后新增的调用点）都会让缓存
        # 静默失效 —— 不报错、只是永远不命中，这类问题很难被发现。
        self.cache = cache

    async def generate_roadmap(
        self,
        target_role: str,
        resume_text: str = "",
    ) -> RoadmapResult:
        cached = await self._load_cached(target_role, resume_text)
        if cached is not None:
            return cached

        user_message = f"目标岗位：{target_role}\n\n"
        if resume_text:
            user_message += f"我的简历内容：\n{resume_text}\n\n"
        user_message += "请分析差距并生成学习路线图。"

        data = await self.llm.chat_json(ROADMAP_SYSTEM_PROMPT, user_message)
        result = RoadmapResult(
            target_role=data.get("target_role", target_role),
            steps=[RoadmapStep(**s) for s in data.get("steps", [])],
        )

        await self._store_cached(target_role, resume_text, result)
        return result

    async def _load_cached(self, target_role: str, resume_text: str) -> RoadmapResult | None:
        if self.cache is None:
            return None
        try:
            raw = await self.cache.get(_roadmap_cache_key(target_role, resume_text))
        except Exception as exc:
            # Redis 挂掉不该把「生成路线」这个原本不依赖 Redis 的功能一起拖下水，
            # 降级成未命中，照常走 LLM。
            logger.warning("学习路线缓存读取失败，按未命中处理: %s", exc)
            return None
        if raw is None:
            return None
        try:
            return RoadmapResult(**json.loads(raw))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            # 结构对不上（字段改名、旧版本残留）就当没缓存，而不是把坏数据抛给用户。
            # ValidationError 是 ValueError 的子类；TypeError 覆盖「合法 JSON 但不是对象」
            # （顶层是数组 / 数字时 `**` 展开会直接炸）。
            logger.warning("学习路线缓存数据损坏，按未命中处理: %s", exc)
            return None

    async def _store_cached(
        self, target_role: str, resume_text: str, result: RoadmapResult
    ) -> None:
        if self.cache is None:
            return
        try:
            await self.cache.set(
                _roadmap_cache_key(target_role, resume_text),
                json.dumps(result.model_dump(), ensure_ascii=False),
                ttl=ROADMAP_CACHE_TTL,
            )
        except Exception as exc:
            # 写不进去只是这次没省下 token，用户已经拿到结果了，不能为此报错。
            logger.warning("学习路线缓存写入失败: %s", exc)

    async def analyze_gaps(
        self,
        target_role: str,
        resume_text: str,
    ) -> dict:
        system_prompt = """分析目标岗位与用户当前技能之间的差距。
返回 JSON：{"matched_skills": [...], "missing_skills": [...], "suggestion": "总体建议"}"""
        user_message = f"目标岗位：{target_role}\n简历内容：\n{resume_text}"
        return await self.llm.chat_json(system_prompt, user_message)


# ===== 全局单例 =====
_learning_service_instance: LearningService | None = None


def get_learning_service() -> LearningService:
    """获取 LearningService 单例（只复用 LLMService，缓存由调用方按请求注入）"""
    global _learning_service_instance
    if _learning_service_instance is None:
        _learning_service_instance = LearningService()
    return _learning_service_instance


def reset_learning_service() -> None:
    """重置单例（测试用）"""
    global _learning_service_instance
    _learning_service_instance = None
