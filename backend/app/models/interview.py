from pydantic import BaseModel


class InterviewRequest(BaseModel):
    role: str
    topics: list[str] = []
    difficulty: str = "medium"


class InterviewSession(BaseModel):
    session_id: str
    questions: list[str]
    current_index: int = 0


class EvaluationResult(BaseModel):
    score: float
    feedback: str
    model_answer: str = ""
