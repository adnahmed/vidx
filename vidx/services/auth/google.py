
from __future__ import annotations

import asyncio
from typing import Any, Dict

import httpx
from fastapi import HTTPException, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from vidx.settings import settings


def ensure_google_configured() -> None:
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth is not configured.",
        )


async def exchange_code_for_tokens(code: str) -> Dict[str, Any]:
    ensure_google_configured()
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            settings.google_token_uri,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
    if response.status_code != status.HTTP_200_OK:
        try:
            detail = response.json()
        except ValueError:
            detail = response.text
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Failed to exchange authorization code", "response": detail},
        )
    return response.json()


async def verify_id_token(token: str) -> Dict[str, Any]:
    ensure_google_configured()
    google_request = google_requests.Request()
    try:
        return await asyncio.to_thread(
            google_id_token.verify_oauth2_token,
            token,
            google_request,
            settings.google_client_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Google token.") from exc


async def revoke_google_token(token: str) -> None:
    ensure_google_configured()
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            settings.google_revoke_uri,
            data={"token": token},
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
    if response.status_code not in {status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST}:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to revoke Google token.")

