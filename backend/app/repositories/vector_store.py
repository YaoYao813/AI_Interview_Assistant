from app.core.config import settings
from app.repositories.base_vector_store import BaseVectorStore, DocumentChunk, DocumentInfo, SearchResult
from app.repositories.chroma_vector_store import ChromaVectorStore

# 向后兼容别名
VectorStoreRepository = ChromaVectorStore

_vector_store_instance: ChromaVectorStore | None = None


def get_vector_store() -> ChromaVectorStore:
    global _vector_store_instance
    if _vector_store_instance is None:
        _vector_store_instance = ChromaVectorStore(
            settings.CHROMA_PERSIST_DIR, settings.CHROMA_COLLECTION
        )
    return _vector_store_instance


def reset_vector_store() -> None:
    global _vector_store_instance
    _vector_store_instance = None
