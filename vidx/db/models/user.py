
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from beanie import Document, Indexed
from pydantic import EmailStr, Field


class User(Document):
    """User document stored in MongoDB."""

    email: Annotated[EmailStr, Indexed(unique=True)]
    hashed_password: str | None = None
    full_name: str | None = None
    is_active: bool = True
    google_sub: Annotated[str | None, Indexed(unique=True, partialFilterExpression={"google_sub": {"$type": "string"}})] = None
    google_access_token: str | None = None
    google_refresh_token: str | None = None
    providers: list[str] = Field(default_factory=list)
    last_login_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "users"

    async def save(self, *args, **kwargs) -> "User":
        self.updated_at = datetime.utcnow()
        return await super().save(*args, **kwargs)

