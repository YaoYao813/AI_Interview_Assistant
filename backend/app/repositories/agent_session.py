"""Agent 面试会话存储（Redis）

与旗舰的 SessionRepository（`interview:session:`）**刻意分开**：本仓库服务「动态追问」Agent
（阶段 4），key 前缀独立为 `interview:agent:`，两种会话永不互相覆盖。

形状照抄 SessionRepository，只换前缀与日志文案——**不参数化旗舰仓库**，避免为了复用一行
key 拼接而去改动已验证的线性面试流程。领域模型不同（见 InterviewAgentService 里的 session JSON），
本就该是两个仓库。
"""
import json
import logging

from app.repositories.cache import CacheRepository

logger = logging.getLogger(__name__)


class AgentSessionRepository:
    """Agent 面试会话的领域化存取，内部复用通用 CacheRepository"""

    KEY_PREFIX = "interview:agent:"
    DEFAULT_TTL = 1800  # 30 分钟，与线性面试一致

    def __init__(self, cache: CacheRepository):
        self.cache = cache

    def _key(self, session_id: str) -> str:
        return f"{self.KEY_PREFIX}{session_id}"

    async def save_session(self, session_id: str, session: dict, ttl: int = DEFAULT_TTL) -> None:
        await self.cache.set(
            self._key(session_id),
            json.dumps(session, ensure_ascii=False),
            ttl=ttl,
        )

    async def get_session(self, session_id: str) -> dict | None:
        raw = await self.cache.get(self._key(session_id))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Agent 面试会话数据损坏: %s", session_id)
            return None

    async def delete_session(self, session_id: str) -> None:
        await self.cache.delete(self._key(session_id))
