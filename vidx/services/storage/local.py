import shutil
import tempfile
import uuid as std_uuid
from pathlib import Path
from typing import Union

from fastapi import UploadFile

from .base import StorageProvider


class LocalStorageStrategy(StorageProvider):
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

    async def generate_download_url(self, location: str) -> str:
        # Local path: return file path as-is (caller will serve FileResponse)
        return location
