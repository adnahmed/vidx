from contextlib import asynccontextmanager
from typing import AsyncGenerator

import beanie
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient

from vidx.db.models import load_all_models
from vidx.settings import settings
from vidx.services.container import ServiceContainer


async def _setup_db(app: FastAPI) -> None:
    """Setup database strategy based on configuration."""
    db_strategy = ServiceContainer.get_database_strategy()
    await db_strategy.connect()
    app.state.db_strategy = db_strategy

    # For backward compatibility with existing code using MongoDB
    if settings.db_type.lower() == "mongodb":
        client = AsyncIOMotorClient(str(settings.db_url))  # type: ignore
        app.state.db_client = client
        await beanie.init_beanie(
            database=client[settings.db_base],
            document_models=load_all_models(),  # type: ignore
        )


async def _setup_cache(app: FastAPI) -> None:
    """Setup cache strategy based on configuration."""
    cache_strategy = ServiceContainer.get_cache_strategy()
    await cache_strategy.connect()
    app.state.cache_strategy = cache_strategy


@asynccontextmanager
async def lifespan_setup(
    app: FastAPI,
) -> AsyncGenerator[None, None]:  # pragma: no cover
    """
    Actions to run on application startup.

    This function uses fastAPI app to store data
    in the state, such as db_engine and cache_strategy.

    :param app: the fastAPI application.
    :return: function that actually performs actions.
    """

    app.middleware_stack = None
    await _setup_db(app)
    await _setup_cache(app)
    app.middleware_stack = app.build_middleware_stack()

    yield

    # Cleanup on shutdown
    if hasattr(app.state, "db_strategy"):
        await app.state.db_strategy.disconnect()
    if hasattr(app.state, "cache_strategy"):
        await app.state.cache_strategy.disconnect()
    if hasattr(app.state, "db_client"):
        app.state.db_client.close()
