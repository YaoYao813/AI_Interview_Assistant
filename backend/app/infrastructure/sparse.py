"""混合检索的稀疏一路（阶段 2.5）：BM25 词法检索 + RRF 融合。

为什么要有这一路：稠密检索（bge-m3 余弦）是语义匹配，遇到「罕见标识符 / 专有术语」
会把语义近邻压在正主前面——典型是 B01 的 `sizeCtl`，稠密只排到第 4。BM25 是词法
精确匹配，`sizeCtl` 原样命中 → 排到第 1。两路并联再用 RRF 融合，互补长短。

类比 Java：这类似在同一个 DAO 接口下再挂一个「按精确字段查」的实现，查询服务把两侧
结果归并——不是新框架，是同一层里加一个检索器。

本模块是 2.5 的【唯一函数边界】：
  - tokenize()      分词（ASCII 标识符整块保留 + 中文双字组）
  - BM25Store       稀疏索引（按需从 Chroma 现读现建）
  - rrf_fuse()      融合（唯一对外策略入口，被 rag_service 与 run_eval 共用）
"""
import logging
import re

from rank_bm25 import BM25Okapi

from app.repositories.base_vector_store import DocumentChunk
from app.repositories.vector_store import get_vector_store

logger = logging.getLogger(__name__)

# RRF 的名次折扣常数（标准值 60）。只用排名、不用分数，所以免疫「余弦 vs BM25」
# 的量纲差异——这正是它取代「分数加权求和」的原因。
RRF_K = 60

# ASCII 标识符：以字母开头，后续允许字母/数字/_. # + -（覆盖 sizeCtl / JDK1.8 / ReadView）。
# 与 base_vector_store._IDENTIFIER_RE 同一套字符集，但这里不做长度过滤——
# BM25 的 IDF 自己会把高频短词（a / the）压下去。
_IDENT_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.#+-]*")
# 连续汉字串（含扩展 A 区常用范围，够覆盖技术语料）。
_CJK_RE = re.compile(r"[一-鿿]+")


def tokenize(text: str) -> list[str]:
    """切词：英文标识符整块保留（小写），连续汉字切双字组（char bigram）。

    为什么英文和中文分开处理：中文没有空格，BM25 又必须拿到「词项」。用双字组
    （雪花算法 → 雪花/花算/算法）而非分词器（jieba），是为了零字典依赖、对 OOV
    术语鲁棒；但双字组会把手写标识符切碎（sizeCtl → size/Ct/…），所以英文先整块
    抠出来再动中文——保住了 2.5 存在的全部理由（精确匹配标识符）。
    """
    text = text or ""
    tokens: list[str] = [m.group(0).lower() for m in _IDENT_RE.finditer(text)]
    for m in _CJK_RE.finditer(text):
        seg = m.group(0)
        if len(seg) == 1:
            tokens.append(seg)
        else:
            tokens.extend(seg[i:i + 2] for i in range(len(seg) - 1))
    return tokens


def _index_text(chunk: DocumentChunk) -> str:
    """BM25 索引文本 = heading_path + 正文，与稠密侧 _embed_text 保持同一份「可检索文本」。

    有标题才有前置；正文是 Chroma 存的干净文本（不含路径），所以要在这里补回
    heading_path，否则两路看到的文本不一致，融合就成了在比两种不同的东西。
    """
    path = chunk.metadata.get("heading_path")
    return f"{path}\n{chunk.content}" if path else chunk.content


class BM25Store:
    """BM25 稀疏检索器。语料从 Chroma 现读现建（不落盘、不改库）。

    刻意做成「懒建 + 缓存」：构造便宜，真正用到才读全量语料建索引。语料在两次
    重建之间是静态的，缓存一次即可；重建后需要 reset_bm25_store() 才刷新。
    """

    def __init__(self) -> None:
        self._chunks: list[DocumentChunk] = []
        self._bm25: BM25Okapi | None = None
        self._built = False

    def _ensure_built(self) -> None:
        if self._built:
            return
        self._chunks = get_vector_store().all_chunks()
        corpus = [tokenize(_index_text(c)) for c in self._chunks]
        # 空语料时 BM25Okapi 没有可用的 avgdl，直接留 None，search 会退化成空结果。
        self._bm25 = BM25Okapi(corpus) if corpus else None
        self._built = True
        logger.info("BM25 索引已构建：%d 块", len(self._chunks))

    def search(self, query: str, top_k: int) -> list[DocumentChunk]:
        """返回 BM25 分数最高的 top_k 块（similarity 一律不填——那是余弦的语义，
        BM25 分不是相似度，别让它混进 sources 的「相似度」展示）。"""
        self._ensure_built()
        if not self._bm25 or not self._chunks:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        return [
            DocumentChunk(
                chunk_id=self._chunks[i].chunk_id,
                content=self._chunks[i].content,
                metadata=self._chunks[i].metadata,
            )
            for i in order
        ]


def rrf_fuse(
    dense_hits: list[DocumentChunk],
    sparse_hits: list[DocumentChunk],
    top_n: int,
) -> list[DocumentChunk]:
    """Reciprocal Rank Fusion：把两路【按排名】的结果融合成一个排序。

    每块得分 = Σ 1/(RRF_K + 该路里的名次)。只用名次不用分数——稠密余弦在 [-1,1]、
    BM25 无上界，直接相加等于拿米加斤。两块都在两路里排得靠前 → 融合分最高。
    去重键是 chunk_id：同一块在两路都出现时，两路各贡献一份倒数名次。
    同分时优先返回稠密侧的对象（带余弦 similarity，供 sources 展示）。
    """
    scores: dict[str, float] = {}
    picked: dict[str, DocumentChunk] = {}
    for rank, chunk in enumerate(dense_hits, start=1):
        scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (RRF_K + rank)
        picked.setdefault(chunk.chunk_id, chunk)
    for rank, chunk in enumerate(sparse_hits, start=1):
        scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (RRF_K + rank)
        picked.setdefault(chunk.chunk_id, chunk)

    order = sorted(scores, key=lambda cid: scores[cid], reverse=True)[:top_n]
    return [picked[cid] for cid in order]


# ========== 全局单例 ==========

_bm25_store_instance: BM25Store | None = None


def get_bm25_store() -> BM25Store:
    global _bm25_store_instance
    if _bm25_store_instance is None:
        _bm25_store_instance = BM25Store()
    return _bm25_store_instance


def reset_bm25_store() -> None:
    """重置单例（测试 / 语料重建后刷新索引用）"""
    global _bm25_store_instance
    _bm25_store_instance = None
