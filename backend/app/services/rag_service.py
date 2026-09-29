"""
RAG 问答服务
职责：检索 → 拼接上下文 → 调用 LLM → 返回带 Source Citation 的回答
设计：KnowledgeService 是知识库管理（写），RAGService 是智能问答（读）

类比 Java：
  RAGService  → 类似一个复杂的查询 Service
  组合 VectorStore + LLMService → 类似 Service 组合多个 DAO
"""
import json
import logging
from collections.abc import AsyncGenerator

from app.infrastructure.embeddings import get_embedding
from app.repositories.base_vector_store import DocumentChunk
from app.repositories.vector_store import get_vector_store
from app.services.llm_service import get_llm_service, LLMService

logger = logging.getLogger(__name__)

# ========== Prompt 模板 ==========

RAG_SYSTEM_PROMPT = """你是一个专业的 AI 面试辅导助手。

## 你的角色
你精通各技术领域的面试知识，帮助求职者理解技术概念、准备面试问题。

## 回答要求
1. 基于以下"参考文档"回答问题，不要编造知识库中没有的内容
2. 在答案中引用来源，格式为 [1][2]（对应下方参考文档的序号）
3. 如果参考文档不足以回答问题，请明确说"知识库中没有相关信息"
4. 涉及代码时用代码块展示
5. 回答简洁有条理，适合面试场景

## 参考文档
{context}

## 用户问题
{question}

## 回答"""


