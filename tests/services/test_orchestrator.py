"""Tests for the generation orchestrator: gating, callbacks and continuation."""

from __future__ import annotations

from datetime import datetime

import pytest
from beanie import PydanticObjectId

from vidx.db.models.project import (
    ComponentStatus,
    Project,
    ProjectType,
)
from vidx.db.models.scene import Scene
from vidx.services.generation import GenerationError, generation_orchestrator
from vidx.services.providers import GenerationComponent
from vidx.services.providers.base import (
    AIProvider,
    GenerationRequest,
    ProviderCallback,
    ProviderJob,
)


class FakeProvider(AIProvider):
    def __init__(self) -> None:
        self.name = "fake"
        self.component = GenerationComponent.IMAGE
        self.submitted: list[GenerationRequest] = []

    async def submit_job(self, request: GenerationRequest) -> ProviderJob:
        self.submitted.append(request)
        return ProviderJob(
            provider=self.name, job_id="job-123", correlation_id=request.correlation_id,
        )

    def parse_webhook(self, payload):  # pragma: no cover - not used here
        return None


class FakeStorage:
    def __init__(self) -> None:
        self.saved: list[tuple[str, str]] = []

    async def save_from_url(self, url: str, filename: str) -> str:
        self.saved.append((url, filename))
        return f"stored/{filename}"

    async def generate_download_url(self, location: str) -> str:
        return f"http://media.local/{location}"


def make_scene(**overrides) -> Scene:
    defaults = dict(
        id=PydanticObjectId(),
        project_id=PydanticObjectId(),
        scene_number=1,
        image_prompt="a lighthouse",
        scene_prompt="the lighthouse sweeps",
        audio_prompt="waves crashing",
    )
    defaults.update(overrides)
    return Scene(**defaults)


def make_project(scene: Scene) -> Project:
    return Project(
        user_id=PydanticObjectId(),
        project_type=ProjectType.VIDEO_PRODUCTION,
        name="Film",
        options={"resolution": [1280, 720]},
    )


class FakeSceneDAO:
    """In-memory stand-in for atomic SceneDAO operations."""

    def __init__(self, scene: Scene) -> None:
        self.scene = scene
        self.saved = 0

    async def find_by_provider_job(self, *, provider: str, provider_job_id: str, component: str):
        state = getattr(self.scene, component)
        if state.provider == provider and state.provider_job_id == provider_job_id:
            return self.scene
        return None

    async def get(self, *, scene_id):
        return self.scene

    async def update_component(self, *, scene_id, component, fields, inc_attempts=False):
        state = getattr(self.scene, component)
        for key, value in fields.items():
            setattr(state, key, value)
        if inc_attempts:
            state.attempts += 1
        self.saved += 1

    async def update_fields(self, *, scene_id, fields):
        for key, value in fields.items():
            setattr(self.scene, key, value)


@pytest.fixture(autouse=True)
def patch_scene_save(monkeypatch):
    async def fake_save(self: Scene, *args, **kwargs) -> Scene:
        self.recompute_overall_status()
        self.updated_at = datetime.utcnow()
        return self

    monkeypatch.setattr(Scene, "save", fake_save)


@pytest.fixture
def fake_storage(monkeypatch) -> FakeStorage:
    storage = FakeStorage()
    monkeypatch.setattr(
        "vidx.services.generation.orchestrator.get_storage_provider", lambda: storage,
    )
    return storage


@pytest.mark.anyio
async def test_video_generation_requires_completed_image(monkeypatch) -> None:
    scene = make_scene()
    project = make_project(scene)
    with pytest.raises(GenerationError) as exc:
        await generation_orchestrator.submit_component(
            scene, project, GenerationComponent.VIDEO,
        )
    assert "image" in str(exc.value).lower()


@pytest.mark.anyio
async def test_image_submission_records_job_and_processing(monkeypatch) -> None:
    scene = make_scene()
    await scene.insert()
    project = make_project(scene)
    provider = FakeProvider()
    monkeypatch.setattr(
        "vidx.services.generation.orchestrator.provider_registry.get", lambda component: provider,
    )

    updated = await generation_orchestrator.submit_component(
        scene, project, GenerationComponent.IMAGE,
    )
    assert updated.image.status == ComponentStatus.PROCESSING
    assert updated.image.provider_job_id == "job-123"
    assert updated.image.correlation_id
    assert updated.image.attempts == 1


