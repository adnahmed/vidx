"""Tests for provider webhook signing, parsing and correlation semantics."""

from __future__ import annotations

from vidx.services.providers.base import GenerationComponent
from vidx.services.providers.http_provider import HTTPAIProvider
from vidx.services.providers.simulated import SimulatedProvider
from vidx.services.providers.webhooks import sign_payload, verify_signature


def test_signature_roundtrip() -> None:
    body = b'{"hello":"world"}'
    signature = sign_payload(body)
    assert signature.startswith("sha256=")
    assert verify_signature(body, signature)
    assert not verify_signature(body + b"x", signature)
    assert not verify_signature(body, None)
    assert not verify_signature(body, "sha256=deadbeef")


def test_http_provider_ignores_non_terminal_updates() -> None:
    provider = HTTPAIProvider(
        component=GenerationComponent.IMAGE, endpoint="http://x", api_key=None, model="m",
    )
    assert provider.parse_webhook({"job_id": "1", "status": "processing"}) is None


def test_http_provider_parses_success() -> None:
    provider = HTTPAIProvider(
        component=GenerationComponent.IMAGE, endpoint="http://x", api_key=None, model="m",
    )
    callback = provider.parse_webhook(
        {
            "job_id": "job-9",
            "status": "completed",
            "correlation_id": "corr-1",
            "result": {"url": "https://cdn.example.com/out.png", "mime_type": "image/png"},
        },
    )
    assert callback is not None
    assert callback.success
    assert callback.result_url == "https://cdn.example.com/out.png"
    assert callback.correlation_id == "corr-1"


def test_http_provider_parses_failure() -> None:
    provider = HTTPAIProvider(
        component=GenerationComponent.VIDEO, endpoint="http://x", api_key=None, model="m",
    )
    callback = provider.parse_webhook(
        {"job_id": "job-1", "status": "failed", "error": "boom"},
    )
    assert callback is not None
    assert not callback.success
    assert callback.error == "boom"


def test_http_provider_rejects_foreign_provider_payload() -> None:
    provider = HTTPAIProvider(
        component=GenerationComponent.IMAGE, endpoint="http://x", api_key=None, model="m",
    )
    assert provider.parse_webhook({"provider": "other", "job_id": "1", "status": "completed"}) is None


def test_simulated_provider_parses_own_payload() -> None:
    provider = SimulatedProvider(GenerationComponent.AUDIO)
    callback = provider.parse_webhook(
        {
            "provider": "simulated",
            "data": {
                "job_id": "sim-audio-1",
                "status": "completed",
                "correlation_id": "c1",
                "result": {"url": "file:///tmp/a.mp3", "mime_type": "audio/mpeg"},
            },
        },
    )
    assert callback is not None
    assert callback.success
    assert callback.job_id == "sim-audio-1"
    assert callback.result_url == "file:///tmp/a.mp3"
