"""Generation orchestrator: submit → job id → webhook → store → continue."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple

from vidx.db.dao.project_dao import SceneDAO
from vidx.db.models.project import ComponentState, ComponentStatus, Project
from vidx.db.models.scene import Scene
from vidx.services.providers import (
    GenerationComponent,
    GenerationRequest,
    ProviderCallback,
    provider_registry,
)
from vidx.services.storage.factory import get_storage_provider
from vidx.settings import settings

logger = logging.getLogger(__name__)

COMPONENTS = (
    GenerationComponent.IMAGE,
    GenerationComponent.VIDEO,
    GenerationComponent.AUDIO,
    GenerationComponent.SUBTITLE,
)

_EXTENSIONS = {
    GenerationComponent.IMAGE: ".png",
    GenerationComponent.VIDEO: ".mp4",
    GenerationComponent.AUDIO: ".mp3",
    GenerationComponent.SUBTITLE: ".srt",
}


class GenerationError(RuntimeError):
    """Raised when a generation request violates pipeline preconditions."""


class GenerationOrchestrator:
    """Owns submission preconditions, correlation and callback continuation."""

    def webhook_url(self, provider: str) -> str:
        base = (settings.public_base_url or "").rstrip("/")
        return f"{base}/api/webhooks/{provider}"

    def _get_component_state(
        self, scene: Scene, component: GenerationComponent,
    ) -> ComponentState:
        return getattr(scene, component.value)

    def _precondition_error(
        self, scene: Scene, project: Project, component: GenerationComponent,
    ) -> Optional[str]:
        state = self._get_component_state(scene, component)
        if component == GenerationComponent.VIDEO:
            if scene.image.status != ComponentStatus.COMPLETED:
                return "Generated image must be completed before video generation."
            if not (scene.scene_prompt or "").strip():
                return "Scene has no scene prompt."
        else:
            prompt_by_component = {
                GenerationComponent.IMAGE: (
                    scene.image_prompt,
                    "Scene has no image prompt.",
                ),
                GenerationComponent.AUDIO: (
                    scene.audio_prompt,
                    "Scene has no audio prompt.",
                ),
                GenerationComponent.SUBTITLE: (
                    scene.scene_prompt or scene.audio_prompt,
                    "Scene has no prompt text to derive subtitles from.",
                ),
            }
            prompt, message = prompt_by_component[component]
            if not (prompt or "").strip():
                return message
        if state.status in (ComponentStatus.QUEUED, ComponentStatus.PROCESSING):
            return f"{component.value} generation is already in progress."
        return None

    def _build_request(
        self,
        scene: Scene,
        project: Project,
        component: GenerationComponent,
        provider_name: str,
    ) -> GenerationRequest:
        prompt_map = {
            GenerationComponent.IMAGE: scene.image_prompt,
            GenerationComponent.VIDEO: scene.scene_prompt,
            GenerationComponent.AUDIO: scene.audio_prompt,
            GenerationComponent.SUBTITLE: scene.audio_prompt or scene.scene_prompt,
        }
        correlation_id = uuid.uuid4().hex
        return GenerationRequest(
            component=component,
            provider_job_ref=f"{scene.id}:{component.value}",
            correlation_id=correlation_id,
            prompt=prompt_map[component] or "",
            webhook_url=self.webhook_url(provider_name),
            scene_id=str(scene.id),
            project_id=str(project.id),
            parameters=dict(project.options or {}),
        )

    async def submit_component(
        self,
        scene: Scene,
        project: Project,
        component: GenerationComponent,
        *,
        force: bool = False,
    ) -> Scene:
        """
        Submit one component to the configured provider.

        ``force`` allows explicit regeneration of an already-completed
        component without touching any other component of the scene.
        """
        state = self._get_component_state(scene, component)

        if not force:
            error = self._precondition_error(scene, project, component)
            if error:
                raise GenerationError(error)

        provider = provider_registry.get(component)

        # Resolve upstream artifacts that the provider needs.
        if component == GenerationComponent.VIDEO:
            if scene.image.status != ComponentStatus.COMPLETED or not scene.image.storage_ref:
                raise GenerationError(
                    "Generated image must be completed before video generation.",
                )
            request = self._build_request(scene, project, component, provider.name)
            request.source_image_url = await self._materialized_url(
                scene.image.storage_ref,
            )
        elif component == GenerationComponent.SUBTITLE and scene.audio.storage_ref:
            request = self._build_request(scene, project, component, provider.name)
            request.source_audio_url = await self._materialized_url(
                scene.audio.storage_ref,
            )
        else:
            request = self._build_request(scene, project, component, provider.name)

        state.status = ComponentStatus.QUEUED
        state.error = None
        state.attempts += 1
        state.correlation_id = request.correlation_id
        state.submitted_at = datetime.utcnow()
        state.updated_at = datetime.utcnow()
        await self._persist_component(
            scene.id,
            component,
            {
                "status": state.status,
                "error": None,
                "correlation_id": state.correlation_id,
                "submitted_at": state.submitted_at,
                "updated_at": state.updated_at,
            },
            inc_attempts=True,
        )

        try:
            job = await provider.submit_job(request)
        except Exception as exc:
            await self._persist_component(
                scene.id,
                component,
                {
                    "status": ComponentStatus.FAILED,
                    "error": str(exc),
                    "updated_at": datetime.utcnow(),
                },
            )
            return await self._refresh_scene(scene.id)

        await self._persist_component(
            scene.id,
            component,
            {
                "status": ComponentStatus.PROCESSING,
                "provider": job.provider,
                "provider_job_id": job.job_id,
                "updated_at": datetime.utcnow(),
            },
        )
        return await self._refresh_scene(scene.id) or scene

    async def _persist_component(
        self,
        scene_id: Any,
        component: GenerationComponent,
        fields: dict,
        *,
        inc_attempts: bool = False,
    ) -> None:
        """Atomically persist component fields (never a full-document save)."""
        await SceneDAO().update_component(
            scene_id=scene_id,
            component=component.value,
            fields=fields,
            inc_attempts=inc_attempts,
        )

    async def _refresh_scene(self, scene_id: Any) -> Optional[Scene]:
        """Reload a scene and persist its derived overall status atomically."""
        scene = await SceneDAO().get(scene_id=scene_id)
        if scene is None:
            return None
        scene.recompute_overall_status()
        await SceneDAO().update_fields(
            scene_id=scene_id,
            fields={"overall_status": scene.overall_status},
        )
        return scene

    async def _materialized_url(self, storage_ref: str) -> str:
        """Return a URL an external provider can fetch for an input artifact."""
        provider = get_storage_provider()
        url = await provider.generate_download_url(storage_ref)
        if url.startswith(("http://", "https://")):
            return url
        # Local storage: expose the generated file through the public media
        # route so external providers can download it without credentials.
        base = (settings.public_base_url or "").rstrip("/")
        return f"{base}/api/media/generated/{Path(url).name}"

    # ── callback continuation ────────────────────────────────────────────────
    async def _find_scene_component(
        self, callback: ProviderCallback,
    ) -> Tuple[Optional[Scene], Optional[GenerationComponent]]:
        dao = SceneDAO()
        for component in COMPONENTS:
            scene = await dao.find_by_provider_job(
                provider=callback.provider,
                provider_job_id=callback.job_id,
                component=component.value,
            )
            if scene is not None:
                return scene, component
        return None, None

    async def handle_callback(self, callback: ProviderCallback) -> bool:
        """
        Correlate a provider callback to a scene component and persist the result.

        Returns True when the callback matched a known job. Duplicate callbacks
        for an already-completed component are acknowledged and ignored.
        """
        scene, component = await self._find_scene_component(callback)
        if scene is None or component is None:
            logger.warning(
                "Unmatched provider callback: provider=%s job=%s",
                callback.provider,
                callback.job_id,
            )
            return False

        state = self._get_component_state(scene, component)

        if (
            state.correlation_id
            and callback.correlation_id
            and state.correlation_id != callback.correlation_id
        ):
            logger.warning(
                "Correlation mismatch for scene %s %s: expected %s got %s",
                scene.id,
                component.value,
                state.correlation_id,
                callback.correlation_id,
            )
            return False

        if state.provider_job_id != callback.job_id:
            logger.warning(
                "Stale provider job id for scene %s %s", scene.id, component.value,
            )
            return False

        if state.status == ComponentStatus.COMPLETED:
            # Idempotent duplicate callback.
            return True

        fields: dict = {"updated_at": datetime.utcnow()}
        if callback.success and callback.result_url:
            try:
                storage = get_storage_provider()
                filename = f"{scene.id}_{component.value}{_EXTENSIONS[component]}"
                storage_ref = await storage.save_from_url(callback.result_url, filename)
                fields.update(
                    {
                        "storage_ref": storage_ref,
                        "source_url": callback.result_url,
                        "mime_type": callback.result_mime_type,
                        "status": ComponentStatus.COMPLETED,
                        "error": None,
                        "completed_at": datetime.utcnow(),
                    },
                )
            except Exception as exc:
                logger.exception("Failed to persist provider result")
                fields.update(
                    {
                        "status": ComponentStatus.FAILED,
                        "error": f"Failed to store generated result: {exc}",
                    },
                )
        else:
            fields.update(
                {
                    "status": ComponentStatus.FAILED,
                    "error": callback.error or "Provider job failed.",
                },
            )

        await self._persist_component(scene.id, component, fields)
        await self._refresh_scene(scene.id)
        return True


generation_orchestrator = GenerationOrchestrator()
