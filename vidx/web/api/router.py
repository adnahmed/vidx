from fastapi.routing import APIRouter

from vidx.web.api import monitoring, video

api_router = APIRouter()
api_router.include_router(monitoring.router)
api_router.include_router(video.router, prefix="/video", tags=["video"])
