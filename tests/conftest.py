import sys
from types import ModuleType

if "magic" not in sys.modules:
    magic_stub = ModuleType("magic")

    class _MagicStub:
        def __init__(self, mime: bool = False) -> None:
            self.mime = mime

        def from_file(self, file_path: str) -> str:
            return "video/mp4" if self.mime else "application/octet-stream"

        def from_buffer(self, _buffer: bytes, mime: bool | None = None) -> str:
            _ = mime
            return "video/mp4" if self.mime else "application/octet-stream"

    magic_stub.Magic = _MagicStub
    sys.modules["magic"] = magic_stub

from typing import Any, AsyncGenerator

import beanie
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

from vidx.settings import settings
from vidx.web.application import get_app


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """
    Backend for anyio pytest plugin.

    :return: backend name.
    """
    return "asyncio"


@pytest.fixture(autouse=True)
async def setup_db() -> AsyncGenerator[None, None]:
    """
    Fixture to create database connection.

    Tests run against an in-memory MongoDB (mongomock-motor) so the full
    Beanie model/DAO layer is exercised without an external database.

    :yield: nothing.
    """
    from vidx.db.models import load_all_models

    if settings.environment.lower() in {"pytest", "test"}:
        from mongomock_motor import AsyncMongoMockClient

        mock_client = AsyncMongoMockClient()
        await beanie.init_beanie(
            database=mock_client[settings.db_base],
            document_models=load_all_models(),  # type: ignore[arg-type]
        )
        yield
        return

    client = AsyncIOMotorClient(settings.db_url.human_repr())  # type: ignore
    await beanie.init_beanie(
        database=client[settings.db_base],
        document_models=load_all_models(),  # type: ignore
    )
    yield
    client.close()


@pytest.fixture
def fastapi_app() -> FastAPI:
    """
    Fixture for creating FastAPI app.

    :return: fastapi app with mocked dependencies.
    """
    return get_app()


@pytest.fixture
async def client(
    fastapi_app: FastAPI,
    anyio_backend: Any,
) -> AsyncGenerator[AsyncClient, None]:
    """
    Fixture that creates client for requesting server.

    :param fastapi_app: the application.
    :yield: client for the app.
    """
    async with AsyncClient(app=fastapi_app, base_url="http://test", timeout=2.0) as ac:
        yield ac
