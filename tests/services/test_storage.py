"""Tests for the storage abstraction and public generated-media route."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from vidx.services.storage.local import LocalStorageStrategy
from vidx.settings import settings


@pytest.mark.anyio
async def test_local_save_bytes_and_materialize(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "local_storage_dir", str(tmp_path))
    strategy = LocalStorageStrategy()
    ref = await strategy.save_bytes(b"hello", "file.bin")
    assert Path(ref).exists()
    assert Path(ref).read_bytes() == b"hello"
    materialized = await strategy.materialize(ref)
    assert materialized == ref


@pytest.mark.anyio
async def test_local_save_from_file_url_copies_into_storage(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "local_storage_dir", str(tmp_path / "store"))
    source = tmp_path / "source.png"
    source.write_bytes(b"png-bytes")
    strategy = LocalStorageStrategy()
    ref = await strategy.save_from_url(source.as_uri(), "image.png")
    assert ref != str(source)
    assert Path(ref).read_bytes() == b"png-bytes"


@pytest.mark.anyio
async def test_media_route_rejects_traversal(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "local_storage_dir", str(tmp_path))
    (tmp_path / "safe.png").write_bytes(b"x")

    from vidx.web.api.media.views import router as media_router

    app = FastAPI()
    app.include_router(media_router, prefix="/api/media")
    async with AsyncClient(app=app, base_url="http://test") as client:
        ok = await client.get("/api/media/generated/safe.png")
        assert ok.status_code == 200
        bad = await client.get("/api/media/generated/..%2Fsecret")
        assert bad.status_code in (400, 404)
        missing = await client.get("/api/media/generated/nope.png")
        assert missing.status_code == 404
