from contextlib import asynccontextmanager
from typing import AsyncGenerator

import beanie
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient

from vidx.db.models import load_all_models
from vidx.settings import settings


async def _setup_db(app: FastAPI) -> None:
    client = AsyncIOMotorClient(str(settings.db_url))  # type: ignore
    app.state.db_client = client
    await beanie.init_beanie(
        database=client[settings.db_base],
        document_models=load_all_models(),  # type: ignore
    )


@asynccontextmanager
async def lifespan_setup(
    app: FastAPI,
) -> AsyncGenerator[None, None]:  # pragma: no cover
    """
    Actions to run on application startup.

    This function uses fastAPI app to store data
    in the state, such as db_engine.

    :param app: the fastAPI application.
    :return: function that actually performs actions.
    """

    app.middleware_stack = None
    await _setup_db(app)
    app.middleware_stack = app.build_middleware_stack()

    yield
