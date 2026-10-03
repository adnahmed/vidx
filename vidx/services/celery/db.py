"""Beanie/Mongo setup for Celery tasks.

Celery worker processes do not run the FastAPI lifespan, so tasks that need
database access initialize Beanie on a persistent worker event loop here.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, TypeVar

import beanie
from motor.motor_asyncio import AsyncIOMotorClient

from vidx.settings import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class _WorkerState:
    loop: Optional[asyncio.AbstractEventLoop] = None
    client: Optional[AsyncIOMotorClient] = None
    initialized: bool = False


_state = _WorkerState()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    if _state.loop is None or _state.loop.is_closed():
        _state.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_state.loop)
    return _state.loop


async def _init_beanie() -> None:
    from vidx.db.models import load_all_models

    _state.client = AsyncIOMotorClient(str(settings.db_url))
    await beanie.init_beanie(
        database=_state.client[settings.db_base],
        document_models=load_all_models(),  # type: ignore[arg-type]
    )
    logger.info("Celery worker Beanie initialized")


def run_with_db(coro_factory: Callable[[], Awaitable[T]]) -> T:
    """Run an async function on the worker loop, initializing Beanie lazily."""
    loop = _ensure_loop()
    if not _state.initialized:
        loop.run_until_complete(_init_beanie())
        _state.initialized = True
    return loop.run_until_complete(coro_factory())
