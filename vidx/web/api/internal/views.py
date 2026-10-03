"""Internal artifact endpoint for split deployments.

When the Celery worker runs in a separate container from the API (see
render.yaml), worker-produced artifacts are uploaded here so the API can
serve them. Authenticated with the shared ``VIDX_INTERNAL_TOKEN``.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from starlette import status

from vidx.settings import settings

router = APIRouter()


@router.post("/artifacts")
async def upload_artifact(request: Request, file: UploadFile = File(...)) -> dict:
    if not settings.internal_token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    if request.headers.get("X-Internal-Token") != settings.internal_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal token."
        )

    name = Path(file.filename or "artifact").name.replace("\\", "_").replace("/", "_")
    if not name or ".." in name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid artifact name."
        )

    data = await file.read()
    base = Path(settings.local_storage_dir)
    base.mkdir(parents=True, exist_ok=True)
    target = base / name
    target.write_bytes(data)
    return {"stored": str(target), "name": name}
