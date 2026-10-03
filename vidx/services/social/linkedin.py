"""LinkedIn platform adapter (first concrete platform)."""

from __future__ import annotations

import logging
from typing import List, Optional

import httpx

from vidx.services.social.base import (
    PlatformAvailability,
    PlatformCapabilities,
    PostPayload,
    ProjectContext,
    PublishResult,
    SocialPlatformAdapter,
)
from vidx.settings import settings

logger = logging.getLogger(__name__)

LINKEDIN_MAX_COMMENTARY = 3000


class LinkedInAdapter(SocialPlatformAdapter):
    """
    Publishes text (optionally with a single image and/or link) to LinkedIn.

    All LinkedIn-specific protocol details live here: the API base URL, the
    version header, the UGC/Images endpoints and the author URN. Credentials
    come from the environment (never from source or the client).
    """

    platform = "linkedin"
    capabilities = PlatformCapabilities(
        platform="linkedin",
        label="LinkedIn",
        availability=PlatformAvailability.AVAILABLE,
        max_content_length=LINKEDIN_MAX_COMMENTARY,
        max_hashtags=None,
        supports_images=True,
        supports_links=True,
        supports_scheduling=False,
        notes="Publishes as the configured author URN (person or organization).",
    )

    def _headers(self) -> dict:
        version = settings.linkedin_api_version
        # Normalize YYYY-MM-DD to YYYYMM if a date was supplied.
        version = version.replace("-", "")[:6]
        return {
            "Authorization": f"Bearer {settings.linkedin_access_token}",
            "LinkedIn-Version": version,
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }

    def _configuration_error(self) -> Optional[str]:
        missing = []
        if not settings.linkedin_access_token:
            missing.append("VIDX_LINKEDIN_ACCESS_TOKEN")
        if not settings.linkedin_author_urn:
            missing.append("VIDX_LINKEDIN_AUTHOR_URN")
        if missing:
            return (
                "LinkedIn is not configured on the server. Missing: "
                + ", ".join(missing)
            )
        return None

    async def validate_post(self, payload: PostPayload) -> List[str]:
        errors: List[str] = []
        content = (payload.content or "").strip()
        if not content:
            errors.append("Content is required.")
        elif len(content) > LINKEDIN_MAX_COMMENTARY:
            errors.append(
                f"Content exceeds LinkedIn's {LINKEDIN_MAX_COMMENTARY} character limit "
                f"(got {len(content)}).",
            )
        if payload.image_url and payload.image_url.startswith("file://"):
            errors.append("Image could not be referenced for publishing.")
        if errors:
            return errors
        configuration_error = self._configuration_error()
        if configuration_error:
            # Configuration problems are surfaced at publish time, not as
            # content validation failures, so drafts can still be stored.
            return []
        return errors

    async def _upload_image(self, image_url: str, author_urn: str) -> Optional[str]:
        """Initialize an image upload, transfer bytes, return the image URN."""
        base = settings.linkedin_api_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            init_response = await client.post(
                f"{base}/rest/images?action=initializeUpload",
                headers=self._headers(),
                json={"initializeUploadRequest": {"owner": author_urn}},
            )
            init_response.raise_for_status()
            value = init_response.json().get("value", {})
            upload_url = value.get("uploadUrl")
            image_urn = value.get("image")
            if not upload_url or not image_urn:
                raise RuntimeError("LinkedIn image initializeUpload returned no upload URL")
            async with client.stream("GET", image_url) as source:
                source.raise_for_status()
                data = await source.aread()
            upload_response = await client.put(
                upload_url,
                content=data,
                headers={
                    "Authorization": f"Bearer {settings.linkedin_access_token}",
                    "Content-Type": "application/octet-stream",
                },
            )
            upload_response.raise_for_status()
        return image_urn

    async def publish(self, payload: PostPayload, project: ProjectContext) -> PublishResult:
        configuration_error = self._configuration_error()
        if configuration_error:
            return PublishResult(success=False, error=configuration_error)

        author_urn = settings.linkedin_author_urn
        if not author_urn:
            return PublishResult(success=False, error="LinkedIn author URN is not configured.")

        commentary = (payload.content or "").strip()
        if payload.hashtags:
            tags = " ".join(
                tag if tag.startswith("#") else f"#{tag}" for tag in payload.hashtags
            )
            commentary = f"{commentary}\n\n{tags}".strip()
        if payload.link:
            commentary = f"{commentary}\n\n{payload.link}".strip()

        body: dict = {
            "author": author_urn,
            "commentary": commentary,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }

        try:
            image_urn = None
            if payload.image_url:
                image_urn = await self._upload_image(payload.image_url, author_urn)
            if image_urn:
                body["content"] = {"media": {"id": image_urn}}

            base = settings.linkedin_api_base_url.rstrip("/")
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{base}/rest/posts", headers=self._headers(), json=body,
                )
            if response.status_code not in (200, 201):
                detail = response.text[:500]
                return PublishResult(
                    success=False,
                    error=f"LinkedIn publish failed ({response.status_code}): {detail}",
                )
            post_id = response.headers.get("x-restli-id") or response.headers.get("X-RestLi-Id")
            return PublishResult(success=True, provider_post_id=post_id)
        except httpx.HTTPError as exc:
            logger.warning("LinkedIn publish transport error: %s", exc)
            return PublishResult(success=False, error=f"LinkedIn request failed: {exc}")
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Unexpected LinkedIn publish error")
            return PublishResult(success=False, error=str(exc))
