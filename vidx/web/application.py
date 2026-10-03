from importlib import metadata

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import UJSONResponse

from vidx.settings import settings
from vidx.web.api.router import api_router
from vidx.web.lifespan import lifespan_setup
from vidx.web.middleware import AuthMiddleware


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

    # Authentication middleware for protected routes. CORS middleware must come before auth
    # so preflight (OPTIONS) requests are handled without authentication.
    app.add_middleware(AuthMiddleware)

    # Enable CORS for the frontend. Origins are configurable via
    # VIDX_CORS_ORIGINS (comma-separated) so deployed frontends can be added
    # without code changes.
    cors_origins = [
        origin.strip()
        for origin in (settings.cors_origins or "").split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app
