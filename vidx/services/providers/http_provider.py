"""Generic HTTP AI provider adapter for externally configured APIs."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

from vidx.services.providers.base import (
    AIProvider,
    GenerationComponent,
    GenerationRequest,
    ProviderCallback,
    ProviderJob,
)
from vidx.settings import settings

logger = logging.getLogger(__name__)


class HTTPAIProvider(AIProvider):
    """
    Submits generation jobs to a configured external HTTP endpoint.

    Configuration is entirely external (environment-driven):
      endpoint, api_key, model, extra parameters. The provider is expected to
      accept a JSON submit payload containing the prompt, parameters,
      correlation id and a webhook URL, to return a job id, and to call the
      webhook back when processing completes.
    """

    def __init__(
        self,
        *,
        component: GenerationComponent,
        endpoint: Optional[str],
        api_key: Optional[str],
        model: Optional[str],
        extra_params: Optional[Dict[str, Any]] = None,
        name: str = "default",
    ) -> None:
        self.name = name
        self.component = component
        self._endpoint = endpoint
        self._api_key = api_key
        self._model = model
        self._extra_params = extra_params or {}

    def is_configured(self) -> bool:
        return bool(self._endpoint)

    async def submit_job(self, request: GenerationRequest) -> ProviderJob:
        if not self._endpoint:
            raise RuntimeError(
                f"No endpoint configured for {self.component.value} provider "
                f"'{self.name}'. Set the corresponding VIDX_AI_*_ENDPOINT value.",
            )

        payload: Dict[str, Any] = {
            "component": request.component.value,
            "model": self._model,
            "prompt": request.prompt,
            "parameters": {**self._extra_params, **request.parameters},
            "webhook_url": request.webhook_url,
            "correlation_id": request.correlation_id,
            "metadata": {
                "scene_id": request.scene_id,
                "project_id": request.project_id,
            },
        }
        if request.source_image_url:
            payload["image_url"] = request.source_image_url
        if request.source_audio_url:
            payload["audio_url"] = request.source_audio_url
        if request.source_video_url:
            payload["video_url"] = request.source_video_url

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        async with httpx.AsyncClient(
            timeout=float(settings.provider_submit_timeout_seconds),
        ) as client:
            response = await client.post(self._endpoint, headers=headers, json=payload)
        if response.status_code not in (200, 201, 202):
            detail = response.text[:500]
            raise RuntimeError(
                f"Provider submit failed ({response.status_code}): {detail}",
            )
        data = response.json() if response.content else {}
        job_id = (
            data.get("job_id")
            or data.get("jobId")
            or data.get("id")
            or (data.get("data") or {}).get("job_id")
            or (data.get("data") or {}).get("id")
        )
        if not job_id:
            raise RuntimeError("Provider submit response did not contain a job id")
        return ProviderJob(
            provider=self.name,
            job_id=str(job_id),
            correlation_id=request.correlation_id,
            status=str(data.get("status") or "processing"),
        )

    def parse_webhook(self, payload: Dict[str, Any]) -> Optional[ProviderCallback]:
        if payload.get("provider") not in (None, self.name):
            return None
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        job_id = (
            data.get("job_id")
            or data.get("jobId")
            or data.get("id")
            or payload.get("job_id")
        )
        if not job_id:
            return None
        status = str(
            data.get("status") or data.get("state") or payload.get("status") or "",
        ).lower()
        success = status in {"completed", "succeeded", "success", "done", "finished"}
        failure = status in {"failed", "error", "canceled", "cancelled"}
        if not success and not failure:
            # Non-terminal update (e.g. "processing"): nothing to store yet.
            return None
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        result_url = (
            data.get("result_url")
            or data.get("output_url")
            or data.get("url")
            or result.get("url")
            or payload.get("result_url")
        )
        error = data.get("error") or payload.get("error")
        return ProviderCallback(
            provider=self.name,
            job_id=str(job_id),
            correlation_id=data.get("correlation_id") or payload.get("correlation_id"),
            success=success,
            result_url=result_url,
            result_mime_type=data.get("mime_type") or result.get("mime_type"),
            error=None if success else (str(error) if error else "Provider job failed"),
            raw=payload,
        )
