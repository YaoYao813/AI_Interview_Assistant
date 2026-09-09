from pydantic import BaseModel


class RoadmapStep(BaseModel):
    topic: str
    description: str
    resources: list[str] = []


class RoadmapResult(BaseModel):
    target_role: str
    steps: list[RoadmapStep]
