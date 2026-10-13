"""模拟面试服务

职责：
  - start_session: 基于简历/岗位出题，创建面试会话（存 Redis）
  - evaluate: 评价候选人回答，推进面试进度

面试状态完全由 Redis 持有（SessionRepository），本服务无状态。
"""
import json
import logging
import re
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import InvalidFileException, LLMException, NotFoundException
from app.infrastructure.document_loader import load
from app.models.interview import InterviewRequest
from app.repositories.cache import CacheRepository
from app.repositories.session import SessionRepository
from app.services.llm_service import LLMService, get_llm_service
from app.utils.sse import sse_event

logger = logging.getLogger(__name__)

QUESTION_COUNT = 5  # 每场面试题目数

QUESTION_SYSTEM_PROMPT = """你是一位资深技术面试官，正在为一场模拟面试出题。

## 面试信息
- 目标岗位：{role}
- 重点方向：{topics}
- 难度：{difficulty}
- 题目数量：{count} 道

## 出题要求（基于简历）
- 60%-70% 的题目必须围绕候选人简历中的技术栈和项目经历提问，深挖细节、原理和难点
- 30%-40% 的题目作为岗位通用题，考察基础广度与体系化理解
- 题目要具体、有明确的考察点，避免空泛的「介绍一下 XX」
- 难度递进：从基础到深入，最后 1 道可以是开放设计题

## 候选人简历
{resume_text}

## 输出
严格返回 JSON，格式：{{"questions": ["题目1", "题目2", ...]}}"""

EVALUATE_SYSTEM_PROMPT = """你是一位资深技术面试官，正在评价候选人的回答。

## 面试题目
{question}

## 候选人回答
{answer}

## 评价要求
1. score：0-10 分，保留一位小数，从正确性、深度、表达三个维度综合评判
2. feedback：具体、可操作的反馈，指出回答的优点、不足和遗漏的关键点
3. model_answer：给出一份高质量参考答案，结构清晰、覆盖考点

## 输出
严格返回 JSON，格式：{{"score": 7.5, "feedback": "...", "model_answer": "..."}}"""

# 流式评价：用「段名」而非 JSON，便于边生成边渲染
EVALUATE_STREAM_SYSTEM_PROMPT = """你是一位资深技术面试官，正在评价候选人的回答。

## 面试题目
{question}

## 候选人回答
{answer}

## 评价要求
1. score：0-10 分，保留一位小数，从正确性、深度、表达三个维度综合评判
2. feedback：具体、可操作的反馈，指出回答的优点、不足和遗漏的关键点
3. model_answer：给出一份高质量参考答案，结构清晰、覆盖考点

## 输出格式（必须严格遵守，用于流式渲染）
按下面三段依次输出，段名必须原样保留，**不要输出 JSON，不要加 markdown 代码块**：

###SCORE###
（只写一个 0-10 的数字，保留一位小数）

###FEEDBACK###
（反馈正文）

###MODEL_ANSWER###
（参考答案正文）"""

# 段落顺序与段名一一对应，流式解析依赖此顺序
EVAL_MARKERS = ("###SCORE###", "###FEEDBACK###", "###MODEL_ANSWER###")
EVAL_STATES = ("score", "feedback", "model_answer")


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


def _strip_code_fence(text: str) -> str:
    """去掉可能存在的 markdown 代码块包裹"""
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    return match.group(1).strip() if match else text.strip()


def _try_json(text: str) -> dict | None:
    """尝试从文本中提取 JSON 对象（兜底：模型没按段名输出时可能仍返回 JSON）"""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


