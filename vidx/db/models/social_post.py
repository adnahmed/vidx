"""Scheduled/published social media post model."""

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Annotated, Any, ClassVar, List, Optional

from beanie import Document, Indexed, PydanticObjectId
from pydantic import Field, field_validator


class PostStatus(str, enum.Enum):
    """Post lifecycle status exposed in the UI."""

    DRAFT = "Draft"
    SCHEDULED = "Scheduled"
    PUBLISHED = "Published"
    FAILED = "Failed"


class SocialPost(Document):
    """
    A single social media post belonging to a campaign project.

    The user-facing schedule is stored as a local date + time plus the user's
    IANA timezone. ``scheduled_at_utc`` is the normalized instant the scheduler
    compares against, so daylight saving changes are handled by the timezone
    database rather than by fixed offsets.
    """

    project_id: Annotated[PydanticObjectId, Indexed()]
    user_id: Annotated[PydanticObjectId, Indexed()]
    platform: Annotated[str, Indexed()]

    content: str
    image_ref: Optional[str] = None
    link: Optional[str] = None
    hashtags: List[str] = Field(default_factory=list)

    date: date
    time: str  # "HH:MM" in the user's timezone
    timezone: str  # IANA name, e.g. "Europe/Berlin"
    scheduled_at_utc: datetime

    status: PostStatus = PostStatus.DRAFT
    error: Optional[str] = None
    provider_post_id: Optional[str] = None
    publish_attempts: int = 0
    claimed_at: Optional[datetime] = None
    published_at: Optional[datetime] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "social_posts"
        indexes: ClassVar[list[str]] = ["-created_at"]

    @field_validator("hashtags", mode="before")
    @classmethod
    def normalize_hashtags(cls, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            parts = [part.strip() for part in value.replace(",", " ").split()]
            return [part for part in parts if part]
        return [str(part).strip() for part in value if str(part).strip()]

    async def save(self, *args: Any, **kwargs: Any) -> "SocialPost":
        self.updated_at = datetime.utcnow()
        return await super().save(*args, **kwargs)
