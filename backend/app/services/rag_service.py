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

from app.core.config import settings
from app.infrastructure.embeddings import get_embedding
from app.infrastructure.rerank import rerank
from app.repositories.base_vector_store import DocumentChunk, is_grounded
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


# ========== 查询改写（阶段 1.4）==========

# 指代词表：命中即认为实体被替代掉了、需要拿历史补全。
# 刻意不含「该/此」——它们是普通中文高频词（该如何 / 因此），而生产里第 2 轮往后
# history 恒非空，会把「那 HashMap 的扩容机制是什么？」这类自足问句也卷进改写。
ANAPHORA_CUES = ("它", "那", "上面", "前面")

QUERY_REWRITE_PROMPT = """你是查询改写专家。把用户发来的追问改写成一句可以脱离对话、独立检索的完整问句。

规则：
1. 把 它/那/上面/前面 这类指代，换成下面【最近对话】里出现过的具体实体或概念
2. 只输出改写后的这一句问句本身 —— 不要解释、不要引号、不要"改写后："之类的前缀
3. 如果问题本身已经完整，原样返回，不要做任何润色
4. 英文标识符（类名/参数名/字段名）原样保留，不要翻译、不要展开缩写、不要改大小写
5. 指代到多个实体时（如"它俩"），把每个实体都写进去

最近对话：
{history}"""


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

        # 2. 查询改写 + 向量检索（内部 embedding）
        retrieval_query = await self._rewrite_query(question, history)  # 只影响"取回什么"
        query_embedding = await self._embedding.embed_query(retrieval_query) # 将问题转为向量
        # 2.2：开启重排就多取候选（5 → RERANK_CANDIDATES）；关 = 原样取 top_k
        search_k = settings.RERANK_CANDIDATES if settings.RERANK_ENABLED else top_k
        result = self._vector_store.search( # 检索向量
            query_embedding=query_embedding,
            top_k=search_k,
            threshold=threshold,
        )
        # 2.2：跨编码器重排。必须在拒答判定【之前】——is_grounded 看的正是最终
        # 喂给 LLM 的那几条，重排会改集合成员，判定必须锚在重排后的集合上。
        hits = await self._rerank_if_enabled(retrieval_query, result.hits, top_k)

        # 3. 知识库答不了：0 命中，或命中了但没讲问题里的那件事（阶段 1.2 的拒答判定）
        if not hits or (
            settings.RETRIEVAL_TERM_GROUNDING and not is_grounded(question, hits)
        ):
            return {
                "answer": "知识库中没有与您问题相关的信息。请尝试换个问法，或上传相关文档到知识库。",
                "sources": [],
                "has_knowledge": False,
                "token_count": 0,
            }

        # 3.5 2.4：把喂给 LLM 的上下文压进 token 预算（在拒答判定【之后】——拒答只看
        # 知识库里有没有，不看喂多少）。裁【一次】，上下文与来源共用同一份 hits，编号才对得上。
        hits, history = self._apply_budget(hits, history)

        # 4. 拼接上下文（历史 + 文档）
        context = self._build_context(hits, history)

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
        sources = self._format_sources(hits)

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
        # 1. 查询改写 + 向量检索（改写只影响"取回什么"）
        retrieval_query = await self._rewrite_query(question, history)
        query_embedding = await self._embedding.embed_query(retrieval_query)
        # 2.2：开启重排就多取候选（5 → RERANK_CANDIDATES）；关 = 原样取 top_k
        search_k = settings.RERANK_CANDIDATES if settings.RERANK_ENABLED else top_k
        result = self._vector_store.search(
            query_embedding=query_embedding,
            top_k=search_k,
            threshold=threshold,
        )
        # 2.2：重排（与 answer() 同一条路径——两个入口不能各写各的，否则会分叉）
        hits = await self._rerank_if_enabled(retrieval_query, result.hits, top_k)

        if not hits or (
            settings.RETRIEVAL_TERM_GROUNDING and not is_grounded(question, hits)
        ):
            yield f"data: {json.dumps({'type': 'sources', 'data': []})}\n\n"
            yield f"data: {json.dumps({'type': 'token', 'data': '知识库中没有与您问题相关的信息。'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        # 2.4：预算截断（拒答判定之后；裁一次，上下文与来源共用同一份 hits）
        hits, history = self._apply_budget(hits, history)

        # 2. 拼接上下文并先发 sources
        context = self._build_context(hits, history)
        sources = self._format_sources(hits)
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

    async def _rerank_if_enabled(
        self, query: str, hits: list[DocumentChunk], top_k: int
    ) -> list[DocumentChunk]:
        """2.2 的唯一调用点。关 = 原样返回（零开销）；开 = 取前 RERANK_CANDIDATES 条重排。

        query 用改写后的 retrieval_query：重排属于「取回什么」，和 embed 同源。
        """
        if not settings.RERANK_ENABLED:
            return hits
        return await rerank(query, hits[:settings.RERANK_CANDIDATES], top_k)

    # ===== 2.4 上下文 token 预算 =====

    def _render_sources(self, chunks: list[DocumentChunk]) -> list[str]:
        """按文档聚合渲染每条来源。抽出来是为了让「预算测量」和「实际拼接」用同一份文本，
        否则 measured（_sources_tokens）和 rendered（_build_context）会悄悄分叉。"""
        return [
            f"[{src['index']}] {src['content']}\n"
            f"（文档：{src['document']}，相似度：{src['similarity']:.2f}）"
            for src in self._group_sources(chunks)
        ]

    def _sources_tokens(self, chunks: list[DocumentChunk]) -> int:
        return self._llm.count_tokens("\n\n".join(self._render_sources(chunks)))

    def _trim_history(self, history: list[dict] | None, budget: int) -> list[dict]:
        """保留最近的若干条消息（从最新往前收，收不下就停），恢复时间顺序返回。
        按【整条消息】截，不按字符硬切——否则会留半句 assistant 回复。"""
        if not history:
            return []
        kept: list[dict] = []
        used = 0
        for msg in reversed(history):
            t = self._llm.count_messages_tokens([msg])  # 接上此前零引用的死方法
            if used + t > budget:
                break
            kept.append(msg)
            used += t
        return list(reversed(kept))

    def _apply_budget(
        self, chunks: list[DocumentChunk], history: list[dict] | None
    ) -> tuple[list[DocumentChunk], list[dict]]:
        """把「喂给 LLM 的上下文」压进 token 预算，返回 (保留的 chunks, 截过的 history)。

        **必须在拒答判定之后调用**：预算只决定「喂多少」，不决定「能不能答」，
        所以拒答仍看截断前的集合，grounding / recall 不受影响。
        历史先占（≤ HISTORY_MAX_TOKENS），剩下的留给来源；来源从排名最低的块
        （hits 尾部）丢，至少留 1 条——保证最高分来源不被丢。
        """
        kept_history = self._trim_history(history, settings.HISTORY_MAX_TOKENS)
        hist_tokens = self._llm.count_messages_tokens(kept_history) if kept_history else 0
        budget = max(settings.CONTEXT_MAX_TOKENS - hist_tokens, 0)

        kept = list(chunks)
        while len(kept) > 1:
            if self._sources_tokens(kept) <= budget:
                break
            kept.pop()  # hits 尾部 = 重排后排名最低的那块
        return kept, kept_history

    def context_token_count(
        self, chunks: list[DocumentChunk], history: list[dict] | None = None
    ) -> int:
        """2.4 的测量口径：按预算截断后、真正会喂给 LLM 的那段上下文的 token 数（评测用）。"""
        kept, kept_history = self._apply_budget(chunks, history)
        return self._llm.count_tokens(self._build_context(kept, kept_history))

    async def _rewrite_query(self, question: str, history: list[dict] | None) -> str:
        """把指代追问改写成可独立检索的完整问句 —— 1.4 的【唯一】函数边界。

        返回原问题表示「没改」（未开启 / 未触发 / 调用失败 / 结果不可用），调用方无需分支。

        为什么只改这一处：改写只决定「取回什么」，不改「问模型什么」。拒答判定
        （1.2 的 is_grounded）与 prompt 里的 {question} 都仍用原始问句——改写会往问句里
        补标识符，拿它去判会单调变严；且改写出错时不该把自己变成一次拒答。
        """
        if not settings.RETRIEVAL_QUERY_REWRITE or not history:
            return question
        if not any(cue in question for cue in ANAPHORA_CUES):
            return question

        # 掐掉可能的重复：生产里前端是「先 addMessage('user') 再取 history」，history
        # 末条就等于当前问题；评测 fixture 里则不含它。两种形状都吃。
        recent = [m for m in history if (m.get("content") or "").strip()]
        if recent and recent[-1]["content"].strip() == question.strip():
            recent.pop()
        if not recent:
            return question

        # 只喂最近 2 轮；每条截 500 字（助手回答可能很长，实体一般在开头）
        lines = [
            f"{'用户' if m.get('role') == 'user' else '助手'}: {(m.get('content') or '')[:500]}"
            for m in recent[-4:]
        ]

        try:
            rewritten = await self._llm.chat(
                system_prompt=QUERY_REWRITE_PROMPT.format(history="\n".join(lines)),
                user_message=question,
                temperature=0.0,  # 这是转换不是生成，要可复现
                max_tokens=128,
            )
        except Exception:
            logger.warning("查询改写失败，回退原问题", exc_info=True)
            return question

        rewritten = (rewritten or "").strip().strip('"').strip()
        if not rewritten or len(rewritten) > 200:
            return question  # 空 / 像解释而不像问句 → 退化成「不改写」
        return rewritten

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
        parts.extend(self._render_sources(chunks))
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
