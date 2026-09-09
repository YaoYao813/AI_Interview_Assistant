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

        # 参考文档
        for i, chunk in enumerate(chunks, start=1):
            filename = chunk.metadata.get("filename", "未知文档")
            similarity = chunk.similarity or 0
            part = (
                f"[来源{i}] {chunk.content}\n"
                f"（文档：{filename}，相似度：{similarity:.2f}）"
            )
            parts.append(part)
        return "\n\n".join(parts)

    def _format_sources(self, chunks: list[DocumentChunk]) -> list[dict]:
        """
        格式化来源信息（给前端展示）+ 去重

        Returns:
            [
                {"index": 1, "document": "Java集合.pdf", "content": "...", "similarity": 0.92},
                ...
            ]
        """
        sources: list[dict] = []
        seen: set[str] = set()

        for i, chunk in enumerate(chunks, start=1):
            preview = chunk.content[:150]

            if preview in seen:
                continue
            seen.add(preview)

            sources.append({
                "index": i,
                "document": chunk.metadata.get("filename", "未知文档"),
                "content": preview + ("..." if len(chunk.content) > 150 else ""),
                "similarity": chunk.similarity,
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