class InterviewService:
    """模拟面试服务"""

    def __init__(self, cache: CacheRepository, llm: LLMService | None = None):
        self.sessions = SessionRepository(cache)
        self._llm = llm or get_llm_service()

    async def parse_resume(self, file_bytes: bytes, filename: str) -> str:
        """将上传的简历文件解析为纯文本（与简历分析模块共用 document_loader）"""
        ext = Path(filename).suffix.lower()
        if ext not in settings.ALLOWED_EXTENSIONS:
            raise InvalidFileException(
                f"不支持的文件格式 '{ext}'。"
                f"当前支持: {', '.join(settings.ALLOWED_EXTENSIONS)}"
            )

        upload_dir = Path(settings.UPLOAD_DIR)
        upload_dir.mkdir(parents=True, exist_ok=True)
        temp_path = upload_dir / f"resume_{uuid.uuid4().hex}{ext}"

        try:
            with open(temp_path, "wb") as f:
                f.write(file_bytes)
            text = load(str(temp_path))
        except ValueError as e:
            raise InvalidFileException(f"简历解析失败: {e}")
        finally:
            if temp_path.exists():
                temp_path.unlink()

        if not text or len(text.strip()) < 20:
            raise InvalidFileException("简历内容过短，请检查文件是否有效")
        return text

    async def start_session(self, req: InterviewRequest) -> dict:
        """出题并创建面试会话"""
        questions = await self._generate_questions(req)

        session_id = uuid.uuid4().hex
        session = {
            "session_id": session_id,
            "role": req.role,
            "topics": req.topics,
            "difficulty": req.difficulty,
            "questions": questions,
            "current_index": 0,
            "history": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await self.sessions.save_session(session_id, session)

        return {
            "session_id": session_id,
            "total": len(questions),
            "current_index": 0,
            "current_question": questions[0],
        }

    async def evaluate(self, session_id: str, answer: str) -> dict:
        """评价回答并推进面试进度（非流式）"""
        session, question = await self._load_active_session(session_id)
        evaluation = await self._evaluate_answer(question, answer)
        return await self._persist_evaluation(session_id, session, evaluation, answer)

    async def evaluate_answer(self, question: str, answer: str) -> dict:
        """公开的【纯评价】入口（无副作用），供 Agent 的 evaluate_answer 工具复用。

        与 evaluate(session_id, answer) 的区别：不需要会话、不落库、不推进面试进度，
        只对 (题目, 回答) 打分并返回 {score, feedback, model_answer}。
        evaluate() 内部同样走 _evaluate_answer，行为一行未变。
        """
        return await self._evaluate_answer(question, answer)

    async def prepare_evaluate_stream(
        self, session_id: str, answer: str
    ) -> AsyncGenerator[str, None]:
        """流式评价的入口：**先**同步校验会话是否有效

        校验收在 StreamingResponse 之前完成，这样「会话不存在 / 已结束」
        仍然是正常的 404 响应，而不是已经建立流之后才发生的错误。

        Returns:
            SSE 事件生成器（交给 StreamingResponse）
        """
        session, question = await self._load_active_session(session_id)
        return self._stream_evaluation(session_id, session, question, answer)

    async def _load_active_session(self, session_id: str) -> tuple[dict, str]:
        """取出会话及其当前待答题，无效则抛 NotFoundException"""
        session = await self.sessions.get_session(session_id)
        if session is None:
            raise NotFoundException("面试会话不存在或已过期")

        idx = session["current_index"]
        questions = session["questions"]
        if idx >= len(questions):
            raise NotFoundException("该面试已结束")
        return session, questions[idx]

    async def _stream_evaluation(
        self,
        session_id: str,
        session: dict,
        question: str,
        answer: str,
    ) -> AsyncGenerator[str, None]:
        """逐段推送面试评价

        事件顺序：score → feedback(逐字) → model_answer(逐字) → done(含结构化结果)

        解析方式是「段名状态机」：LLM 输出的文本按 ###SCORE### / ###FEEDBACK### /
        ###MODEL_ANSWER### 分段，遇到下一个段名就切换当前段落；为避免段名被拆在
        两个 token 之间，每个状态下都回留 len(段名)-1 个字符不推送。
        """
        system_prompt = EVALUATE_STREAM_SYSTEM_PROMPT.format(question=question, answer=answer)

        raw = ""                        # 完整原文（兜底用）
        buffer = ""                     # 尚未消费的缓冲
        expected = 0                    # 下一个待匹配的段名下标
        current: str | None = None      # 当前正在累积的段落
        texts = {"feedback": "", "model_answer": ""}
        score_text = ""

        try:
            async for token in self._llm.chat_stream(
                system_prompt, "请评价", temperature=0.3
            ):
                if not token:
                    continue
                raw += token
                buffer += token
                out: list[str] = []

                # 尽可能消费段名
                while expected < len(EVAL_MARKERS):
                    marker = EVAL_MARKERS[expected]
                    pos = buffer.find(marker)
                    if pos == -1:
                        break
                    head = buffer[:pos]
                    if head and current:
                        if current == "score":
                            score_text += head
                        else:
                            texts[current] += head
                            out.append(sse_event(current, head))
                    buffer = buffer[pos + len(marker):]
                    current = EVAL_STATES[expected]
                    expected += 1
                    if current == "feedback":
                        # 分数段结束，此时才推分数（数字要完整才能解析）
                        score = _to_score(score_text)
                        if score is not None:
                            out.append(sse_event("score", score))

                if expected >= len(EVAL_MARKERS):
                    # 段名已全部出现，剩余内容都属于 model_answer
                    if buffer:
                        texts["model_answer"] += buffer
                        out.append(sse_event("model_answer", buffer))
                        buffer = ""
                else:
                    # 回留可能被拆开的段名，其余可以安全推送
                    keep = len(EVAL_MARKERS[expected]) - 1
                    if len(buffer) > keep:
                        tail = buffer[: len(buffer) - keep]
                        buffer = buffer[len(buffer) - keep:]
                        if current == "score":
                            score_text += tail
                        elif current:
                            texts[current] += tail
                            out.append(sse_event(current, tail))

                for event in out:
                    yield event
        except Exception:
            logger.exception("面试评价流式调用失败")
            yield sse_event("error", "AI 服务暂时不可用，请稍后重试。")
            return  # 失败不落库，避免写入半截评价

        # ---- 收尾 ----
        if expected == 0:
            # 模型完全没按段名输出：先试 JSON，再退化为纯文本反馈
            fallback = _strip_code_fence(raw)
            data = _try_json(fallback)
            if data is not None:
                texts["feedback"] = str(data.get("feedback", ""))
                texts["model_answer"] = str(data.get("model_answer", ""))
                score_text = data.get("score", "")
            elif fallback:
                texts["feedback"] = fallback

            score = _to_score(score_text)
            if score is not None:
                yield sse_event("score", score)
            if texts["feedback"]:
                yield sse_event("feedback", texts["feedback"])
            if texts["model_answer"]:
                yield sse_event("model_answer", texts["model_answer"])
        elif buffer:
            if current == "score":
                score_text += buffer
                score = _to_score(score_text)
                if score is not None:
                    yield sse_event("score", score)
            elif current:
                texts[current] += buffer
                yield sse_event(current, buffer)

        score = _to_score(score_text)
        evaluation = {
            "score": score if score is not None else 0,
            "feedback": texts["feedback"],
            "model_answer": texts["model_answer"],
        }
        meta = await self._persist_evaluation(session_id, session, evaluation, answer)
        yield sse_event("done", meta)

    async def _persist_evaluation(
        self, session_id: str, session: dict, evaluation: dict, answer: str
    ) -> dict:
        """把评价写回会话并推进进度（流式/非流式共用的落库逻辑）"""
        idx = session["current_index"]
        questions = session["questions"]
        question = questions[idx]

        session["history"].append({"role": "interviewer", "question": question})
        session["history"].append({"role": "candidate", "answer": answer})
        session["history"].append({"role": "evaluator", **evaluation})
        session["current_index"] = idx + 1
        session["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self.sessions.save_session(session_id, session)

        is_finished = (idx + 1) >= len(questions)
        return {
            "score": evaluation["score"],
            "feedback": evaluation["feedback"],
            "model_answer": evaluation.get("model_answer", ""),
            "current_index": idx + 1,
            "total": len(questions),
            "is_finished": is_finished,
            "next_question": None if is_finished else questions[idx + 1],
        }

    async def _generate_questions(self, req: InterviewRequest) -> list[str]:
        topics = "、".join(req.topics) if req.topics else "岗位核心技能"
        resume = req.resume_text.strip() or "（候选人未提供简历，请全部出岗位通用题）"
        system_prompt = QUESTION_SYSTEM_PROMPT.format(
            role=req.role,
            topics=topics,
            difficulty=req.difficulty,
            count=QUESTION_COUNT,
            resume_text=resume,
        )
        try:
            data = await self._llm.chat_json(system_prompt, "请出题", temperature=0.7)
        except Exception as e:
            raise LLMException(f"面试出题失败: {e}")

        questions = data.get("questions", [])
        if not questions:
            raise LLMException("面试出题失败：未生成题目")
        return questions

    async def _evaluate_answer(self, question: str, answer: str) -> dict:
        system_prompt = EVALUATE_SYSTEM_PROMPT.format(question=question, answer=answer)
        try:
            return await self._llm.chat_json(system_prompt, "请评价", temperature=0.3)
        except Exception as e:
            raise LLMException(f"面试评价失败: {e}")
