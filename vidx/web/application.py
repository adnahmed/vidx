import os
from importlib import metadata

from fastapi import FastAPI
from fastapi.responses import UJSONResponse

from vidx.web.api.router import api_router
from vidx.web.lifespan import lifespan_setup

os.environ["FFPROBE_BINARY"] = f"{os.environ["HOME"]}/ffmpeg/ffprobe"
os.environ["FFMPEG_BINARY"] = f"{os.environ["HOME"]}/ffmpeg/ffmpeg"


def get_app() -> FastAPI:
    """
    Get FastAPI application.

    This is the main constructor of an application.

    :return: application.
    """
    app = FastAPI(
        title="vidx",
        version=metadata.version("vidx"),
        lifespan=lifespan_setup,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        default_response_class=UJSONResponse,
    )

    # Main router for the API.
    app.include_router(router=api_router, prefix="/api")

    return app
