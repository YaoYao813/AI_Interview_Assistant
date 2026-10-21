"""模拟面试「动态追问」Agent 服务（阶段 4）

职责（一个入口 = 一场面试）：
  - start:         一次性分析「简历 vs 岗位」→ 生成分阶段题目 → 建会话（Redis）
  - answer_stream: 流式评价候选人回答 → 【模型决策】追问 or 翻页 → 回下一题 / 收尾
  - report:        汇总整场问答与评分

与旗舰 InterviewService 的分工（刻意分开，key 前缀不同，互不覆盖）：
  - 旗舰：线性推进（开场一次性出 5 题，答完 current_index += 1），没有任何决策。
  - 本服务：阶段流程仍是【确定性状态机】（if/else 足够），只有「追问 vs 翻页」这一步交给
    模型，且用【工具调用】编码（ask_followup / advance）——这样能直接复用 3.6 的
    「工具选择正确率」评测口径。这也是「为什么不用 LangGraph」的正面回答：
    流程是确定的、决策是局部的，一个函数边界 + 一次工具往返就够。

硬约束沿用（项目级）：
  - 纯新增：不改已验证的旗舰路径（InterviewService / SessionRepository 一行不动）。
  - 只有【一个函数边界】build_decision_messages()（纯函数、无 I/O），供评测直接调用。
  - 上限是【代码里的模块常量】而非 config.py：固定产品规则，不是要 A/B 的优化项，
    不进旗舰配置以免污染。

已知边界（诚实记录）：
  - 「话题派生质量」「B 类追问相关性」「结题报告质量」自动化测不了，只能人工抽查。
  - 上限 12 / 每阶段 2·3 是默认值，要调就改本文件的模块常量。
"""
import json
import logging
import re
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from app.core.exceptions import LLMException, NotFoundException
from app.repositories.agent_session import AgentSessionRepository
from app.repositories.cache import CacheRepository
from app.services.interview_service import (
    EVAL_MARKERS,
    EVAL_STATES,
    EVALUATE_STREAM_SYSTEM_PROMPT,
)
from app.services.llm_service import LLMService, get_llm_service
from app.services.rag_service import RAGService, get_rag_service
from app.utils.sse import sse_event

logger = logging.getLogger(__name__)

# ========== 产品规则（模块常量，不进 config.py）==========
# 每阶段允许的追问次数：自我介绍不追问；八股少追问；项目深挖。
INTERVIEW_FOLLOWUP_CAPS = {"intro": 0, "fundamentals": 2, "project": 3}
INTERVIEW_MAX_QUESTIONS = 12          # 整场总题数上限（含自我介绍）
INTERVIEW_MAX_FUNDAMENTALS = 5        # 八股题条数上限（分析结果裁剪）
INTERVIEW_MAX_PROJECTS = 4            # 项目题条数上限（分析结果裁剪）

PHASES = ("intro", "fundamentals", "project", "done")
PHASE_HINTS = {
    "intro": "自我介绍，不追问，直接翻页",
    "fundamentals": "八股基础，追问宜少",
    "project": "项目拷问，可深挖",
    "done": "面试已结束",
}
INTRO_QUESTION = "请先做一个 1-2 分钟的自我介绍，重点讲讲你的技术背景和最近做过的项目。"

# ========== 提示词 ==========

INTERVIEW_ANALYSIS_PROMPT = """你是一位资深技术面试官。请分析候选人的简历与目标岗位，为一场多轮技术面试准备素材。

## 目标岗位
{role}

## 岗位 JD
{jd}

## 输出要求（严格 JSON）
{{
  "match_summary": "候选人与该岗位匹配度的简要判断（2-3 句，点出强项与短板）",
  "fundamentals_topics": ["八股题1", "八股题2", "八股题3", "八股题4"],
  "project_topics": ["项目题1", "项目题2", "项目题3"]
}}

要求：
- fundamentals_topics：围绕简历里的「专业技能」出的基础原理题（约 4 道），考察原理与取舍，不要只考记忆。
- project_topics：围绕简历中的项目经历出的题（约 3 道），追问技术选型、难点、数据与结果。
- 每一项都是一句【可以直接向候选人提出的问题】，不要只写关键词。
- 若简历信息不足，用岗位通用题补足，但不要编造简历里没有的经历。"""

