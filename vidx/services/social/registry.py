"""Registry of social platform adapters."""

from __future__ import annotations

from typing import Dict, List

from vidx.services.social.base import (
    PlatformAvailability,
    PlatformCapabilities,
    PostPayload,
    ProjectContext,
    PublishResult,
    SocialPlatformAdapter,
)
from vidx.services.social.linkedin import LinkedInAdapter


class _PlannedPlatform(SocialPlatformAdapter):
    """Capability descriptor for platforms not yet implemented."""

    def __init__(self, platform: str, label: str, max_content_length: int, notes: str) -> None:
        self.platform = platform
        self.capabilities = PlatformCapabilities(
            platform=platform,
            label=label,
            availability=PlatformAvailability.PLANNED,
            max_content_length=max_content_length,
            supports_images=True,
            supports_links=True,
            supports_scheduling=False,
            notes=notes,
        )

    async def validate_post(self, payload: PostPayload) -> List[str]:
        return [f"{self.capabilities.label} is not yet available."]

    async def publish(self, payload: PostPayload, project: ProjectContext) -> PublishResult:
        return PublishResult(
            success=False, error=f"{self.capabilities.label} adapter is not implemented yet.",
        )


class PlatformRegistry:
    """Maps platform identifiers to adapters and exposes capabilities."""

    def __init__(self) -> None:
        self._adapters: Dict[str, SocialPlatformAdapter] = {}
        self.register(LinkedInAdapter())
        self.register(
            _PlannedPlatform("facebook", "Facebook", 63206, "Page posts planned."),
        )
        self.register(
            _PlannedPlatform("instagram", "Instagram", 2200, "Feed/carousel planned."),
        )
        self.register(_PlannedPlatform("threads", "Threads", 500, "Planned."))
        self.register(_PlannedPlatform("x", "X (Twitter)", 280, "Planned."))
        self.register(_PlannedPlatform("tiktok", "TikTok", 2200, "Planned."))
        self.register(
            _PlannedPlatform("youtube", "YouTube", 5000, "Shorts/video metadata planned."),
        )

    def register(self, adapter: SocialPlatformAdapter) -> None:
        self._adapters[adapter.platform] = adapter

    def get(self, platform: str) -> SocialPlatformAdapter | None:
        return self._adapters.get((platform or "").lower())

    def list_capabilities(self) -> List[PlatformCapabilities]:
        order = [
            "linkedin",
            "facebook",
            "instagram",
            "threads",
            "x",
            "tiktok",
            "youtube",
        ]
        result = [
            self._adapters[key].capabilities for key in order if key in self._adapters
        ]
        for key, adapter in self._adapters.items():
            if key not in order:
                result.append(adapter.capabilities)
        return result


platform_registry = PlatformRegistry()