class RAGService:
    """
    RAG 问答服务

    核心流程：
      query → embedding → vector search → context building → prompt → LLM → answer + sources

    不负责：
      - 文档上传/删除（由 KnowledgeService 负责）
      - 对话历史管理（由 InterviewService 负责）
    """

    def __init__(
        self,
        vector_store=None,
        llm_service: LLMService | None = None,
    ):
        """
        支持依赖注入，方便单元测试

        Args:
            vector_store: 向量数据库实例（不传则用全局单例）
            llm_service: LLM 服务实例（不传则用全局单例）
        """
        self._vector_store = vector_store or get_vector_store()
        self._llm = llm_service or get_llm_service()
        self._embedding = get_embedding()

    # ========== 核心 API ==========

    async def answer(
        self,
        question: str,
        top_k: int = 5,
        threshold: float = 0.3,
        history: list[dict] | None = None,
    ) -> dict:
        """
        非流式问答

        Args:
            question: 用户问题
            top_k: 检索返回的最大文档块数
            threshold: 相似度阈值（0=不过滤，建议范围 0.2-0.5）
            history: 对话历史 [{"role":"user","content":"..."}, ...]

        Returns:
            {
                "answer": str,              # LLM 生成的回答
                "sources": list[dict],      # 引用来源列表
                "has_knowledge": bool,      # 知识库中是否有相关内容
                "token_count": int,         # 消耗的 Token 数（估算）
            }
        """
        # 1. 校验输入
        if not question or not question.strip():
            return {
                "answer": "请输入有效的问题。",
                "sources": [],
                "has_knowledge": False,
                "token_count": 0,
            }

        # 2. 向量检索（内部 embedding）
        query_embedding = await self._embedding.embed_query(question) # 将问题转为向量
        result = self._vector_store.search( # 检索向量
            query_embedding=query_embedding,
            top_k=top_k,
            threshold=threshold,
        )

        # 3. 知识库无相关内容
        if not result.hits:
            return {
                "answer": "知识库中没有与您问题相关的信息。请尝试换个问法，或上传相关文档到知识库。",
                "sources": [],
                "has_knowledge": False,
                "token_count": 0,
            }

        # 4. 拼接上下文（历史 + 文档）
        context = self._build_context(result.hits, history)

        # 5. 调用 LLM 生成回答
        try:
            answer_text = await self._llm.chat(
                system_prompt=RAG_SYSTEM_PROMPT.format(
                    context=context, question=question
                ),
                user_message=question,
            )
            token_count = self._llm.count_tokens(context) + self._llm.count_tokens(answer_text)
        except Exception:
            logger.exception("LLM 调用失败")
            answer_text = "AI 服务暂时不可用，请稍后重试。"
            token_count = 0

        # 6. 组装 sources
        sources = self._format_sources(result.hits)

        return {
            "answer": answer_text,
            "sources": sources,
            "has_knowledge": True,
            "token_count": token_count,
        }

    async def answer_stream(
        self,
        question: str,
        top_k: int = 5,
        threshold: float = 0.3,
        history: list[dict] | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        流式问答（SSE 格式）

        Yields:
            data: {"type": "sources", "data": [...]}

            data: {"type": "token", "data": "ConcurrentHashMap..."}

            data: {"type": "done"}

        """
        # 1. 向量检索
        query_embedding = await self._embedding.embed_query(question)
        result = self._vector_store.search(
            query_embedding=query_embedding,
            top_k=top_k,
            threshold=threshold,
        )

        if not result.hits:
            yield f"data: {json.dumps({'type': 'sources', 'data': []})}\n\n"
            yield f"data: {json.dumps({'type': 'token', 'data': '知识库中没有与您问题相关的信息。'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        # 2. 拼接上下文并先发 sourcecclaude
        context = self._build_context(result.hits, history)
        sources = self._format_sources(result.hits)
        yield f"data: {json.dumps({'type': 'sources', 'data': sources})}\n\n"

        # 3. 流式调用 LLM
        try:
            async for token in self._llm.chat_stream(
                system_prompt=RAG_SYSTEM_PROMPT.format(
                    context=context, question=question
                ),
                user_message=question,
            ):
                if token:
                    yield f"data: {json.dumps({'type': 'token', 'data': token})}\n\n"
        except Exception:
            logger.exception("LLM 流式调用失败")
            yield f"data: {json.dumps({'type': 'token', 'data': 'AI 服务暂时不可用，请稍后重试。'})}\n\n"

        # 4. 结束标记
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    # ========== 私有方法 ==========

    @staticmethod
    def _group_sources(chunks: list[DocumentChunk]) -> list[dict]:
        """把检索结果按【文档】聚合成引用列表 —— 引用编号的唯一来源。

        为什么要有这个函数：编号必须只有一处产出。此前 `_build_context` 按块
        编号、`_format_sources` 也按块编号但会跳过重复项，两边编号就对不上，
        模型会引用一个前端根本没展示的编号（引用不可追溯）。现在二者都只
        消费本函数的返回值，编号结构上不可能分叉。

        去重键是 `document_id` 而非「内容前 150 字符」：同一文档的不同块正文
        不同，用内容前缀去重挡不住「同一文档占满多个引用位」；反过来，开头
        相同的不同文档又会被误并成一条。

        Returns:
            [{"index": 1, "document": str, "content": str, "similarity": float}, ...]
            index 从 1 连续编号，与 `_format_sources` 的 `index` 逐位一致。
        """
        grouped: dict[str, dict] = {}
        order: list[str] = []

        for chunk in chunks:
            doc_id = chunk.metadata.get("document_id") or chunk.metadata.get("filename", "")
            similarity = chunk.similarity or 0.0

            entry = grouped.get(doc_id)
            if entry is None:
                entry = {
                    "document": chunk.metadata.get("filename", "未知文档"),
                    "contents": [],
                    "seen": set(),
                    "similarity": similarity,
                }
                grouped[doc_id] = entry
                order.append(doc_id)

            # 同一文档内完全相同的块只收一次（切分重叠理论上不该产出，但短块重复很便宜地挡掉）
            content = chunk.content or ""
            if content not in entry["seen"]:
                entry["seen"].add(content)
                entry["contents"].append(content)
            entry["similarity"] = max(entry["similarity"], similarity)

        return [
            {
                "index": i,
                "document": grouped[doc_id]["document"],
                "content": "\n---\n".join(grouped[doc_id]["contents"]),
                "similarity": grouped[doc_id]["similarity"],
            }
            for i, doc_id in enumerate(order, start=1)
        ]

    def _build_context(self, chunks: list[DocumentChunk], history: list[dict] | None = None) -> str:
        """拼接检索结果 + 历史对话为上下文"""
        parts: list[str] = []

        # 历史对话
        if history:
            parts.append("## 对话历史")
            for msg in history:
                role = "用户" if msg.get("role") == "user" else "AI"
                parts.append(f"**{role}**: {msg.get('content', '')}")
            parts.append("")

        # 参考文档（按文档聚合，编号与前端引用来源一致）
        for src in self._group_sources(chunks):
            part = (
                f"[{src['index']}] {src['content']}\n"
                f"（文档：{src['document']}，相似度：{src['similarity']:.2f}）"
            )
            parts.append(part)
        return "\n\n".join(parts)

    def _format_sources(self, chunks: list[DocumentChunk]) -> list[dict]:
        """
        格式化来源信息（给前端展示）。一篇文档一条，编号取自 `_group_sources`。

        Returns:
            [
                {"index": 1, "document": "Java集合.pdf", "content": "...", "similarity": 0.92},
                ...
            ]
        """
        sources: list[dict] = []
        for src in self._group_sources(chunks):
            content = src["content"]
            sources.append({
                "index": src["index"],
                "document": src["document"],
                "content": content[:150] + ("..." if len(content) > 150 else ""),
                "similarity": src["similarity"],
            })
        return sources


# ========== 全局单例 ==========

_rag_service_instance: RAGService | None = None


def get_rag_service() -> RAGService:
    """获取 RAGService 单例"""
    global _rag_service_instance
    if _rag_service_instance is None:
        _rag_service_instance = RAGService()
    return _rag_service_instance


def reset_rag_service() -> None:
    """重置单例（测试用）"""
    global _rag_service_instance
    _rag_service_instance = None
