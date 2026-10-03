"""API-level tests for project/post validation against an in-memory MongoDB."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from beanie import PydanticObjectId
from fastapi import FastAPI, Request
from httpx import AsyncClient

from vidx.web.api.projects import views

TEST_USER_ID = PydanticObjectId()


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()

    @application.middleware("http")
    async def inject_user(request: Request, call_next):
        request.state.user = SimpleNamespace(id=TEST_USER_ID)
        return await call_next(request)

    application.include_router(views.router, prefix="/api/projects")
    application.include_router(views.posts_router, prefix="/api/posts")
    application.include_router(views.social_router, prefix="/api/social")
    return application


@pytest.fixture
async def client(app: FastAPI):
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


async def create_campaign(client: AsyncClient, **overrides):
    data = {
        "project_type": "social_campaign",
        "name": "Launch",
        "platform": "linkedin",
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "timezone": "Europe/Berlin",
    }
    data.update(overrides)
    return await client.post("/api/projects", data=data)


@pytest.mark.anyio
async def test_platforms_endpoint_lists_linkedin_first(client: AsyncClient) -> None:
    response = await client.get("/api/social/platforms")
    assert response.status_code == 200
    platforms = response.json()
    assert platforms[0]["platform"] == "linkedin"
    assert platforms[0]["availability"] == "available"
    assert platforms[0]["max_content_length"] == 3000


@pytest.mark.anyio
async def test_campaign_requires_platform(client: AsyncClient) -> None:
    response = await client.post(
        "/api/projects",
        data={
            "project_type": "social_campaign",
            "name": "Launch",
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "timezone": "Europe/Berlin",
        },
    )
    assert response.status_code == 400
    assert "Platform is required" in response.json()["detail"]


@pytest.mark.anyio
async def test_campaign_end_date_cannot_precede_start(client: AsyncClient) -> None:
    response = await create_campaign(
        client, start_date="2026-02-01", end_date="2026-01-01",
    )
    assert response.status_code == 400
    assert "End date cannot precede" in response.json()["detail"]


@pytest.mark.anyio
async def test_campaign_creation_succeeds(client: AsyncClient) -> None:
    response = await create_campaign(client, description="Q1 launch")
    assert response.status_code == 201
    body = response.json()
    assert body["project_type"] == "social_campaign"
    assert body["platform"] == "linkedin"

    listing = await client.get("/api/projects", params={"project_type": "social_campaign"})
    assert listing.status_code == 200
    assert len(listing.json()) == 1


@pytest.mark.anyio
async def test_video_production_creation_needs_no_dates(client: AsyncClient) -> None:
    response = await client.post(
        "/api/projects",
        data={"project_type": "video_production", "name": "Explainer"},
    )
    assert response.status_code == 201
    assert response.json()["project_type"] == "video_production"


@pytest.mark.anyio
async def test_post_content_limit_enforced(client: AsyncClient) -> None:
    project_id = (await create_campaign(client)).json()["id"]
    response = await client.post(
        f"/api/projects/{project_id}/posts",
        data={
            "content": "x" * 3100,
            "date": "2026-01-10",
            "time": "09:00",
            "timezone": "Europe/Berlin",
            "status": "Draft",
        },
    )
    assert response.status_code == 400
    assert "character limit" in response.json()["detail"]


@pytest.mark.anyio
async def test_post_date_must_be_inside_project_range(client: AsyncClient) -> None:
    project_id = (await create_campaign(client)).json()["id"]
    response = await client.post(
        f"/api/projects/{project_id}/posts",
        data={
            "content": "Hello",
            "date": "2026-03-10",
            "time": "09:00",
            "timezone": "Europe/Berlin",
            "status": "Scheduled",
        },
    )
    assert response.status_code == 400
    assert "within the project range" in response.json()["detail"]


@pytest.mark.anyio
async def test_post_time_is_required(client: AsyncClient) -> None:
    project_id = (await create_campaign(client)).json()["id"]
    response = await client.post(
        f"/api/projects/{project_id}/posts",
        data={
            "content": "Hello",
            "date": "2026-01-10",
            "time": "",
            "timezone": "Europe/Berlin",
            "status": "Draft",
        },
    )
    assert response.status_code == 400
    assert "Time is required" in response.json()["detail"]


@pytest.mark.anyio
async def test_post_creation_succeeds_with_timezone_conversion(client: AsyncClient) -> None:
    project_id = (await create_campaign(client)).json()["id"]
    response = await client.post(
        f"/api/projects/{project_id}/posts",
        data={
            "content": "Hello world",
            "date": "2026-01-10",
            "time": "12:00",
            "timezone": "Europe/Berlin",
            "hashtags": "launch, product",
            "status": "Scheduled",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "Scheduled"
    # 12:00 CET == 11:00 UTC
    assert "11:00:00" in body["scheduled_at_utc"]
    assert body["hashtags"] == ["launch", "product"]


@pytest.mark.anyio
async def test_calendar_reports_per_day_counts(client: AsyncClient) -> None:
    project_id = (await create_campaign(client)).json()["id"]
    for content, day in (("first", "2026-01-05"), ("second", "2026-01-05"), ("third", "2026-01-07")):
        created = await client.post(
            f"/api/projects/{project_id}/posts",
            data={
                "content": content,
                "date": day,
                "time": "10:00",
                "timezone": "Europe/Berlin",
                "status": "Draft",
            },
        )
        assert created.status_code == 201

    response = await client.get(f"/api/projects/{project_id}/calendar")
    assert response.status_code == 200
    body = response.json()
    counts = {day["date"]: day["count"] for day in body["days"]}
    assert counts["2026-01-05"] == 2
    assert counts["2026-01-07"] == 1
    assert counts["2026-01-06"] == 0
    assert len(body["days"]) == 31
    assert len(body["posts"]) == 3


@pytest.mark.anyio
async def test_post_update_and_delete(client: AsyncClient) -> None:
    project_id = (await create_campaign(client)).json()["id"]
    created = await client.post(
        f"/api/projects/{project_id}/posts",
        data={
            "content": "draft",
            "date": "2026-01-10",
            "time": "10:00",
            "timezone": "Europe/Berlin",
            "status": "Draft",
        },
    )
    post_id = created.json()["id"]

    updated = await client.put(
        f"/api/posts/{post_id}",
        data={
            "content": "updated content",
            "date": "2026-01-11",
            "time": "11:30",
            "timezone": "Europe/Berlin",
            "status": "Scheduled",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["content"] == "updated content"
    assert updated.json()["status"] == "Scheduled"

    deleted = await client.delete(f"/api/posts/{post_id}")
    assert deleted.status_code == 204

    listing = await client.get(f"/api/projects/{project_id}/posts")
    assert listing.json() == []
