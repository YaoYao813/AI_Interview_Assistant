"""模拟面试服务

职责：
  - start_session: 基于简历/岗位出题，创建面试会话（存 Redis）
  - evaluate: 评价候选人回答，推进面试进度

面试状态完全由 Redis 持有（SessionRepository），本服务无状态。
"""
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import InvalidFileException, LLMException, NotFoundException
from app.infrastructure.document_loader import load
from app.models.interview import InterviewRequest
from app.repositories.cache import CacheRepository
from app.repositories.session import SessionRepository
from app.services.llm_service import LLMService, get_llm_service

QUESTION_COUNT = 5  # 每场面试题目数

QUESTION_SYSTEM_PROMPT = """你是一位资深技术面试官，正在为一场模拟面试出题。

## 面试信息
- 目标岗位：{role}
- 重点方向：{topics}
- 难度：{difficulty}
- 题目数量：{count} 道

## 出题要求（基于简历）
- 70%-80% 的题目必须围绕候选人简历中的技术栈和项目经历提问，深挖细节、原理和难点
- 20%-30% 的题目作为岗位通用题，考察基础广度与体系化理解
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
        """评价回答并推进面试进度"""
        session = await self.sessions.get_session(session_id)
        if session is None:
            raise NotFoundException("面试会话不存在或已过期")

        idx = session["current_index"]
        questions = session["questions"]
        if idx >= len(questions):
            raise NotFoundException("该面试已结束")

        question = questions[idx]
        evaluation = await self._evaluate_answer(question, answer)

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
