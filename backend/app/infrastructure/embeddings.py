from abc import ABC, abstractmethod
from openai import AsyncOpenAI
from app.core.config import settings

class BaseEmbedding(ABC):
    """Embedding 抽象基类，定义接口契约"""

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]:
        ...

    @abstractmethod
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...


class OpenAIEmbedding(BaseEmbedding):
    """基于 OpenAI 兼容 API 的 Embedding 实现"""

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.EMBEDDING_API_KEY,
            base_url=settings.EMBEDDING_BASE_URL,
            timeout=settings.LLM_REQUEST_TIMEOUT,
            max_retries=3,
        )
        self.model = settings.EMBEDDING_MODEL
        self.dimension = getattr(settings, "EMBEDDING_DIMENSION", 1024)

    async def embed_query(self, text: str) -> list[float]:
        results = await self.embed_documents([text])
        return results[0]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self.client.embeddings.create(model=self.model, input=texts)
        return [d.embedding for d in response.data]

    @property
    def model_name(self) -> str:
        return self.model


class LocalEmbedding(BaseEmbedding):
    """本地 Embedding 模型占位实现（未来扩展）"""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        raise NotImplementedError("本地 Embedding 模型尚未接入，请使用 OpenAIEmbedding")

    async def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


# ===== 全局单例 =====
_embedding_instance: BaseEmbedding | None = None

def get_embedding() -> BaseEmbedding:
    global _embedding_instance
    if _embedding_instance is None:
        _embedding_instance = OpenAIEmbedding()
    return _embedding_instance


def reset_embedding() -> None:
    global _embedding_instance
    _embedding_instance = None
