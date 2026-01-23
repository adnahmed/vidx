"""Abstract base classes for cache strategies."""

from abc import ABC, abstractmethod
from typing import Any, Optional


class CacheStrategy(ABC):
    """Abstract cache strategy interface."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish cache connection."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close cache connection."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if cache is healthy and accessible."""
        pass

    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        pass

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        """Set value in cache with optional TTL (seconds)."""
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete value from cache."""
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        pass

    @abstractmethod
    async def clear(self) -> None:
        """Clear all cache."""
        pass
