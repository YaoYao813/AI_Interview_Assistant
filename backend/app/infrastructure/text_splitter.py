import re
from abc import abstractmethod, ABC

from langchain_core.documents import Document as LCDocument
from langchain_text_splitters import RecursiveCharacterTextSplitter as LangChainRecursiveSplitter
from app.core.config import settings

# ========== 默认配置 ==========
# 递归分割的优先级顺序（按语义边界从粗到细）
DEFAULT_SEPARATORS: list[str] = [
    "\n\n",      # 1. 段落边界（最高优先级）
    "\n",        # 2. 行边界
    "。",        # 3. 中文句号
    "！",        # 4. 中文感叹号
    "？",        # 5. 中文问号
    "；",        # 6. 中文分号
    ".",         # 7. 英文句号
    " ",         # 8. 空格（英文词边界）
    "",          # 9. 字符级别（兜底，保证不超过 chunk_size）
]
DEFAULT_CHUNK_SIZE: int = 1000
DEFAULT_CHUNK_OVERLAP: int = 200


# ========== 抽象基类 ==========
class TextSplitter(ABC):
    """文本切片器抽象基类"""
    @abstractmethod
    def split_text(self, text: str) -> list[dict]:
        """
        将纯文本切分为块，返回纯 dict 结构
        Returns:
            [{"content": str, "chunk_index": int, "chunk_size": int, "start_index": int}, ...]
        """
        ...
    @abstractmethod
    def split_documents(self, text: str, metadata: dict | None = None) -> list[LCDocument]:
        """
        将文本切分为 LangChain Document 对象（用于 Chroma 批量添加）
        """
        ...
    @abstractmethod
    def estimate_chunk_count(self, text: str) -> int:
        """估算切分后的块数（不实际切分）"""
        ...


# 默认切分策略
class RecursiveTextSplitter(TextSplitter):
    """
    递归字符切分器（默认策略）
    封装 LangChain 的 RecursiveCharacterTextSplitter。
    按 separators 列表顺序尝试分割，优先保留段落边界。
    适用场景：通用文档（PDF/DOCX/TXT），大多数情况的默认选择
    """
    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
        separators: list[str] | None = None,
    ):
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._separators = separators or DEFAULT_SEPARATORS
        self._splitter = LangChainRecursiveSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=self._separators,
            length_function=len,
            keep_separator=True,        # 保留分隔符在块末尾，保持语义完整
            add_start_index=True,       # 记录每个 chunk 在原文本中的起始位置
            strip_whitespace=True,
        )

    def split_text(self, text: str) -> list[dict]:
        if not text or not text.strip():
            return []
        raw_chunks = self._splitter.split_text(text)
        result = []
        for i, chunk_text in enumerate(raw_chunks):
            chunk_text = chunk_text.strip()
            if not chunk_text:
                continue
            # 前 50 字符定位起始位置（近似值，足够用）
            start_index = text.index(chunk_text[:50]) if len(chunk_text) > 50 else text.index(chunk_text) if chunk_text in text else 0
            result.append({
                "content": chunk_text,
                "chunk_index": i,
                "chunk_size": len(chunk_text),
                "start_index": start_index,
            })
        return result

    def split_documents(self, text: str, metadata: dict | None = None) -> list[LCDocument]:
        if not text or not text.strip():
            return []
        base_doc = LCDocument(page_content=text, metadata=metadata or {})
        documents = self._splitter.split_documents([base_doc])
        for i, doc in enumerate(documents):
            doc.metadata["chunk_index"] = i
            doc.metadata["chunk_size"] = len(doc.page_content)
        return documents

    def estimate_chunk_count(self, text: str) -> int:
        if not text:
            return 0
        effective_length = len(text)
        step = self._chunk_size - self._chunk_overlap
        if step <= 0:
            return 1
        count = (effective_length + step - 1) // step
        return max(1, count)

    @property
    def config(self) -> dict:
        """当前配置快照（用于日志和调试）"""
        return {
            "type": "recursive",
            "chunk_size": self._chunk_size,
            "chunk_overlap": self._chunk_overlap,
        }


# ========== 预留扩展：Markdown 标题切分 ==========
class MarkdownHeaderSplitter(TextSplitter):
    """
    按 Markdown 标题层级切分（扩展策略）
    适用场景：Markdown 文档、技术博客、README
    利用 # ## ### 标题做天然分割，同一标题下的内容保持完整
    注意：此策略尚未完全实现，目前作为扩展占位
    """
    def __init__(self):
        # 待实现：from langchain.text_splitter import MarkdownHeaderTextSplitter
        raise NotImplementedError("MarkdownHeaderSplitter 尚未接入，当前请使用 RecursiveTextSplitter")
    def split_text(self, text: str) -> list[dict]:
        raise NotImplementedError
    def split_documents(self, text: str, metadata: dict | None = None) -> list[LCDocument]:
        raise NotImplementedError
    def estimate_chunk_count(self, text: str) -> int:
        raise NotImplementedError


# ========== 全局单例工厂 ==========
_splitter_instance: TextSplitter | None = None
def get_splitter() -> TextSplitter:
    """
    获取 TextSplitter 实例（单例）
    后续扩展：根据配置返回不同的实现
    config.SPLITTER_TYPE = "recursive" | "markdown_header"
    调用方只依赖 TextSplitter 抽象，不依赖具体实现
    """
    global _splitter_instance
    if _splitter_instance is None:
        # 从 settings 读取配置，支持覆盖默认值
        _splitter_instance = RecursiveTextSplitter(
            chunk_size=getattr(settings, "CHUNK_SIZE", DEFAULT_CHUNK_SIZE),
            chunk_overlap=getattr(settings, "CHUNK_OVERLAP", DEFAULT_CHUNK_OVERLAP),
        )
    return _splitter_instance

def reset_splitter() -> None:
    """重置单例（测试用）"""
    global _splitter_instance
    _splitter_instance = None