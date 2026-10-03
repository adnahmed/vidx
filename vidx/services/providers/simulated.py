"""Simulated provider transport used for offline/dev verification.

This is NOT model inference and NOT an image/video generator: it is a
transport stand-in that speaks the exact external-provider contract
(submit → job id → asynchronous webhook callback → result URL) so the whole
pipeline can be exercised without external API credentials. Artifacts are
produced by the local FFmpeg binary (color frame / test video / tone / SRT).
Production deployments configure ``VIDX_AI_PROVIDER_MODE=http`` and real
external endpoints.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from vidx.services.providers.base import (
    AIProvider,
    GenerationComponent,
    GenerationRequest,
    ProviderCallback,
    ProviderJob,
)
from vidx.services.providers.webhooks import sign_payload
from vidx.settings import settings

logger = logging.getLogger(__name__)


def _prompt_color(prompt: str) -> str:
    digest = hashlib.sha256((prompt or "").encode("utf-8")).hexdigest()
    return f"0x{digest[:6]}"


def _prompt_hash(prompt: str) -> int:
    return int(hashlib.sha256((prompt or "").encode("utf-8")).hexdigest()[:8], 16)


class SimulatedProvider(AIProvider):
    """Provider transport stand-in: no model inference, real async webhooks."""

    # Bounds concurrent in-process FFmpeg artifact production so a burst of
    # submissions cannot exhaust memory on small instances.
    _artifact_semaphore = threading.BoundedSemaphore(
        max(1, settings.simulated_provider_max_concurrency),
    )

    def __init__(self, component: GenerationComponent, name: str = "simulated") -> None:
        self.name = name
        self.component = component
        self._base_dir = Path(settings.local_storage_dir) / "simulated-provider"
        self._base_dir.mkdir(parents=True, exist_ok=True)

    # ── submission ───────────────────────────────────────────────────────────
    async def submit_job(self, request: GenerationRequest) -> ProviderJob:
        job_id = f"sim-{self.component.value}-{uuid.uuid4().hex[:16]}"
        thread = threading.Thread(
            target=self._deliver_callback,
            args=(request, job_id),
            daemon=True,
        )
        thread.start()
        return ProviderJob(
            provider=self.name, job_id=job_id, correlation_id=request.correlation_id,
        )

    def _deliver_callback(self, request: GenerationRequest, job_id: str) -> None:
        # Simulate provider processing time, then produce and deliver the result.
        time.sleep(max(0.0, settings.simulated_provider_delay_seconds))
        artifact = self._produce_artifact(request, job_id)
        payload = {
            "provider": self.name,
            "event": "job.completed",
            "data": {
                "job_id": job_id,
                "correlation_id": request.correlation_id,
                "status": "completed" if artifact else "failed",
                "component": self.component.value,
                "result": {
                    "url": artifact.as_uri() if artifact else None,
                    "mime_type": self._mime_type() if artifact else None,
                },
                "error": None if artifact else "Simulated artifact production failed",
            },
        }
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-Provider-Signature": sign_payload(body),
            "X-Provider-Name": self.name,
        }
        for attempt in range(3):
            try:
                response = httpx.post(request.webhook_url, content=body, headers=headers, timeout=30.0)
                if response.status_code < 500:
                    logger.info(
                        "Simulated webhook delivered for %s (status %s)",
                        job_id,
                        response.status_code,
                    )
                    return
            except Exception as exc:  # pragma: no cover - retry path
                logger.warning("Simulated webhook attempt %s failed: %s", attempt + 1, exc)
            time.sleep(1.5)

    def _mime_type(self) -> str:
        return {
            GenerationComponent.IMAGE: "image/png",
            GenerationComponent.VIDEO: "video/mp4",
            GenerationComponent.AUDIO: "audio/mpeg",
            GenerationComponent.SUBTITLE: "application/x-subrip",
        }[self.component]

    # ── artifact production (FFmpeg only, no inference) ──────────────────────
    def _produce_artifact(self, request: GenerationRequest, job_id: str) -> Optional[Path]:
        with self._artifact_semaphore:
            try:
                if self.component == GenerationComponent.IMAGE:
                    return self._make_image(request.prompt, job_id)
                if self.component == GenerationComponent.VIDEO:
                    return self._make_video(request.prompt, job_id)
                if self.component == GenerationComponent.AUDIO:
                    return self._make_audio(request.prompt, job_id)
                if self.component == GenerationComponent.SUBTITLE:
                    return self._make_subtitle(request.prompt, job_id)
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Simulated artifact production failed: %s", exc)
            return None

    def _run_ffmpeg(self, args: list[str]) -> None:
        result = subprocess.run(
            [settings.ffmpeg, "-y", *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg failed ({result.returncode}): {result.stderr[-500:]}",
            )

    def _make_image(self, prompt: str, job_id: str) -> Path:
        target = self._base_dir / f"{job_id}.png"
        color = _prompt_color(prompt)
        self._run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s=1280x720",
                "-frames:v",
                "1",
                str(target),
            ],
        )
        return target

    def _make_video(self, prompt: str, job_id: str) -> Path:
        target = self._base_dir / f"{job_id}.mp4"
        duration = 3 + (_prompt_hash(prompt) % 3)
        self._run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                f"testsrc2=size=1280x720:rate=24:duration={duration}",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={220 + (_prompt_hash(prompt) % 440)}:duration={duration}",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-pix_fmt",
                "yuv420p",
                "-threads",
                "1",
                "-x264-params",
                "threads=1:lookahead_threads=1",
                "-c:a",
                "aac",
                "-shortest",
                str(target),
            ]
        )
        return target

    def _make_audio(self, prompt: str, job_id: str) -> Path:
        target = self._base_dir / f"{job_id}.mp3"
        duration = 3 + (_prompt_hash(prompt) % 3)
        self._run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={220 + (_prompt_hash(prompt) % 660)}:duration={duration}",
                "-c:a",
                "libmp3lame",
                "-q:a",
                "6",
                str(target),
            ],
        )
        return target

    def _make_subtitle(self, prompt: str, job_id: str) -> Path:
        target = self._base_dir / f"{job_id}.srt"
        words = (prompt or "Scene").split()
        chunks = [" ".join(words[i : i + 6]) for i in range(0, len(words), 6)] or ["Scene"]
        lines = []
        start = 0.0
        for index, chunk in enumerate(chunks, start=1):
            end = start + 2.0

            def _stamp(value: float) -> str:
                hours = int(value // 3600)
                minutes = int((value % 3600) // 60)
                seconds = int(value % 60)
                millis = int((value - int(value)) * 1000)
                return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

            lines.append(f"{index}")
            lines.append(f"{_stamp(start)} --> {_stamp(end)}")
            lines.append(chunk)
            lines.append("")
            start = end
        target.write_text("\n".join(lines), encoding="utf-8")
        return target

    # ── webhook parsing ──────────────────────────────────────────────────────
    def parse_webhook(self, payload: Dict[str, Any]) -> Optional[ProviderCallback]:
        if payload.get("provider") not in (None, self.name):
            return None
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        job_id = data.get("job_id") or payload.get("job_id")
        if not job_id:
            return None
        status = str(data.get("status") or "").lower()
        success = status in {"completed", "succeeded", "success"}
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        return ProviderCallback(
            provider=self.name,
            job_id=str(job_id),
            correlation_id=data.get("correlation_id") or payload.get("correlation_id"),
            success=success,
            result_url=result.get("url"),
            result_mime_type=result.get("mime_type"),
            error=None if success else str(data.get("error") or "Job failed"),
            raw=payload,
        )
