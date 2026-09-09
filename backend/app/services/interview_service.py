from app.models.interview import InterviewRequest


class InterviewService:
    async def start_session(self, req: InterviewRequest) -> dict:
        # TODO: generate questions based on role/topics/difficulty
        raise NotImplementedError

    async def evaluate(self, session_id: str, question: str, answer: str) -> dict:
        # TODO: call LLM to score and give feedback
        raise NotImplementedError
