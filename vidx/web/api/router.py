from fastapi.routing import APIRouter

from vidx.web.api import auth, monitoring, video

api_router = APIRouter()
api_router.include_router(monitoring.router)
api_router.include_router(auth.router)
api_router.include_router(video.router, prefix="/video", tags=["video"])
