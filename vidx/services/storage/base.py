from __future__ import annotations

import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Union

import httpx
from fastapi import UploadFile

from vidx.settings import settings


class StorageProvider(ABC):
    """
    Abstract storage provider interface.

    Locations returned by this provider are durable *references* (local path or
    object key) that can be persisted in the database. Media blobs never enter
    the database.
    """

    @abstractmethod
    async def save_upload(self, upload: Union[UploadFile, str]) -> str:
        """
        Save an UploadFile or accept a URL string.

        Returns a location string (local path or remote URL).
        """
        raise NotImplementedError

    @abstractmethod
    async def generate_download_url(self, location: str) -> str:
        """Return a downloadable URL for the given location (path or key/URL)."""
        raise NotImplementedError

    @abstractmethod
    async def save_bytes(self, data: bytes, filename: str) -> str:
        """Persist raw bytes and return a durable storage reference."""
        raise NotImplementedError

    @abstractmethod
    async def materialize(self, location: str) -> str:
        """
        Return a local filesystem path for the given storage reference.

        For local storage this is the path itself. For remote storage the
        object is downloaded into a temp file so FFmpeg can consume it.
        """
        raise NotImplementedError

    async def save_from_url(self, url: str, filename: str) -> str:
        """Stream a remote URL into storage without loading it all in memory."""
        if url.startswith("file://"):
            from urllib.parse import urlparse
            from urllib.request import url2pathname

            parsed = urlparse(url)
            local_path = Path(url2pathname(parsed.path))
            return await self.save_bytes(local_path.read_bytes(), filename)
        chunks = bytearray()
        async with httpx.AsyncClient(
            timeout=float(settings.provider_download_timeout_seconds),
            follow_redirects=True,
        ) as client, client.stream("GET", url) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                chunks.extend(chunk)
        return await self.save_bytes(bytes(chunks), filename)

    @staticmethod
    def _safe_filename(filename: str) -> str:
        candidate = Path(filename).name or "file"
        return candidate.replace("\x00", "") or "file"

    @staticmethod
    def _temp_path(filename: str) -> Path:
        suffix = Path(filename).suffix
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        handle.close()
        return Path(handle.name)
