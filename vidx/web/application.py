from importlib import metadata

from fastapi import FastAPI
from fastapi.responses import UJSONResponse

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

    app.add_middleware(AuthMiddleware)
    # Main router for the API.
    app.include_router(router=api_router, prefix="/api")

    return app
