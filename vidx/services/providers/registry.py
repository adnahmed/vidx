"""Provider registry: resolves the configured generation provider per component."""

from __future__ import annotations

import json
import logging
from typing import Dict, Optional

from vidx.services.providers.base import AIProvider, GenerationComponent
from vidx.services.providers.http_provider import HTTPAIProvider
from vidx.services.providers.simulated import SimulatedProvider
from vidx.settings import settings

logger = logging.getLogger(__name__)


def _extra_params() -> Dict:
    raw = settings.ai_extra_params
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        logger.warning("VIDX_AI_EXTRA_PARAMS is not valid JSON; ignoring")
        return {}


class ProviderRegistry:
    """Builds one provider adapter per generation component from settings."""

    def __init__(self) -> None:
        self._by_component: Dict[GenerationComponent, AIProvider] = {}
        self._by_name: Dict[str, AIProvider] = {}
        self._build()

    def _build(self) -> None:
        mode = (settings.ai_provider_mode or "simulated").lower()
        for component in GenerationComponent:
            if mode == "http":
                provider = HTTPAIProvider(
                    component=component,
                    endpoint=getattr(settings, f"ai_{component.value}_endpoint"),
                    api_key=getattr(settings, f"ai_{component.value}_api_key"),
                    model=getattr(settings, f"ai_{component.value}_model"),
                    extra_params=_extra_params(),
                    name=getattr(settings, f"ai_{component.value}_provider") or "default",
                )
            else:
                provider = SimulatedProvider(component, name="simulated")
            self._by_component[component] = provider
            self._by_name.setdefault(provider.name, provider)

    def get(self, component: GenerationComponent) -> AIProvider:
        return self._by_component[component]

    def get_by_name(self, name: str) -> Optional[AIProvider]:
        return self._by_name.get(name)


provider_registry = ProviderRegistry()
