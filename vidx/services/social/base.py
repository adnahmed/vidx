"""Platform abstraction for social media publishing.

LinkedIn is the first concrete adapter. Facebook, Instagram, Threads, X,
TikTok and YouTube can be added by implementing ``SocialPlatformAdapter`` and
registering the adapter — no route or service changes required.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

from pydantic import BaseModel


class PlatformAvailability(str, enum.Enum):
    """Whether a platform can publish today or is planned."""

    AVAILABLE = "available"
    PLANNED = "planned"


class PlatformCapabilities(BaseModel):
    """Machine-readable limits/features so the UI can validate before submit."""

    platform: str
    label: str
    availability: PlatformAvailability
    max_content_length: int
    max_hashtags: Optional[int] = None
    supports_images: bool = True
    supports_links: bool = True
    supports_scheduling: bool = False
    notes: str = ""


@dataclass
class PostPayload:
    """Normalized post data passed to platform adapters."""

    content: str
    image_url: Optional[str] = None
    link: Optional[str] = None
    hashtags: List[str] = field(default_factory=list)
    scheduled_at_utc: Optional[object] = None


@dataclass
class ProjectContext:
    """Minimal project data needed by an adapter."""

    project_id: str
    name: str
    description: Optional[str] = None
    timezone: Optional[str] = None


@dataclass
class PublishResult:
    """Outcome of a publish attempt."""

    success: bool
    provider_post_id: Optional[str] = None
    error: Optional[str] = None
    raw: Optional[dict] = None


class SocialPlatformAdapter(ABC):
    """Interface every social platform integration must implement."""

    platform: str
    capabilities: PlatformCapabilities

    @abstractmethod
    async def validate_post(self, payload: PostPayload) -> List[str]:
        """Return a list of human-readable validation errors (empty = valid)."""
        raise NotImplementedError

    @abstractmethod
    async def publish(self, payload: PostPayload, project: ProjectContext) -> PublishResult:
        """Publish (or schedule, when the platform supports it) immediately."""
        raise NotImplementedError