DECISION_SYSTEM_PROMPT = """你是一位资深技术面试官。候选人刚回答完「当前题目」，你要决定【追问】还是【翻页】。

## 当前阶段
{phase}（{phase_hint}）

## 当前题目
{question}

## 候选人回答
{answer}

## 本阶段追问情况
已追问 {followups_used} 次，上限 {cap} 次。

## 简历摘要（追问可锚定的技术点）
{resume_excerpt}

## 知识库命中（追问可锚定的技术点）
{kb_hits}

## 决策规则（按顺序判断）
1. A 类缺口：回答有事实错误，或含糊、明显不全面 → 调用 ask_followup，
   追问要能补齐这个具体缺口。
2. B 类深挖：回答正确，且【主动提到】了简历摘要或知识库命中里出现过、
   但当前回答【没有展开】的关键技术点 → 就该点再问一层。
3. 其余情况 → 调用 advance。核心考点已经讲清时，不要为了延长面试而追问；
   「还能再问点别的」不构成追问理由。

追问必须收窄到上面「简历摘要」或「知识库命中」里出现过的点；
不在两处的点一律不追问，直接 advance。

## 输出
必须调用且【只调用一个】工具：ask_followup(question=...) 或 advance()。"""

# ========== 决策工具（阶段 4 的核心编码）==========
DECISION_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "ask_followup",
            "description": "就当前题目追问一个更细的问题。当候选人回答含糊/不全面，或答得有料值得深挖时调用。追问只能针对简历或知识库里出现过的技术点。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "要追问的单个具体问题。"}
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "advance",
            "description": "当前题目已经问得足够充分，翻到下一个话题 / 阶段。无需传参。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


# ========== 纯函数（无会话、无 I/O，供评测直接调用）==========

def _to_score(value) -> float | None:
    """从任意文本中提取 0-10 的分数（容错：'7.5 分' → 7.5）"""
    if value is None:
        return None
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    if not match:
        return None
    try:
        return round(float(match.group()), 1)
    except ValueError:
        return None


def _extract_json(text: str) -> dict | None:
    """从文本里兜底抠一个 JSON 对象（模型没按段名输出时用）"""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def build_decision_messages(
    phase: str,
    question: str,
    answer: str,
    followups_used: int,
    cap: int,
    resume_excerpt: str,
    kb_hits: list[str],
) -> list[dict]:
    """构造【决策】这一步的 messages —— 纯函数，不碰会话、不发请求。

    抽成纯函数的意义：评测（阶段 4 的 run_interview_eval）可以拿冻结好的 case
    直接构造 messages 喂给一次 chat_with_tools，不必启动整个服务、不依赖语料。
    """
    system = DECISION_SYSTEM_PROMPT.format(
        phase=phase,
        phase_hint=PHASE_HINTS.get(phase, ""),
        question=question or "",
        answer=answer or "",
        followups_used=followups_used,
        cap=cap,
        resume_excerpt=(resume_excerpt or "").strip() or "（无）",
        kb_hits="\n".join(f"- {h}" for h in (kb_hits or [])) or "（无命中）",
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "请做出决策（调用一个工具）。"},
    ]


def _normalize_analysis(data: dict | None) -> dict:
    """把模型给的分析结果裁剪成会话里要用的固定形状（缺字段/脏数据一律收敛住）"""

    def _clean(value, limit: int) -> list[str]:
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            return []
        out = [str(x).strip() for x in value if str(x).strip()]
        return out[:limit]

    data = data or {}
    return {
        "match_summary": str(data.get("match_summary", "")).strip(),
        "fundamentals_topics": _clean(data.get("fundamentals_topics"), INTERVIEW_MAX_FUNDAMENTALS),
        "project_topics": _clean(data.get("project_topics"), INTERVIEW_MAX_PROJECTS),
    }


