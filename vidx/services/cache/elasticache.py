"""AWS ElastiCache (Redis-compatible) cache strategy implementation."""

from typing import Any, Optional

import redis.asyncio as redis

from .base import CacheStrategy


class ElastiCacheStrategy(CacheStrategy):
    """ElastiCache (Redis-compatible) cache strategy."""

    def __init__(
        self,
        endpoint: str,
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        ssl: bool = True,
    ):
        """Initialize ElastiCache strategy.
        
        Args:
            endpoint: ElastiCache endpoint (DNS name or IP)
            port: ElastiCache port (default 6379)
            db: Database number (default 0)
            password: Optional AUTH token for ElastiCache with AUTH enabled
            ssl: Whether to use SSL/TLS (default True for AWS)
        """
        self.endpoint = endpoint
        self.port = port
        self.db = db
        self.password = password
        self.ssl = ssl
        self.client: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Establish ElastiCache connection."""
        protocol = "rediss" if self.ssl else "redis"
        auth_part = f":{self.password}@" if self.password else ""
        connection_url = f"{protocol}://{auth_part}{self.endpoint}:{self.port}/{self.db}"

        self.client = await redis.from_url(
            connection_url,
            encoding="utf8",
            decode_responses=True,
            ssl_certfile=None,
            ssl_keyfile=None,
            ssl_cert_reqs="none" if not self.ssl else "required",
        )

    async def disconnect(self) -> None:
        """Close ElastiCache connection."""
        if self.client:
            await self.client.close()

    async def health_check(self) -> bool:
        """Check if ElastiCache is healthy."""
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
