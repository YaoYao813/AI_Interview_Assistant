"""Agent 服务（阶段 3）

职责：一个手写的工具调用循环 —— 带 tools 调 LLM → 模型要工具就执行并回填 → 否则返回。
这是「RAG 是 Agent 的第一个工具」的落地层，也是模拟面试动态追问的地基。

设计约束（沿用项目硬约束）：
  - 只有【一个函数边界】`_build_tools()`，不做策略基类 / 注册表 / 插件框架。
  - 请求级状态（简历文本）用【闭包】捕获进工具，绝不挂到单例 self 上——单例跨并发请求
    共享，挂 self 会在 await 让出时被别的请求覆盖（跨用户串号）。
  - 工具异常【当结果喂回模型】，不抛出去 500；让模型自己纠错或降级。
"""
import asyncio
import json
import logging

from app.core.config import settings
from app.repositories.base_vector_store import is_grounded
from app.services.interview_service import InterviewService
from app.services.llm_service import LLMService, get_llm_service
from app.services.rag_service import RAGService, get_rag_service
from app.services.resume_service import ResumeService, get_resume_service

logger = logging.getLogger(__name__)

MAX_STEPS = 8          # 工具往返轮数上限（超了强制停，防死循环）
TOOL_TIMEOUT = 30.0    # 单次工具执行的墙钟上限（秒）


AGENT_SYSTEM_PROMPT = """你是 AI 面试助手。你可以调用工具来更准确地回答问题。

工具使用原则：
- 涉及具体技术事实（概念、原理、面试题解析）时，必须先调用 search_knowledge_base 依据知识库作答，
  即使对话历史里已经聊过相关内容——历史可能不准确或不完整，不要只凭记忆回答。
- 用户提供了简历、且需要了解其背景或据此设计问题时，调用 analyse_resume。
- 需要给用户的回答打分点评时，调用 evaluate_answer。
- 只有寒暄、身份询问、纯闲聊这类不涉及知识库内容时，才不调用任何工具、直接回答。

调用工具后，请基于工具返回的结果组织最终回答，不要编造工具没提供的信息。
如果 search_knowledge_base 明确返回「知识库中没有相关信息」，请如实告知用户知识库无法回答该问题，不要凭自己的知识作答。"""


# ========== 工具 schema（阶段 3.2 定稿，2–4 个为宜）==========
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "检索本地知识库，返回与查询最相关的文档片段。当回答需要依据知识库里的资料（技术概念、面试题解析等）时调用；寒暄、或当前上下文已足够回答时不要调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "要检索的查询语句。请针对当前意图重新组织，不要照抄用户原话。"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 10, "description": "期望返回的片段条数，默认 5；取值 1-10，越大越宽。"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyse_resume",
            "description": "分析本次请求携带的简历，返回结构化结果（技能 / 经历 / 薄弱点）。当需要了解候选人背景、或据此设计面试题与追问时调用。无需传参。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "evaluate_answer",
            "description": "对一道面试题的回答打分并给出点评。当需要评估用户回答的质量（给分、指出不足）时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "被回答的面试题题干。"},
                    "answer": {"type": "string", "description": "用户对该题的回答内容。"},
                },
                "required": ["question", "answer"],
            },
        },
    },
]


