
from __future__ import annotations

from datetime import datetime
from typing import Annotated, List

from beanie import Document, Indexed, PydanticObjectId
from pydantic import Field


class MergeHistory(Document):
    """Stores metadata about a user's video merge task."""

    user_id: Annotated[PydanticObjectId, Indexed()]
    task_id: str
    videos: List[str]
    audio: str | None = None
    transition: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "merge_history"
        indexes = ["-created_at"]

