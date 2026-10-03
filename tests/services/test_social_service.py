"""Tests for social platform validation, scheduling math and publishing."""

from __future__ import annotations

from datetime import date

import pytest
from beanie import PydanticObjectId

from vidx.db.models.project import Project, ProjectType
from vidx.db.models.social_post import PostStatus
from vidx.services.social.registry import platform_registry
from vidx.services.social.service import (
    PostValidationError,
    SocialPublishingService,
    compute_scheduled_at_utc,
    is_valid_timezone,
)


def make_project(**overrides) -> Project:
    defaults = dict(
        user_id=PydanticObjectId(),
        project_type=ProjectType.SOCIAL_CAMPAIGN,
        name="Launch",
        platform="linkedin",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        timezone="Europe/Berlin",
    )
    defaults.update(overrides)
    return Project(**defaults)


def validate(project: Project, **overrides):
    payload = dict(
        project=project,
        platform=project.platform or "linkedin",
        content="Hello world",
        day=date(2026, 1, 10),
        time_str="09:30",
        timezone_name="Europe/Berlin",
        link=None,
        hashtags=[],
        status=PostStatus.DRAFT,
    )
    payload.update(overrides)
    return SocialPublishingService().validate_fields(**payload)


def test_valid_post_passes() -> None:
    validate(make_project())


def test_date_outside_project_range_rejected() -> None:
    with pytest.raises(PostValidationError) as exc:
        validate(make_project(), day=date(2026, 2, 5))
    assert any("within the project range" in error for error in exc.value.errors)


def test_content_length_limit_enforced() -> None:
    with pytest.raises(PostValidationError) as exc:
        validate(make_project(), content="x" * 3001)
    assert any("character limit" in error for error in exc.value.errors)


def test_time_required_and_validated() -> None:
    with pytest.raises(PostValidationError):
        validate(make_project(), time_str="")
    with pytest.raises(PostValidationError):
        validate(make_project(), time_str="25:99")


def test_invalid_timezone_rejected() -> None:
    assert is_valid_timezone("Europe/Berlin")
    assert not is_valid_timezone("Mars/Olympus")
    with pytest.raises(PostValidationError):
        validate(make_project(), timezone_name="Mars/Olympus")


def test_invalid_link_rejected() -> None:
    with pytest.raises(PostValidationError):
        validate(make_project(), link="ftp://example.com")


def test_unsupported_platform_rejected() -> None:
    with pytest.raises(PostValidationError):
        validate(make_project(platform="myspace"), platform="myspace")


def test_scheduled_at_uses_timezone_and_dst() -> None:
    # 2026-03-29 is the DST switch in Europe/Berlin (CET+1 -> CEST+2).
    winter = compute_scheduled_at_utc(date(2026, 1, 15), "12:00", "Europe/Berlin")
    summer = compute_scheduled_at_utc(date(2026, 6, 15), "12:00", "Europe/Berlin")
    dst_day = compute_scheduled_at_utc(date(2026, 3, 29), "03:30", "Europe/Berlin")
    assert winter.hour == 11
    assert summer.hour == 10
    assert dst_day.hour == 1
    assert dst_day.minute == 30


def test_registry_exposes_linkedin_and_planned_platforms() -> None:
    capabilities = {cap.platform: cap for cap in platform_registry.list_capabilities()}
    assert capabilities["linkedin"].availability.value == "available"
    for platform in ("facebook", "instagram", "threads", "x", "tiktok", "youtube"):
        assert capabilities[platform].availability.value == "planned"


@pytest.mark.anyio
async def test_linkedin_adapter_reports_missing_credentials(monkeypatch) -> None:
    from vidx.services.social.base import PostPayload, ProjectContext
    from vidx.services.social.linkedin import LinkedInAdapter
    from vidx.settings import settings

    monkeypatch.setattr(settings, "linkedin_access_token", None)
    monkeypatch.setattr(settings, "linkedin_author_urn", None)
    result = await LinkedInAdapter().publish(
        PostPayload(content="Hi"), ProjectContext(project_id="1", name="P"),
    )
    assert result.success is False
    assert result.error is not None and "not configured" in result.error
