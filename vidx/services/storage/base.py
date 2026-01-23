from __future__ import annotations

from abc import ABC, abstractmethod
from typing import IO, Union

from fastapi import UploadFile


class StorageProvider(ABC):
    """Abstract storage provider interface."""

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
