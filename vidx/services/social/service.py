"""Social post validation, scheduling and publishing service."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from vidx.db.models.project import Project
from vidx.db.models.social_post import PostStatus, SocialPost
from vidx.services.social.base import PostPayload, ProjectContext
from vidx.services.social.registry import platform_registry

logger = logging.getLogger(__name__)


class PostValidationError(ValueError):
    """Raised when a post payload violates project/platform rules."""

    def __init__(self, errors: List[str]) -> None:
        super().__init__(" | ".join(errors))
        self.errors = errors


def resolve_timezone(name: Optional[str]) -> ZoneInfo:
    """Resolve an IANA timezone name, falling back to UTC."""
    if not name:
        return ZoneInfo("UTC")
    return ZoneInfo(name)


def is_valid_timezone(name: Optional[str]) -> bool:
    """Return True when the name is a known IANA timezone."""
    if not name:
        return False
    try:
        ZoneInfo(name)
        return True
    except ZoneInfoNotFoundError:
        return False


def parse_time(value: str) -> time:
    """Parse an HH:MM (or HH:MM:SS) string."""
    try:
        parts = value.strip().split(":")
        if len(parts) == 2:
            hour, minute = parts
            second = "0"
        elif len(parts) == 3:
            hour, minute, second = parts
        else:
            raise ValueError(value)
        return time(int(hour), int(minute), int(second))
    except (TypeError, ValueError) as exc:
        raise PostValidationError([f"Invalid time '{value}'. Expected HH:MM."]) from exc


def compute_scheduled_at_utc(
    day: date, time_str: str, timezone_name: str,
) -> datetime:
    """Combine local date+time with the IANA timezone into a UTC instant."""
    tz = resolve_timezone(timezone_name)
    local_dt = datetime.combine(day, parse_time(time_str))
    return local_dt.replace(tzinfo=tz).astimezone(timezone.utc)


def to_project_context(project: Project) -> ProjectContext:
    return ProjectContext(
        project_id=str(project.id),
        name=project.name,
        description=project.description,
        timezone=project.timezone,
    )


class SocialPublishingService:
    """Owns post validation, scheduling math and publish attempts."""

    def validate_fields(
        self,
        *,
        project: Project,
        platform: str,
        content: str,
        day: Optional[date],
        time_str: Optional[str],
        timezone_name: Optional[str],
        link: Optional[str],
        hashtags: List[str],
        status: PostStatus,
    ) -> None:
        errors: List[str] = []

        if not day:
            errors.append("Date is required.")
        elif (
            project.start_date
            and project.end_date
            and (day < project.start_date or day > project.end_date)
        ):
            errors.append(
                f"Date must be within the project range "
                f"({project.start_date} - {project.end_date}).",
            )

        if not time_str:
            errors.append("Time is required.")
        else:
            try:
                parse_time(time_str)
            except PostValidationError as exc:
                errors.extend(exc.errors)

        if not timezone_name:
            errors.append("Timezone is required.")
        elif not is_valid_timezone(timezone_name):
            errors.append(f"Unknown timezone '{timezone_name}'.")

        content = content or ""
        if not content.strip():
            errors.append("Content is required.")

        if link and not link.startswith(("http://", "https://")):
            errors.append("Link must be a valid http(s) URL.")

        adapter = platform_registry.get(platform)
        if adapter is None:
            errors.append(f"Unsupported platform '{platform}'.")
        else:
            # Content-length/platform checks only; configuration is checked at publish.
            if len(content) > adapter.capabilities.max_content_length:
                errors.append(
                    f"Content exceeds {adapter.capabilities.label}'s "
                    f"{adapter.capabilities.max_content_length} character limit "
                    f"(got {len(content)}).",
                )
            if not adapter.capabilities.supports_links and link:
                errors.append(f"{adapter.capabilities.label} does not support links.")

        try:
            PostStatus(status)
        except ValueError:
            errors.append(f"Invalid status '{status}'.")

        if errors:
            raise PostValidationError(errors)

    async def validate_with_adapter(self, platform: str, payload: PostPayload) -> List[str]:
        adapter = platform_registry.get(platform)
        if adapter is None:
            return [f"Unsupported platform '{platform}'."]
        return await adapter.validate_post(payload)

    def build_scheduled_at(
        self, *, day: date, time_str: str, timezone_name: str,
    ) -> datetime:
        return compute_scheduled_at_utc(day, time_str, timezone_name)

    async def publish(self, post: SocialPost, project: Project) -> SocialPost:
        """Attempt a single publish and persist the outcome."""
        adapter = platform_registry.get(post.platform)
        post.publish_attempts += 1
        if adapter is None:
            post.status = PostStatus.FAILED
            post.error = f"Unsupported platform '{post.platform}'."
            await post.save()
            return post

        image_url = None
        if post.image_ref:
            from pathlib import Path

            from vidx.services.storage.factory import get_storage_provider

            try:
                image_url = await get_storage_provider().generate_download_url(
                    post.image_ref
                )
                if not image_url.startswith(("http://", "https://")):
                    # Local storage: expose through the public media route so
                    # the platform can fetch it.
                    from vidx.settings import settings as _settings

                    base = (_settings.public_base_url or "").rstrip("/")
                    image_url = f"{base}/api/media/generated/{Path(image_url).name}"
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Could not resolve post image for publishing: %s", exc)

        payload = PostPayload(
            content=post.content,
            image_url=image_url,
            link=post.link,
            hashtags=list(post.hashtags),
            scheduled_at_utc=post.scheduled_at_utc,
        )
        validation_errors = await adapter.validate_post(payload)
        if validation_errors:
            post.status = PostStatus.FAILED
            post.error = " | ".join(validation_errors)
            await post.save()
            return post

        result = await adapter.publish(payload, to_project_context(project))
        if result.success:
            post.status = PostStatus.PUBLISHED
            post.provider_post_id = result.provider_post_id
            post.published_at = datetime.utcnow()
            post.error = None
        else:
            post.status = PostStatus.FAILED
            post.error = result.error or "Publishing failed."
        await post.save()
        return post
