"""Provider webhook receiver: verify, correlate and continue the pipeline."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request
from starlette import status

from vidx.services.generation import generation_orchestrator
from vidx.services.providers import provider_registry
from vidx.services.providers.webhooks import SIGNATURE_HEADER, verify_signature

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{provider_name}")
async def provider_webhook(provider_name: str, request: Request) -> dict:
    """
    Receive an asynchronous generation callback.

    Security: every callback must carry a valid HMAC signature over the raw
    body. Correlation: the payload's provider job id is matched against the
    scene component that submitted the job; mismatches are rejected.
    """
    body = await request.body()
    signature = request.headers.get(SIGNATURE_HEADER)
    if not verify_signature(body, signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature.",
        )

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed webhook payload.",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed webhook payload.",
        )

    provider_name = provider_name or str(payload.get("provider") or "")
    provider = provider_registry.get_by_name(provider_name)
    if provider is None:
        provider_name = str(payload.get("provider") or "")
        provider = provider_registry.get_by_name(provider_name)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown provider '{provider_name}'.",
        )

    callback = provider.parse_webhook(payload)
    if callback is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook payload could not be parsed for this provider.",
        )

    handled = await generation_orchestrator.handle_callback(callback)
    if not handled:
        # Valid signature but no matching job: acknowledge to avoid provider
        # retries while surfacing the mismatch in logs.
        logger.warning(
            "Webhook for provider %s job %s did not match any internal job",
            callback.provider,
            callback.job_id,
        )
    return {"status": "accepted" if handled else "unmatched"}
