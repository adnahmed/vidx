"""Project model shared by Video Production and Social Media Campaign types."""

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Annotated, Any, ClassVar, Dict, Optional

from beanie import Document, Indexed, PydanticObjectId
from pydantic import BaseModel, Field


class ProjectType(str, enum.Enum):
    """Supported project types under the Social Media tab."""

    VIDEO_PRODUCTION = "video_production"
    SOCIAL_CAMPAIGN = "social_campaign"


class ProjectStatus(str, enum.Enum):
    """Lifecycle status of a project."""

    DRAFT = "draft"
    ACTIVE = "active"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"


class ComponentStatus(str, enum.Enum):
    """Status of a single generated/rendered component."""

    IDLE = "idle"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ComponentState(BaseModel):
    """
    Tracks one generated artifact (image, video, audio, subtitle, render).

    Only references are stored here: provider identifiers, a storage reference
    returned by the StorageService, statuses, errors and timestamps. Media blobs
    never live in the database.
    """

    status: ComponentStatus = ComponentStatus.IDLE
    provider: Optional[str] = None
    provider_job_id: Optional[str] = None
    correlation_id: Optional[str] = None
    storage_ref: Optional[str] = None
    source_url: Optional[str] = None
    mime_type: Optional[str] = None
    error: Optional[str] = None
    attempts: int = 0
    submitted_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Project(Document):
    """A project owned by a user: video production or social media campaign."""

    user_id: Annotated[PydanticObjectId, Indexed()]
    project_type: Annotated[ProjectType, Indexed()]
    name: str
    description: Optional[str] = None

    # Social Media Campaign fields
    platform: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    timezone: Optional[str] = None

    # Shared assets / configuration
    image_ref: Optional[str] = None
    status: ProjectStatus = ProjectStatus.DRAFT
    final_video: ComponentState = Field(default_factory=ComponentState)
    options: Dict[str, Any] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "projects"
        indexes: ClassVar[list[str]] = ["-created_at"]

    async def save(self, *args: Any, **kwargs: Any) -> "Project":
        self.updated_at = datetime.utcnow()
        return await super().save(*args, **kwargs)
