"""Storage provider abstraction for local and cloud storage."""

__all__ = ["StorageProvider", "LocalStorageStrategy", "AWSS3Strategy"]

from .base import StorageProvider
from .local import LocalStorageStrategy
from .s3 import AWSS3Strategy
