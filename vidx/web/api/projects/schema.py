"""Schemas for project, post and scene APIs."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    project_type: str
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    platform: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    timezone: Optional[str] = None
    options: Dict[str, Any] = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    timezone: Optional[str] = None
    options: Optional[Dict[str, Any]] = None


class ComponentStateOut(BaseModel):
    status: str
    error: Optional[str] = None
    provider: Optional[str] = None
    provider_job_id: Optional[str] = None
    correlation_id: Optional[str] = None
    asset_url: Optional[str] = None
    attempts: int = 0
    submitted_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ProjectOut(BaseModel):
    id: str
    project_type: str
    name: str
    description: Optional[str] = None
    platform: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    timezone: Optional[str] = None
    status: str
    image_url: Optional[str] = None
    options: Dict[str, Any] = Field(default_factory=dict)
    final_video: ComponentStateOut
    created_at: datetime
    updated_at: datetime


class PostOut(BaseModel):
    id: str
    project_id: str
    platform: str
    content: str
    image_url: Optional[str] = None
    link: Optional[str] = None
    hashtags: List[str] = Field(default_factory=list)
    date: date
    time: str
    timezone: str
    scheduled_at_utc: datetime
    status: str
    error: Optional[str] = None
    provider_post_id: Optional[str] = None
    published_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class CalendarDay(BaseModel):
    date: date
    count: int


class CalendarOut(BaseModel):
    project: ProjectOut
    days: List[CalendarDay]
    posts: List[PostOut]


class PlatformOut(BaseModel):
    platform: str
    label: str
    availability: str
    max_content_length: int
    max_hashtags: Optional[int] = None
    supports_images: bool
    supports_links: bool
    supports_scheduling: bool
    notes: str = ""


class SceneOut(BaseModel):
    id: str
    project_id: str
    scene_number: int
    image_prompt: str
    scene_prompt: str
    audio_prompt: str
    image: ComponentStateOut
    video: ComponentStateOut
    audio: ComponentStateOut
    subtitle: ComponentStateOut
    render: ComponentStateOut
    overall_status: str
    source: str
    created_at: datetime
    updated_at: datetime


class SceneUpdate(BaseModel):
    image_prompt: Optional[str] = None
    scene_prompt: Optional[str] = None
    audio_prompt: Optional[str] = None


class GenerateRequest(BaseModel):
    component: str
    force: bool = False


class GenerateAllRequest(BaseModel):
    components: List[str] = Field(
        default_factory=lambda: ["image", "video", "audio", "subtitle"],
    )
    force: bool = False


class ImportScenesResult(BaseModel):
    imported: int
    mode: str
    errors: List[str] = Field(default_factory=list)
