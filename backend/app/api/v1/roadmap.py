from fastapi import APIRouter, Depends

from app.api.deps import get_learning_svc
from app.models.common import ApiResponse
from app.models.roadmap import RoadmapRequest
from app.services.learning_service import LearningService

router = APIRouter(prefix="/roadmap", tags=["学习路线"])


@router.post("/generate", response_model=ApiResponse)
async def generate_roadmap(
    req: RoadmapRequest,
    learning_svc: LearningService = Depends(get_learning_svc),
):
    result = await learning_svc.generate_roadmap(req.target_role, req.resume_text)
    return ApiResponse(data=result)
