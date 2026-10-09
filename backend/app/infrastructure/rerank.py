"""跨编码器重排（阶段 2.2）。

粗排（双编码器 + 余弦）给出一批候选，本模块用一个跨编码器对 (query, passage)
逐对精算相关性、重新排序。它坐在 search() 与拒答判定之间，只改「顺序」和
「喂给 LLM 的是哪几条」，不改「集合」（集合由粗排的阈值决定）。

唯一的函数边界：一个裸 async def。不做 ABC、不做注册表、不做类——A/B 只靠
settings.RERANK_ENABLED 一个开关。
"""
import logging

import httpx

from app.core.config import settings
from app.repositories.base_vector_store import DocumentChunk

logger = logging.getLogger(__name__)

# 比 LLM 的 60s 短得多：重排是「增强」不是「必需」，卡住宁可不要它。
# 不为它开配置口子。
_TIMEOUT = 10.0


def _passage(chunk: DocumentChunk) -> str:
    """喂给跨编码器的 passage = heading_path + 正文（与 2.1b 的 `_embed_text` 同一份）。

    跨编码器能看见 query 并做 token 级交互，但「信息得在文本里它才看得见」——
    heading_path 是【信息】、不是双编码器专属的补偿。所以它和检索向量用同一份增强文本。
    """
    path = chunk.metadata.get("heading_path")
    return f"{path}\n{chunk.content}" if path else chunk.content


async def rerank(query: str, chunks: list[DocumentChunk], top_n: int) -> list[DocumentChunk]:
    """对候选重排，返回相关性最高的前 top_n 条。

    任何失败（超时 / 5xx / 网络 / 解析）都退回原顺序 chunks[:top_n]——与 1.4
    `_rewrite_query` 同款「优化失败即不生效」语义，绝不因重排挂掉整条问答。

    chunk.similarity 一律不动（那是余弦相似度，供前端展示与 _group_sources 取 max）；
    本函数只改【列表顺序】。副作用：重排后前端的「相似度」列不再单调递减——这是
    两把不同尺子的必然结果，不是 bug。
    """
    if not chunks:
        return []

    payload = {
        "model": settings.RERANK_MODEL,
        "query": query,
        "documents": [_passage(c) for c in chunks],
        "top_n": min(top_n, len(chunks)),
        "return_documents": False,
    }
    headers = {"Authorization": f"Bearer {settings.EMBEDDING_API_KEY}"}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{settings.EMBEDDING_BASE_URL}/rerank",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            results = resp.json()["results"]
        # results[].index 是【传进去的 documents 的下标】，不是 chunk_id；
        # 必须按它回填成原 chunk，否则顺序全乱。放 try 内：响应形状不对也走回退。
        ordered = sorted(results, key=lambda r: r["relevance_score"], reverse=True)
        reranked = [chunks[r["index"]] for r in ordered]
    except Exception:
        # 必须打日志：否则线上静默降级成「无重排」你毫无感知
        logger.warning("rerank 调用失败，回退原顺序", exc_info=True)
        return chunks[:top_n]

    return reranked[:top_n]
