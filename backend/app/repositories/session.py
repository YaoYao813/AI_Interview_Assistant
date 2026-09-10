"""面试会话存储（Redis）

封装面试 session 在 Redis 中的序列化与 key 规范，
上层 InterviewService 只关心 dict 的读写，不感知存储细节。
"""
import json
import logging

from app.repositories.cache import CacheRepository

logger = logging.getLogger(__name__)


class SessionRepository:
    """面试会话的领域化存取，内部复用通用 CacheRepository"""

    KEY_PREFIX = "interview:session:"
    DEFAULT_TTL = 1800  # 30 分钟

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
            logger.warning("面试会话数据损坏: %s", session_id)
            return None

    async def delete_session(self, session_id: str) -> None:
        await self.cache.delete(self._key(session_id))
