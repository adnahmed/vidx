"""Redis cache strategy implementation."""

from typing import Any, Optional

import redis.asyncio as redis

from .base import CacheStrategy


class RedisStrategy(CacheStrategy):
    """Redis cache strategy."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
    ):
        """Initialize Redis strategy.
        
        Args:
            host: Redis host
            port: Redis port
            db: Redis database number
            password: Optional Redis password
        """
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self.client: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Establish Redis connection."""
        self.client = await redis.from_url(
            f"redis://{'user:' + self.password + '@' if self.password else ''}{self.host}:{self.port}/{self.db}",
            encoding="utf8",
            decode_responses=True,
        )

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self.client:
            await self.client.close()

    async def health_check(self) -> bool:
        """Check if Redis is healthy."""
        try:
            if self.client:
                await self.client.ping()
                return True
        except Exception:
            return False
        return False

    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        try:
            if self.client:
                return await self.client.get(key)
        except Exception:
            pass
        return None

    async def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        """Set value in cache with TTL."""
        try:
            if self.client:
                await self.client.setex(key, ttl, value)
        except Exception:
            pass

    async def delete(self, key: str) -> None:
        """Delete value from cache."""
        try:
            if self.client:
                await self.client.delete(key)
        except Exception:
            pass

    async def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        try:
            if self.client:
                return await self.client.exists(key) > 0
        except Exception:
            return False
        return False

    async def clear(self) -> None:
        """Clear all cache."""
        try:
            if self.client:
                await self.client.flushdb()
        except Exception:
            pass