@pytest.mark.anyio
async def test_callback_stores_result_and_marks_completed(monkeypatch, fake_storage) -> None:
    scene = make_scene()
    scene.image.status = ComponentStatus.PROCESSING
    scene.image.provider = "fake"
    scene.image.provider_job_id = "job-123"
    scene.image.correlation_id = "corr-1"

    fake_dao = FakeSceneDAO(scene)
    monkeypatch.setattr("vidx.services.generation.orchestrator.SceneDAO", lambda: fake_dao)

    handled = await generation_orchestrator.handle_callback(
        ProviderCallback(
            provider="fake",
            job_id="job-123",
            correlation_id="corr-1",
            success=True,
            result_url="https://cdn.example.com/out.png",
            result_mime_type="image/png",
        ),
    )
    assert handled is True
    assert scene.image.status == ComponentStatus.COMPLETED
    assert scene.image.storage_ref == f"stored/{scene.id}_image.png"
    assert fake_storage.saved == [("https://cdn.example.com/out.png", f"{scene.id}_image.png")]


@pytest.mark.anyio
async def test_duplicate_callback_is_idempotent(monkeypatch, fake_storage) -> None:
    scene = make_scene()
    scene.image.status = ComponentStatus.PROCESSING
    scene.image.provider = "fake"
    scene.image.provider_job_id = "job-123"
    scene.image.correlation_id = "corr-1"

    fake_dao = FakeSceneDAO(scene)
    monkeypatch.setattr("vidx.services.generation.orchestrator.SceneDAO", lambda: fake_dao)

    callback = ProviderCallback(
        provider="fake",
        job_id="job-123",
        correlation_id="corr-1",
        success=True,
        result_url="https://cdn.example.com/out.png",
    )
    assert await generation_orchestrator.handle_callback(callback) is True
    assert await generation_orchestrator.handle_callback(callback) is True
    assert len(fake_storage.saved) == 1


@pytest.mark.anyio
async def test_correlation_mismatch_is_rejected(monkeypatch, fake_storage) -> None:
    scene = make_scene()
    scene.image.status = ComponentStatus.PROCESSING
    scene.image.provider = "fake"
    scene.image.provider_job_id = "job-123"
    scene.image.correlation_id = "corr-1"

    fake_dao = FakeSceneDAO(scene)
    monkeypatch.setattr("vidx.services.generation.orchestrator.SceneDAO", lambda: fake_dao)

    handled = await generation_orchestrator.handle_callback(
        ProviderCallback(
            provider="fake",
            job_id="job-123",
            correlation_id="WRONG",
            success=True,
            result_url="https://cdn.example.com/out.png",
        ),
    )
    assert handled is False
    assert scene.image.status == ComponentStatus.PROCESSING
    assert fake_storage.saved == []


@pytest.mark.anyio
async def test_unknown_job_is_not_handled(monkeypatch, fake_storage) -> None:
    scene = make_scene()
    fake_dao = FakeSceneDAO(scene)
    monkeypatch.setattr("vidx.services.generation.orchestrator.SceneDAO", lambda: fake_dao)
    handled = await generation_orchestrator.handle_callback(
        ProviderCallback(provider="fake", job_id="nope", correlation_id=None, success=True),
    )
    assert handled is False


@pytest.mark.anyio
async def test_failed_callback_records_error(monkeypatch, fake_storage) -> None:
    scene = make_scene()
    scene.video.status = ComponentStatus.PROCESSING
    scene.video.provider = "fake"
    scene.video.provider_job_id = "job-err"
    scene.video.correlation_id = "c-err"

    fake_dao = FakeSceneDAO(scene)
    monkeypatch.setattr("vidx.services.generation.orchestrator.SceneDAO", lambda: fake_dao)

    handled = await generation_orchestrator.handle_callback(
        ProviderCallback(
            provider="fake",
            job_id="job-err",
            correlation_id="c-err",
            success=False,
            error="provider exploded",
        ),
    )
    assert handled is True
    assert scene.video.status == ComponentStatus.FAILED
    assert scene.video.error == "provider exploded"
    assert scene.overall_status == "failed"
