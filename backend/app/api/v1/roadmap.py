from fastapi import APIRouter

from app.models.common import ApiResponse
from app.services.roadmap_service import RoadmapService

router = APIRouter(prefix="/roadmap", tags=["学习路线"])


@router.post("/generate", response_model=ApiResponse)
async def generate_roadmap(target_role: str, resume_text: str = ""):
    service = RoadmapService()
    result = await service.generate(target_role, resume_text)
    return ApiResponse(data=result)
