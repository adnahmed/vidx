"""Abstract base classes for database strategies."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class DatabaseStrategy(ABC):
    """Abstract database strategy interface."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish database connection."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close database connection."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if database is healthy and accessible."""
        pass

    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        """Get item by key."""
        pass

    @abstractmethod
    async def put(self, key: str, value: Dict[str, Any]) -> None:
        """Put item with key."""
        pass

    @abstractmethod
    async def update(self, key: str, value: Dict[str, Any]) -> None:
        """Update item with key."""
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete item by key."""
        pass

    @abstractmethod
    async def query(self, query_params: Dict[str, Any]) -> list:
        """Query items by parameters."""
        pass