class InterviewAgentService:
    """面试 Agent。会话状态全在 Redis（AgentSessionRepository），本服务无状态。"""

    def __init__(
        self,
        cache: CacheRepository,
        llm: LLMService | None = None,
        rag: RAGService | None = None,
    ):
        self.sessions = AgentSessionRepository(cache)
        self._llm = llm or get_llm_service()
        self._rag = rag or get_rag_service()

    # ========== 入口 ==========

    async def start(self, role: str, jd_text: str, difficulty: str, resume_text: str) -> dict:
        """分析简历 vs 岗位 → 建会话 → 返回自我介绍这一题"""
        analysis = await self._analyse(resume_text, role, jd_text)

        session_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        session = {
            "session_id": session_id,
            "role": role,
            "jd_text": jd_text or "",
            "difficulty": difficulty or "medium",
            "resume_excerpt": (resume_text or "")[:800],  # 供 B 类追问收窄用
            "analysis": analysis,
            "phase": "intro",
            "topic_index": 0,
            "followups_used": 0,
            "total_asked": 1,
            "current_question": INTRO_QUESTION,
            "history": [{"role": "interviewer", "question": INTRO_QUESTION}],
            "created_at": now,
            "updated_at": now,
        }
        self._skip_exhausted(session)  # 分析没给出任何题时直接进 done
        await self.sessions.save_session(session_id, session)
        return {"session_id": session_id, "phase": session["phase"], "question": session["current_question"]}

    async def answer_stream(self, session_id: str, answer: str) -> AsyncGenerator[str, None]:
        """候选人作答一轮：**先**同步校验会话，再返回 SSE 生成器。

        校验收在 StreamingResponse 之前完成——「会话不存在 / 已结束」仍是正常 404，
        而不是建流之后才发生的错误（照抄旗舰 prepare_evaluate_stream 的取舍）。
        """
        session = await self.sessions.get_session(session_id)
        if session is None:
            raise NotFoundException("面试会话不存在或已过期")
        if session.get("phase") == "done":
            raise NotFoundException("该面试已结束")
        return self._stream_answer(session, answer)

    async def report(self, session_id: str) -> dict:
        """结题报告：整场问答 + 分数汇总"""
        session = await self.sessions.get_session(session_id)
        if session is None:
            raise NotFoundException("面试会话不存在或已过期")

        qa: list[dict] = []
        current: dict | None = None
        for h in session.get("history") or []:
            role = h.get("role")
            if role == "interviewer":
                current = {"question": h.get("question", ""), "answer": None, "score": None, "feedback": None}
                qa.append(current)
            elif role == "candidate" and current is not None:
                current["answer"] = h.get("answer", "")
            elif role == "evaluator" and current is not None:
                current["score"] = h.get("score")
                current["feedback"] = h.get("feedback", "")

        scores = [q["score"] for q in qa if isinstance(q["score"], (int, float))]
        return {
            "session_id": session_id,
            "role": session.get("role"),
            "match_summary": (session.get("analysis") or {}).get("match_summary", ""),
            "phase": session.get("phase"),
            "total_asked": session.get("total_asked", 0),
            "answered": len(scores),
            "average_score": round(sum(scores) / len(scores), 2) if scores else None,
            "qa": qa,
        }

    # ========== 流式主体 ==========

    async def _stream_answer(self, session: dict, answer: str) -> AsyncGenerator[str, None]:
        """一轮 = 流式评价 → 决策（追问/翻页）→ 下一题 / 收尾。

        事件顺序：score → feedback(逐字) → model_answer(逐字) → question | done
        """
        question = session.get("current_question") or ""

        evaluation: dict = {}
        async for event in self._evaluate_events(question, answer, evaluation):
            yield event
        if "score" not in evaluation:
            return  # 评价失败（error 事件已发）→ 不落库、不推进，与旗舰一致

        action, followup_question, forced = await self._decide(session, answer)
        self._apply_decision(session, action, followup_question)

        now = datetime.now(timezone.utc).isoformat()
        history = session.setdefault("history", [])
        history.append({"role": "candidate", "answer": answer})
        history.append({"role": "evaluator", **evaluation})
        history.append({"role": "decision", "action": action, "forced": forced})
        if session.get("current_question"):
            history.append({"role": "interviewer", "question": session["current_question"]})
        session["updated_at"] = now
        await self.sessions.save_session(session["session_id"], session)

        payload = {
            "phase": session["phase"],
            "followups_used": session["followups_used"],
            "total_asked": session["total_asked"],
            "is_finished": session["phase"] == "done",
            "evaluation": evaluation,
        }
        if payload["is_finished"]:
            yield sse_event("done", payload)
        else:
            payload["question"] = session["current_question"]
            yield sse_event("question", payload)

    async def _evaluate_events(
        self, question: str, answer: str, result: dict
    ) -> AsyncGenerator[str, None]:
        """逐段推送评价，并把结构化结果写进 result。复用旗舰的标记协议。

        这里的「段名状态机」与旗舰 InterviewService._stream_evaluation 同源（同一套
        EVALUATE_STREAM_SYSTEM_PROMPT / EVAL_MARKERS），但**无副作用**：不落库、不推进
        进度（进度由 _advance / followups_used 决定）。之所以重写而不调用旗舰：
        旗舰的流式评价与会话强绑定（校验 session、写 history、推进 current_index），
        复用会把 Agent 的领域模型塞回旗舰；而改旗舰又违反「不碰已验证旗舰路径」硬约束。
        """
        system_prompt = EVALUATE_STREAM_SYSTEM_PROMPT.format(question=question, answer=answer)
        buffer = ""                       # 尚未消费的缓冲
        expected = 0                      # 下一个待匹配的段名下标
        current: str | None = None        # 当前正在累积的段落
        acc = {"score": "", "feedback": "", "model_answer": ""}
        score_sent = False

        def _emit(seg: str, text: str) -> str | None:
            return sse_event(seg, text) if text else None

        try:
            async for token in self._llm.chat_stream(system_prompt, "请评价", temperature=0.3):
                if not token:
                    continue
                buffer += token

                while expected < len(EVAL_MARKERS):
                    marker = EVAL_MARKERS[expected]
                    pos = buffer.find(marker)
                    if pos == -1:
                        break
                    head, buffer = buffer[:pos], buffer[pos + len(marker):]
                    if head and current:
                        acc[current] += head
                        if current != "score":
                            event = _emit(current, head)
                            if event:
                                yield event
                    current = EVAL_STATES[expected]
                    expected += 1
                    if current == "feedback" and not score_sent:
                        score = _to_score(acc["score"])
                        if score is not None:
                            score_sent = True
                            yield sse_event("score", score)

                keep = len(EVAL_MARKERS[expected]) - 1 if expected < len(EVAL_MARKERS) else 0
                if keep and len(buffer) > keep:
                    tail, buffer = buffer[: len(buffer) - keep], buffer[len(buffer) - keep:]
                    if current:
                        acc[current] += tail
                        if current != "score":
                            event = _emit(current, tail)
                            if event:
                                yield event
        except Exception:
            logger.exception("面试 Agent 评价流式调用失败")
            yield sse_event("error", "AI 服务暂时不可用，请稍后重试。")
            return  # 失败不落库，避免写入半截评价

        # ---- 收尾 ----
        if current and buffer:
            acc[current] += buffer
            if current != "score":
                event = _emit(current, buffer)
                if event:
                    yield event
            buffer = ""

        if expected == 0:
            # 模型完全没按段名输出：先试 JSON，再退化为纯文本反馈
            text = buffer.strip()
            data = _extract_json(text)
            if data is not None:
                acc["feedback"] = str(data.get("feedback", ""))
                acc["model_answer"] = str(data.get("model_answer", ""))
                acc["score"] = str(data.get("score", ""))
            elif text:
                acc["feedback"] = text
            if acc["feedback"]:
                yield sse_event("feedback", acc["feedback"])
            if acc["model_answer"]:
                yield sse_event("model_answer", acc["model_answer"])

        score = _to_score(acc["score"])
        if score is not None and not score_sent:
            yield sse_event("score", score)

        result.update({
            "score": score if score is not None else 0,
            "feedback": acc["feedback"],
            "model_answer": acc["model_answer"],
        })

    # ========== 决策 ==========

    async def _decide(self, session: dict, answer: str) -> tuple[str, str | None, bool]:
        """返回 (action, followup_question, forced)。action ∈ {followup, advance}。

        护栏（确定、免费）优先于模型：上限到了直接强制翻页，不花钱调模型。
        """
        phase = session.get("phase", "intro")
        cap = INTERVIEW_FOLLOWUP_CAPS.get(phase, 0)

        if session.get("total_asked", 0) >= INTERVIEW_MAX_QUESTIONS:
            logger.info("面试 Agent：已达总题数上限 %d，强制收尾", INTERVIEW_MAX_QUESTIONS)
            return "advance", None, True
        if session.get("followups_used", 0) >= cap:
            logger.info("面试 Agent：阶段 %s 追问已达上限 %d，强制翻页", phase, cap)
            return "advance", None, True

        question = session.get("current_question") or ""
        kb_hits = await self._kb_excerpt(question)
        messages = build_decision_messages(
            phase=phase,
            question=question,
            answer=answer,
            followups_used=session.get("followups_used", 0),
            cap=cap,
            resume_excerpt=session.get("resume_excerpt", ""),
            kb_hits=kb_hits,
        )
        try:
            msg = await self._llm.chat_with_tools(messages, DECISION_TOOLS)
        except Exception:
            logger.exception("面试 Agent 决策调用失败，静默翻页")
            return "advance", None, False
        action, followup = self._parse_decision(msg)
        return action, followup, False

    def _parse_decision(self, msg) -> tuple[str, str | None]:
        """把模型的工具调用解析成决策。没有 / 多个 / 坏 / 未知 → 静默 advance。"""
        calls = list(getattr(msg, "tool_calls", None) or [])
        if len(calls) != 1:
            if calls:
                logger.warning("面试决策返回 %d 个工具调用，静默翻页", len(calls))
            return "advance", None

        call = calls[0]
        name = getattr(getattr(call, "function", None), "name", "")
        if name == "advance":
            return "advance", None
        if name != "ask_followup":
            logger.warning("面试决策返回未知工具 %s，静默翻页", name)
            return "advance", None

        try:
            args = json.loads(getattr(call.function, "arguments", "") or "{}")
        except json.JSONDecodeError:
            return "advance", None
        followup = str(args.get("question", "")).strip() if isinstance(args, dict) else ""
        if not followup:
            return "advance", None
        return "followup", followup

    # ========== 状态机 ==========

    def _apply_decision(self, session: dict, action: str, followup_question: str | None) -> None:
        """把一次决策落到会话状态（纯状态变更、无 I/O，评测可直接复用）。

        总题数上限在这里收口：第 INTERVIEW_MAX_QUESTIONS 题答完直接 done，
        不再出下一题（此前先 advance 再 +1 会漏出第 13 题）。
        """
        if action == "followup":
            session["followups_used"] = session.get("followups_used", 0) + 1
            session["current_question"] = followup_question
            session["total_asked"] = session.get("total_asked", 0) + 1
            return

        if session.get("total_asked", 0) >= INTERVIEW_MAX_QUESTIONS:
            session["phase"] = "done"
            session["current_question"] = None
            return

        self._advance(session)
        next_question = self._question_for(session)
        if next_question is None:
            session["phase"] = "done"
            session["current_question"] = None
        else:
            session["current_question"] = next_question
            session["total_asked"] = session.get("total_asked", 0) + 1

    def _topics_of(self, session: dict, phase: str) -> list[str]:
        analysis = session.get("analysis") or {}
        if phase == "fundamentals":
            return analysis.get("fundamentals_topics") or []
        if phase == "project":
            return analysis.get("project_topics") or []
        return []

    def _question_for(self, session: dict) -> str | None:
        """当前阶段/下标对应的题目；没有则 None（= 该收尾了）"""
        phase = session.get("phase")
        if phase == "intro":
            return INTRO_QUESTION
        if phase == "done":
            return None
        topics = self._topics_of(session, phase)
        idx = session.get("topic_index", 0)
        return topics[idx] if 0 <= idx < len(topics) else None

    def _advance(self, session: dict) -> None:
        """推进到下一题：阶段内换题，阶段用完则换阶段，全用完则 done。并重置追问计数。"""
        session["followups_used"] = 0
        if session.get("phase") == "intro":
            session["phase"] = "fundamentals"
            session["topic_index"] = 0
        else:
            session["topic_index"] = session.get("topic_index", 0) + 1
        self._skip_exhausted(session)

    def _skip_exhausted(self, session: dict) -> None:
        """跳过没有题目的阶段（分析没给出八股/项目题时）"""
        while session.get("phase") != "done":
            phase = session["phase"]
            if phase == "intro":
                return  # 自我介绍恒有一题
            if session.get("topic_index", 0) < len(self._topics_of(session, phase)):
                return
            session["phase"] = "project" if phase == "fundamentals" else "done"
            session["topic_index"] = 0

    # ========== 内部 ==========

    async def _analyse(self, resume_text: str, role: str, jd_text: str) -> dict:
        """one-shot：分析简历 vs 岗位，产出分阶段的题目"""
        system_prompt = INTERVIEW_ANALYSIS_PROMPT.format(
            role=role or "（未提供）",
            jd=(jd_text or "").strip() or "（未提供）",
        )
        user_message = "## 候选人简历\n" + ((resume_text or "").strip() or "（未提供）")
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                data = await self._llm.chat_json(system_prompt, user_message, temperature=0.3)
                return _normalize_analysis(data)
            except Exception as e:
                # JSON 模式也会偶发非法输出（未转义引号 / 截断），重试一次比直接 503 划算
                last_error = e
                logger.warning("面试分析失败（第 %d 次）: %s", attempt + 1, e)
        raise LLMException(f"面试分析失败: {last_error}")

    async def _kb_excerpt(self, question: str, top_k: int = 3) -> list[str]:
        """取 KB 命中片段，供决策时把 B 类追问收窄到「知识库覆盖过的点」"""
        try:
            hits = await self._rag.retrieve(question, top_k=top_k)
        except Exception:
            logger.exception("面试 Agent KB 检索失败，追问收窄退化为仅按简历")
            return []
        return [h.content.strip()[:200] for h in hits if (getattr(h, "content", "") or "").strip()]
