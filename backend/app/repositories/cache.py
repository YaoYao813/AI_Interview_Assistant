import redis.asyncio as redis


class CacheRepository:
    def __init__(self, redis_url: str):
        self.redis = redis.from_url(redis_url, decode_responses=True)

    async def get(self, key: str) -> str | None:
        return await self.redis.get(key)

    async def set(self, key: str, value: str, ttl: int = 3600):
        await self.redis.set(key, value, ex=ttl)

    async def delete(self, key: str):
        await self.redis.delete(key)

    async def ping(self) -> bool:
        """健康探针：Redis 可达返回 True，不可达则抛异常（交给调用方判定）"""
        return await self.redis.ping()
