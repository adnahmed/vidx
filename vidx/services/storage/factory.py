"""Storage provider factory used by API routes and services."""

from __future__ import annotations

from vidx.services.storage.base import StorageProvider
from vidx.services.storage.local import LocalStorageStrategy
from vidx.services.storage.s3 import AWSS3Strategy
from vidx.settings import settings


def get_storage_provider() -> StorageProvider:
    """Return the configured storage provider (local by default, S3 when selected)."""
    if settings.storage_type.lower() == "s3":
        return AWSS3Strategy()
    return LocalStorageStrategy()
