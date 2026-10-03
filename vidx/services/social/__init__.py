"""Social media platform abstraction and publishing services."""

from vidx.services.social.registry import platform_registry
from vidx.services.social.service import SocialPublishingService

__all__ = ["platform_registry", "SocialPublishingService"]
