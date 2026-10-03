from fastapi.routing import APIRouter

from vidx.web.api import auth, media, monitoring, projects, transcript, video, webhooks

api_router = APIRouter()
api_router.include_router(monitoring.router)
api_router.include_router(auth.router)
api_router.include_router(video.router, prefix="/video", tags=["video"])
api_router.include_router(transcript.router)
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(projects.posts_router, prefix="/posts", tags=["posts"])
api_router.include_router(projects.scenes_router, prefix="/scenes", tags=["scenes"])
api_router.include_router(projects.social_router, prefix="/social", tags=["social"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(media.router, prefix="/media", tags=["media"])
