"""Webhook signing and verification helpers."""

from __future__ import annotations

import hashlib
import hmac

from vidx.settings import settings

SIGNATURE_HEADER = "X-Provider-Signature"


def sign_payload(body: bytes) -> str:
    """Return the canonical HMAC-SHA256 signature for a webhook body."""
    digest = hmac.new(
        settings.provider_webhook_secret.encode("utf-8"), body, hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def verify_signature(body: bytes, signature: str | None) -> bool:
    """Constant-time verification of a provider webhook signature."""
    if not signature:
        return False
    expected = sign_payload(body)
    return hmac.compare_digest(expected, signature.strip())
