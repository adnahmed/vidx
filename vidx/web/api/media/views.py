"""Public media serving for generated artifacts.

Only generated artifacts are served here, by unguessable UUID-prefixed
filename, so external providers can fetch inputs without credentials.
User uploads and authenticated media use their project/scene routes.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette import status

from vidx.settings import settings

router = APIRouter()


@router.get("/generated/{name}")
async def serve_generated(name: str) -> FileResponse:
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid name.")
    base = Path(settings.local_storage_dir).resolve()
    target = (base / name).resolve()
    if base not in target.parents or not target.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return FileResponse(target)
