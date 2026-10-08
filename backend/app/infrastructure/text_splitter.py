import re
from abc import abstractmethod, ABC

from langchain_core.documents import Document as LCDocument
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter as LangChainMarkdownHeaderSplitter,
    RecursiveCharacterTextSplitter as LangChainRecursiveSplitter,
)
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
DEFAULT_CHUNK_MIN_SIZE: int = 200

# ========== Markdown 标题切分（阶段 2.1）==========
# 只认 3 级，与 document_loader 的 Heading 1/2/3 → #/##/### 转换对齐。
_HEADERS_TO_SPLIT_ON: list[tuple[str, str]] = [("#", "h1"), ("##", "h2"), ("###", "h3")]
_HEADER_LEVELS: tuple[str, ...] = ("h1", "h2", "h3")
# 行首锚定的 ATX 标题。不能写成 `"#" in text`——代码块里的 shell/注释 # 会误判。
_ATX_HEADING_RE = re.compile(r"^[ \t]{0,3}#{1,3}[ \t]+\S", re.MULTILINE)


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


# ========== 阶段 2.1：Markdown 标题切分 ==========
class MarkdownHeaderSplitter(TextSplitter):
    """按 Markdown 标题层级切分（阶段 2.1）。

    适用：带 #/##/### 的 md（JavaGuide，占语料 93.7% 的 chunk）。
    四条规则，逐条对应一个已知的坑：

    1. 有标题 → 按标题切，每块带上标题路径（heading_path）。
    2. 超长 section → 在【section 内部】再用递归切分器切。overlap 只发生在
       section 内：跨 section 加 overlap 会把上一节尾接到下一节头，纯噪声。
    3. 过短的兄弟 section → 合并。否则标题密集的文档（1205 个 H3）全是
       「标题 + 一句」的碎块，碎块向量糊、还挤占 top-5。
    4. 无标题 → 整篇委托 RecursiveTextSplitter。不这么做的话，MarkdownHeader
       找不到切点，会把整篇当成一块，产出远超 chunk_size 的巨块。
    """

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
        min_chunk_size: int = DEFAULT_CHUNK_MIN_SIZE,
    ):
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._min_chunk_size = min_chunk_size
        self._header_splitter = LangChainMarkdownHeaderSplitter(
            headers_to_split_on=_HEADERS_TO_SPLIT_ON
        )
        # 只用于切「超长 section 的内部」，separators 与递归策略保持一致
        self._recursive = LangChainRecursiveSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=DEFAULT_SEPARATORS,
            length_function=len,
            keep_separator=True,
            strip_whitespace=True,
        )
        self._fallback = RecursiveTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )

    @staticmethod
    def has_headings(text: str) -> bool:
        """是否有行首锚定的 ATX 标题（#/##/###）。"""
        return bool(_ATX_HEADING_RE.search(text or ""))

    def _to_pieces(self, text: str) -> list[tuple[list[str], str]]:
        """标题切分 + 超长二次切 + 短兄弟合并，返回 [(heading_path, content)]。"""
        # 1) 按标题切，提取每块的标题路径
        sections: list[tuple[list[str], str]] = []
        for doc in self._header_splitter.split_text(text):
            path = [doc.metadata[k] for k in _HEADER_LEVELS if doc.metadata.get(k)]
            if doc.page_content.strip():
                sections.append((path, doc.page_content))

        # 2) 超长 section 在内部再切（overlap 只在 section 内）
        pieces: list[tuple[list[str], str]] = []
        for path, body in sections:
            if len(body) > self._chunk_size:
                for sub in self._recursive.split_text(body):
                    if sub.strip():
                        pieces.append((path, sub))
            else:
                pieces.append((path, body))

        # 3) 合并「同一父标题下连续的短块」；run 里攒着待合并的兄弟
        out: list[tuple[list[str], str]] = []
        run: list[tuple[list[str], str]] = []
        run_parent: list[str] | None = None
        run_len = 0

        def flush() -> None:
            nonlocal run_parent, run_len
            if not run:
                return
            if len(run) == 1:
                out.append(run[0])
            else:
                # 多块合一：路径退回共同父标题——这是「兄弟合并」的诚实表示
                out.append((run_parent or [], "\n\n".join(c for _, c in run)))
            run.clear()
            run_parent = None
            run_len = 0

        for path, body in pieces:
            # 只有「有父标题」的短块才参与兄弟合并；顶层块与前言不参与。
            if len(body) < self._min_chunk_size and len(path) >= 2:
                parent = path[:-1]
                # run_len 记的是【拼接后】的长度，把 join 用的 "\n\n" 也算进去，
                # 否则合并块会悄悄超过 chunk_size（实测溢出到 1003）。
                sep = 2 if run else 0
                if run and (run_parent != parent or run_len + sep + len(body) > self._chunk_size):
                    flush()
                    sep = 0
                run_parent = parent
                run_len += sep + len(body)
                run.append((path, body))
            else:
                flush()
                out.append((path, body))
        flush()
        return out

    def split_text(self, text: str) -> list[dict]:
        if not text or not text.strip():
            return []
        if not self.has_headings(text):
            return self._fallback.split_text(text)

        result: list[dict] = []
        for path, content in self._to_pieces(text):
            content = content.strip()
            if not content:
                continue
            result.append({
                "content": content,
                "chunk_index": len(result),
                "chunk_size": len(content),
                # 标题切分拿不到可靠的原文字符偏移（只有二次切才有），占位 0；
                # 该字段在生产链路里没人消费，仅手跑脚本会打印。
                "start_index": 0,
                "heading_path": " > ".join(path),
            })
        return result

    def split_documents(self, text: str, metadata: dict | None = None) -> list[LCDocument]:
        if not text or not text.strip():
            return []
        documents: list[LCDocument] = []
        for c in self.split_text(text):
            md = dict(metadata or {})
            md["chunk_index"] = c["chunk_index"]
            md["chunk_size"] = c["chunk_size"]
            if c.get("heading_path"):
                md["heading_path"] = c["heading_path"]
            documents.append(LCDocument(page_content=c["content"], metadata=md))
        return documents

    def estimate_chunk_count(self, text: str) -> int:
        if not text:
            return 0
        if not self.has_headings(text):
            return self._fallback.estimate_chunk_count(text)
        # 标题切分下块数不线性，切一遍最准（只用于 dry-run，不产生 embedding）
        return len(self.split_text(text))

    @property
    def config(self) -> dict:
        """当前配置快照（用于日志和调试）"""
        return {
            "type": "markdown_header",
            "chunk_size": self._chunk_size,
            "chunk_overlap": self._chunk_overlap,
            "min_chunk_size": self._min_chunk_size,
        }


