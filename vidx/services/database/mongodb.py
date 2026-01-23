"""MongoDB database strategy implementation."""

from typing import Any, Dict, Optional

from beanie import init_beanie, Document
from motor.motor_asyncio import AsyncIOMotorClient

from .base import DatabaseStrategy


class MongoDBDocument(Document):
    """Base MongoDB document model."""

    pass


class MongoDBStrategy(DatabaseStrategy):
    """MongoDB strategy for database operations."""

    def __init__(self, connection_url: str):
        """Initialize MongoDB strategy.
        
        Args:
            connection_url: MongoDB connection string
        """
        self.connection_url = connection_url
        self.client: Optional[AsyncIOMotorClient] = None
        self.db = None

    async def connect(self) -> None:
        """Establish MongoDB connection."""
        self.client = AsyncIOMotorClient(self.connection_url)
        self.db = self.client.vidx

        # Initialize Beanie with document models
        await init_beanie(
            database=self.db,
            document_models=[MongoDBDocument],  # Add your models here
        )

    async def disconnect(self) -> None:
        """Close MongoDB connection."""
        if self.client:
            self.client.close()

    async def health_check(self) -> bool:
        """Check if MongoDB is healthy."""
        try:
            if self.db:
                await self.db.command("ping")
                return True
        except Exception:
            return False
        return False

    async def get(self, key: str) -> Optional[Any]:
        """Get document by ID."""
        if not self.db:
            return None
        try:
            collection = self.db.items
            return await collection.find_one({"_id": key})
        except Exception:
            return None

    async def put(self, key: str, value: Dict[str, Any]) -> None:
        """Insert document."""
        if not self.db:
            return
        try:
            collection = self.db.items
            value["_id"] = key
            await collection.insert_one(value)
        except Exception:
            pass

    async def update(self, key: str, value: Dict[str, Any]) -> None:
        """Update document."""
        if not self.db:
            return
        try:
            collection = self.db.items
            await collection.update_one({"_id": key}, {"$set": value})
        except Exception:
            pass

    async def delete(self, key: str) -> None:
        """Delete document."""
        if not self.db:
            return
        try:
            collection = self.db.items
            await collection.delete_one({"_id": key})
        except Exception:
            pass

    async def query(self, query_params: Dict[str, Any]) -> list:
        """Query documents by parameters."""
        if not self.db:
            return []
        try:
            collection = self.db.items
            cursor = collection.find(query_params)
            return await cursor.to_list(length=None)
        except Exception:
            return []
