"""Video production scene model: source prompts plus generated asset references."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Annotated, Any, ClassVar

from beanie import Document, Indexed, PydanticObjectId
from pydantic import Field

from vidx.db.models.project import ComponentState


class SceneSource(str, enum.Enum):
    """How the scene row entered the database."""

    EXCEL_IMPORT = "excel_import"
    MANUAL = "manual"


class Scene(Document):
    """
    One scene of a Video Production project.

    Source prompts are editable. Generated artifacts are referenced per
    component (image, video, audio, subtitle, final scene render); each
    component independently tracks provider job ids, correlation ids, status,
    error and timestamps so components can be regenerated without touching
    the rest of the scene.
    """

    project_id: Annotated[PydanticObjectId, Indexed()]
    scene_number: int
    image_prompt: str = ""
    scene_prompt: str = ""
    audio_prompt: str = ""

    image: ComponentState = Field(default_factory=ComponentState)
    video: ComponentState = Field(default_factory=ComponentState)
    audio: ComponentState = Field(default_factory=ComponentState)
    subtitle: ComponentState = Field(default_factory=ComponentState)
    render: ComponentState = Field(default_factory=ComponentState)

    overall_status: str = "draft"
    source: SceneSource = SceneSource.EXCEL_IMPORT
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "scenes"
        indexes: ClassVar[list[str]] = ["project_id", "scene_number"]

    def recompute_overall_status(self) -> str:
        """Derive the scene status from the component statuses."""
        if self.render.status.value == "completed":
            self.overall_status = "completed"
        elif any(
            component.status.value == "failed"
            for component in (self.image, self.video, self.audio, self.subtitle, self.render)
        ):
            self.overall_status = "failed"
        elif self.render.status.value == "processing" or self.video.status.value == "processing":
            self.overall_status = "processing"
        elif self.video.status.value == "completed":
            self.overall_status = "video_ready"
        elif self.image.status.value == "completed":
            self.overall_status = "image_ready"
        elif any(
            component.status.value in {"queued", "processing"}
            for component in (self.image, self.video, self.audio, self.subtitle)
        ):
            self.overall_status = "processing"
        else:
            self.overall_status = "draft"
        return self.overall_status

    async def save(self, *args: Any, **kwargs: Any) -> "Scene":
        self.recompute_overall_status()
        self.updated_at = datetime.utcnow()
        return await super().save(*args, **kwargs)