# ========== 全局单例工厂 ==========
_splitter_instance: TextSplitter | None = None
def get_splitter() -> TextSplitter:
    """
    获取 TextSplitter 实例（单例）。
    按 settings.CHUNK_STRATEGY 选实现——这是唯一的「策略边界」：
        recursive       递归字符切分（基线 / 回退）
        markdown_header 标题感知切分（无标题文档内部再委托 recursive）
    调用方只依赖 TextSplitter 抽象，不依赖具体实现。
    """
    global _splitter_instance
    if _splitter_instance is None:
        strategy = getattr(settings, "CHUNK_STRATEGY", "recursive")
        chunk_size = getattr(settings, "CHUNK_SIZE", DEFAULT_CHUNK_SIZE)
        chunk_overlap = getattr(settings, "CHUNK_OVERLAP", DEFAULT_CHUNK_OVERLAP)
        if strategy == "recursive":
            _splitter_instance = RecursiveTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
        elif strategy == "markdown_header":
            _splitter_instance = MarkdownHeaderSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                min_chunk_size=getattr(settings, "CHUNK_MIN_SIZE", DEFAULT_CHUNK_MIN_SIZE),
            )
        else:
            raise ValueError(
                f"未知的 CHUNK_STRATEGY: {strategy!r}（应为 recursive / markdown_header）"
            )
    return _splitter_instance

def reset_splitter() -> None:
    """重置单例（测试用）"""
    global _splitter_instance
    _splitter_instance = None