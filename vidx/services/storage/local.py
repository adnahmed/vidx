import shutil
import tempfile
import uuid as std_uuid
from pathlib import Path
from typing import Union

import httpx
from fastapi import UploadFile

from vidx.settings import settings

from .base import StorageProvider


class LocalStorageStrategy(StorageProvider):
    """
    Filesystem-backed storage.

    Uploads keep using the system temp directory (existing merge behaviour).
    Generated artifacts are written under ``local_storage_dir`` so they are
    grouped and easy to serve.
    """

    def _base_dir(self) -> Path:
        base = Path(settings.local_storage_dir)
        base.mkdir(parents=True, exist_ok=True)
        return base

    async def save_upload(self, upload: Union[UploadFile, str]) -> str:
        if isinstance(upload, str):
            # Assume it's already a URL or path; just return as-is
            return upload

        original_filename = upload.filename or str(std_uuid.uuid4())
        path_obj = Path(original_filename)
        suffix = path_obj.suffix or ""
        if suffix and not suffix.startswith("."):
            suffix = "." + suffix

        with tempfile.NamedTemporaryFile(delete=False, prefix=path_obj.stem + "_", suffix=suffix) as tmp_final:
            await upload.seek(0)
            shutil.copyfileobj(upload.file, tmp_final)
            await upload.seek(0)
            return tmp_final.name

    async def save_bytes(self, data: bytes, filename: str) -> str:
        target = self._base_dir() / f"{std_uuid.uuid4().hex}_{self._safe_filename(filename)}"
        target.write_bytes(data)
        return str(target)

    async def generate_download_url(self, location: str) -> str:
        # Local path: return file path as-is (caller will serve FileResponse)
        return location

    async def materialize(self, location: str) -> str:
        if location.startswith(("http://", "https://")):
            target = self._temp_path(location)
            async with httpx.AsyncClient(
                timeout=float(settings.provider_download_timeout_seconds),
                follow_redirects=True,
            ) as client, client.stream("GET", location) as response:
                response.raise_for_status()
                with target.open("wb") as handle:
                    async for chunk in response.aiter_bytes():
                        handle.write(chunk)
            return str(target)
        return location