class AgentService:
    """工具调用循环。无状态：请求级数据一律靠闭包/参数传递，不停在 self 上。"""

    def __init__(
        self,
        llm: LLMService | None = None,
        rag: RAGService | None = None,
        resume: ResumeService | None = None,
        interview: InterviewService | None = None,
    ):
        self._llm = llm or get_llm_service()
        self._rag = rag or get_rag_service()
        self._resume = resume or get_resume_service()
        # 需要 Redis 缓存才能构造，故不设全局单例默认值；由端点（3.4）注入。
        self._interview = interview

    async def run(
        self,
        message: str,
        resume_text: str | None = None,
        history: list[dict] | None = None,
    ) -> dict:
        """跑一轮 agent：最多 MAX_STEPS 次工具往返。

        Args:
            message: 用户本轮消息
            resume_text: 请求携带的简历文本（无状态，用于 analyse_resume 工具）
            history: 历史消息 [{"role": "user"/"assistant", "content": "..."}]

        Returns:
            {"answer": str, "steps": [...], "stopped": "done" | "max_steps" | "error"}
        """
        messages: list[dict] = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
        messages.extend(history or [])
        messages.append({"role": "user", "content": message})

        impls = self._build_tools(message, resume_text)  # ★闭包捕获请求级状态
        seen: set[str] = set()                  # 重复调用检测：tool + arguments
        steps: list[dict] = []
        msg = None

        for step in range(MAX_STEPS):
            try:
                msg = await self._llm.chat_with_tools(messages, TOOLS)  # 调用chat_with_tools就可以知道需不需要调用工具
            except Exception:
                # 与 RAG 的 answer() 同款：LLM 是全项目底层，挂了就优雅降级，不 500
                logger.exception("Agent 调用 LLM 失败")
                return {"answer": "AI 服务暂时不可用，请稍后重试。", "steps": steps, "stopped": "error"}

            # 没有 tool_calls → 这就是最终答案
            if not msg.tool_calls:
                return {"answer": msg.content or "", "steps": steps, "stopped": "done"}

            # 关键：把含 tool_calls 的 assistant 消息原样塞回 history，否则下一步 400
            messages.append(msg)

            for tc in msg.tool_calls:
                key = f"{tc.function.name}:{tc.function.arguments}"
                if key in seen:
                    # 同工具同参数重复调用：不重跑，改喂一句提示让模型换招
                    result = "该工具已用相同参数调用过，请换一个思路或直接回答。"
                else:
                    seen.add(key)
                    result = await self._dispatch(impls, tc)

                # ★结果用匹配的 tool_call_id 回填
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
                steps.append({"step": step, "tool": tc.function.name, "result": result[:200]})

        return {
            "answer": (msg.content or "") if msg is not None else "",
            "steps": steps,
            "stopped": "max_steps",
        }

    # ========== 内部 ==========

    async def _dispatch(self, impls: dict, tc) -> str:
        """执行一次工具调用：parse → 校验 → 超时/异常【当结果喂回去】，绝不抛出去。"""
        impl = impls.get(tc.function.name)
        if impl is None:
            return f"未知工具：{tc.function.name}"

        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            return "参数不是合法 JSON，请重新调用。"
        if not isinstance(args, dict):
            return "参数格式错误，应为 JSON 对象。"

        try:
            return await asyncio.wait_for(impl(**args), timeout=TOOL_TIMEOUT)
        except asyncio.TimeoutError:
            return f"工具 {tc.function.name} 执行超时，请重试或换用其他方式。"
        except TypeError as e:
            # 模型传了 schema 里没有的参数 / 必填缺失
            return f"工具参数有误：{e}"
        except Exception as e:
            logger.exception("工具 %s 执行失败", tc.function.name)
            return f"工具执行失败：{e}"

    def _build_tools(self, message: str, resume_text: str | None) -> dict:
        """构建本次请求的工具实现。

        message / resume_text 用闭包捕获——它们都是本次 run() 的局部变量，别的并发
        请求够不着，所以不可能串号。工具函数体只负责把模型给的参数「转换 + 补全」
        成下游方法要的形态，模型永远看不到、也传不了 message / resume_text 本身。
        message 只用于拒答判定（见下），不作为工具参数暴露给模型。
        """

        async def search_knowledge_base(query: str, top_k: int = 5) -> str:
            try:
                top_k = max(1, min(int(top_k), 10))  # 夹逼：模型越界也挡得住
            except (TypeError, ValueError):
                top_k = 5
            hits = await self._rag.retrieve(query, top_k=top_k)
            # 拒答闸门：与 /rag/chat 的 answer() 用同一把尺子（is_grounded + 同一个开关）。
            # 判据用【原始 message】而非模型改写的 query——改写只影响「取回什么」，
            # 「能不能答」要看用户到底问了什么，与 answer() 用原问句同源。
            if not hits or (
                settings.RETRIEVAL_TERM_GROUNDING and not is_grounded(message, hits)
            ):
                return "知识库中没有与该问题相关的信息，请如实告知用户无法从知识库回答。"
            payload = [
                {
                    "content": h.content,
                    "source": h.metadata.get("filename", ""),
                    "similarity": round(h.similarity or 0.0, 3),
                }
                for h in hits
            ]
            return json.dumps(payload, ensure_ascii=False)

        async def analyse_resume() -> str:
            if not resume_text:
                return "本次请求未携带简历，无法分析。"
            result = await self._resume.analyse_text(resume_text)
            result.pop("_meta", None)  # 别把简历原文（最多 8000 字）塞回模型上下文
            return json.dumps(result, ensure_ascii=False)

        async def evaluate_answer(question: str, answer: str) -> str:
            if self._interview is None:
                return "评分服务未就绪。"
            result = await self._interview.evaluate_answer(question, answer)
            return json.dumps(result, ensure_ascii=False)

        return {
            "search_knowledge_base": search_knowledge_base,
            "analyse_resume": analyse_resume,
            "evaluate_answer": evaluate_answer,
        }


# ========== 全局单例 ==========
_agent_service_instance: AgentService | None = None


def get_agent_service() -> AgentService:
    """获取 AgentService 单例（interview 由端点在 3.4 另行注入）"""
    global _agent_service_instance
    if _agent_service_instance is None:
        _agent_service_instance = AgentService()
    return _agent_service_instance


def reset_agent_service() -> None:
    """重置单例（测试用）"""
    global _agent_service_instance
    _agent_service_instance = None
