from abc import ABC, abstractmethod
from dataclasses import dataclass, field


# ========== 数据模型 ==========

@dataclass
class DocumentChunk:
    """
    文档块（存储和检索的原子单元）
    类比 Chroma 中一条记录的标准化表示
    """
    chunk_id: str
    content: str
    metadata: dict = field(default_factory=dict)
    similarity: float | None = None  # 检索时填充，存储时为 None

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "content": self.content,
            "metadata": self.metadata,
            "similarity": self.similarity,
        }

    @classmethod
    def from_chroma(cls, doc_id: str, document: str, metadata: dict, distance: float) -> "DocumentChunk":
        return cls(
            chunk_id=doc_id,
            content=document,
            metadata=metadata or {},
            similarity=round(1 - distance, 4),
        )


@dataclass
class SearchResult:
    """搜索结果集合"""
    hits: list[DocumentChunk] = field(default_factory=list)
    total: int = 0
    query: str = ""


class DocumentInfo:
    """文档概要信息（列表展示用，不含全文）"""

    def __init__(
        self,
        document_id: str,
        filename: str,
        chunk_count: int,
        created_at: str = "",
        file_size: int | None = None,
    ):
        self.document_id = document_id
        self.filename = filename
        self.chunk_count = chunk_count
        self.created_at = created_at
        # 老数据没有这条 metadata，为 None（前端显示「—」而不是 0）
        self.file_size = file_size

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "chunk_count": self.chunk_count,
            "created_at": self.created_at,
            "file_size": self.file_size,
        }


# ========== 抽象基类 ==========

class BaseVectorStore(ABC):
    """向量数据库抽象基类"""

    @abstractmethod
    async def add_documents(
        self,
        chunks: list[dict],
        document_id: str,
        filename: str,
        file_size: int | None = None,
    ) -> int:
        """
        将文本块向量化并存储

        Args:
            chunks: [{"content": str, "chunk_index": int, ...}, ...]
            document_id: 文档唯一 ID
            filename: 原始文件名
            file_size: 原始文件字节数，写入文档级 metadata

        Returns:
            实际存储的文本块数量
        """
        ...

    @abstractmethod
    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        threshold: float = 0.3,
    ) -> SearchResult:
        """
        语义搜索

        Args:
            query_embedding: 查询向量
            top_k: 返回结果数
            threshold: 绝对相似度底线，低于此值不返回（0=不过滤）
                       RETRIEVAL_RELATIVE_RATIO>0 时实际底线会抬到该比例 × top1

        Returns:
            SearchResult: hits 为 DocumentChunk 列表
        """
        ...

    @abstractmethod
    def delete_document(self, document_id: str) -> int:
        """删除文档及其所有文本块，返回实际删除的块数"""
        ...

    @abstractmethod
    def get_document_stats(self) -> dict:
        """文档级汇总：{"document_count", "sized_document_count", "total_size"}

        一次扫描算完，别为「总大小」再扫一遍。
        """
        ...

    @abstractmethod
    def get_chunk_count(self) -> int:
        """获取文本块总数"""
        ...

    @abstractmethod
    def list_documents(
        self,
        limit: int = 20,
        offset: int = 0,
        keyword: str = "",
        extension: str | None = None,
    ) -> tuple[list[DocumentInfo], int]:
        """分页列出文档概要信息，返回 (当前页, 过滤后的总数)

        keyword 按文件名子串匹配，extension 按扩展名（如 ".pdf"）匹配。
        total 是过滤后的数量，供前端分页器使用。
        """
        ...

    @abstractmethod
    def health_check(self) -> dict:
        """健康检查（应保持轻量：会被高频探测调用，别做全量扫描）"""
        ...
