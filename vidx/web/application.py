from importlib import metadata

from fastapi import FastAPI
from fastapi.responses import UJSONResponse
from fastapi.middleware.cors import CORSMiddleware

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

    # Enable CORS for the frontend (development). Keep restricted origins for security.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Authentication middleware for protected routes. CORS middleware must come before auth
    # so preflight (OPTIONS) requests are handled without authentication.
    app.add_middleware(AuthMiddleware)
    # Main router for the API.
    app.include_router(router=api_router, prefix="/api")

    return app
