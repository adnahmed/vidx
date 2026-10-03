"""AI generation provider abstraction.

The application never performs model inference itself. Every image, video,
audio or subtitle generation is submitted to an external provider endpoint
behind this interface using the contract:

    Input -> Submit Job -> Provider Job ID -> Processing
          -> Webhook Callback -> Store Result -> Continue Pipeline

Providers, endpoints, credentials, models, parameters and webhook settings are
supplied externally through application settings.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class GenerationComponent(str, enum.Enum):
    """Generation component kinds supported by the pipeline."""

    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"


@dataclass
class GenerationRequest:
    """Provider-agnostic job submission payload."""

    component: GenerationComponent
    provider_job_ref: str
    correlation_id: str
    prompt: str
    webhook_url: str
    scene_id: str
    project_id: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    source_image_url: Optional[str] = None
    source_audio_url: Optional[str] = None
    source_video_url: Optional[str] = None


@dataclass
class ProviderJob:
    """Handle returned by a provider after a successful submission."""

    provider: str
    job_id: str
    correlation_id: str
    status: str = "processing"


@dataclass
class ProviderCallback:
    """Normalized webhook callback from a provider."""

    provider: str
    job_id: str
    correlation_id: Optional[str]
    success: bool
    result_url: Optional[str] = None
    result_mime_type: Optional[str] = None
    error: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


class AIProvider(ABC):
    """Interface every external generation provider adapter implements."""

    name: str
    component: GenerationComponent

    @abstractmethod
    async def submit_job(self, request: GenerationRequest) -> ProviderJob:
        """Submit a job to the external provider and return its job handle."""
        raise NotImplementedError

    @abstractmethod
    def parse_webhook(self, payload: Dict[str, Any]) -> Optional[ProviderCallback]:
        """
        Parse a provider webhook payload.

        Returns ``None`` when the payload does not belong to this provider or
        is malformed; callers treat that as an invalid callback.
        """
        raise NotImplementedError
