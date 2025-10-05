from __future__ import annotations

import secrets
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import RedirectResponse

from vidx.settings import settings
from vidx.db.dao.user_dao import UserDAO
from vidx.services.auth.google import (
    ensure_google_configured,
    exchange_code_for_tokens,
    revoke_google_token,
    verify_id_token,
)
from vidx.services.auth.security import (
    create_access_token,
    create_state_token,
    decode_access_token,
    decode_state_token,
    hash_password,
    verify_password,
)
from vidx.web.api.auth.schema import (
    GoogleAuthResponse,
    LoginRequest,
    LogoutResponse,
    RegisterRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


async def get_user_dao() -> UserDAO:
    return UserDAO()


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    payload: RegisterRequest,
    user_dao: UserDAO = Depends(get_user_dao),
) -> TokenResponse:
    existing = await user_dao.get_by_email(payload.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered.",
        )
    hashed_password = hash_password(payload.password)
    user = await user_dao.create_user(
        email=payload.email,
        hashed_password=hashed_password,
        full_name=payload.full_name,
        providers=["local"],
    )
    token = create_access_token({
        "sub": str(user.id),
        "email": user.email,
        "provider": "local",
    })
    return TokenResponse(access_token=token, provider="local")


@router.post("/login", response_model=TokenResponse)
async def login_user(
    payload: LoginRequest,
    user_dao: UserDAO = Depends(get_user_dao),
) -> TokenResponse:
    user = await user_dao.get_by_email(payload.email)
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials.",
        )
    await user_dao.touch_login(user)
    token = create_access_token({
        "sub": str(user.id),
        "email": user.email,
        "provider": "local",
    })
    return TokenResponse(access_token=token, provider="local")


@router.get("/google/login")
async def google_login() -> RedirectResponse:
    ensure_google_configured()
    state = create_state_token({"nonce": secrets.token_urlsafe(16)})
    params = {
        "client_id": settings.google_client_id,
        "response_type": "code",
        "redirect_uri": settings.google_redirect_uri,
        "scope": " ".join(settings.google_scope),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    url = f"{settings.google_authorize_uri}?{urlencode(params)}"
    return RedirectResponse(url=url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/google/callback", response_model=GoogleAuthResponse)
async def google_callback(
    code: str,
    state: str,
    user_dao: UserDAO = Depends(get_user_dao),
) -> GoogleAuthResponse:
    ensure_google_configured()
    state_payload = decode_state_token(state)
    if not state_payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state.")

    token_payload = await exchange_code_for_tokens(code)
    if "id_token" not in token_payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing id_token from Google response.")

    access_token = token_payload.get("access_token")
    if not access_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing access token from Google response.")

    id_info = await verify_id_token(str(token_payload["id_token"]))
    google_sub = id_info.get("sub")
    email = id_info.get("email")
    full_name = id_info.get("name")

    if not google_sub or not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google did not return expected profile data.")

    user = await user_dao.get_by_google_sub(google_sub)
    if not user:
        user = await user_dao.get_by_email(email)
    if user:
        if not user.full_name and full_name:
            user.full_name = full_name
        await user_dao.update_google_tokens(
            user,
            access_token=str(access_token),
            refresh_token=token_payload.get("refresh_token"),
            google_sub=google_sub,
        )
    else:
        user = await user_dao.create_user(
            email=email,
            full_name=full_name,
            providers=["google"],
            google_sub=google_sub,
            google_access_token=str(access_token),
            google_refresh_token=token_payload.get("refresh_token"),
        )

    jwt_token = create_access_token({
        "sub": str(user.id),
        "email": user.email,
        "provider": "google",
    })

    return GoogleAuthResponse(
        access_token=jwt_token,
        provider="google",
        id_token=str(token_payload.get("id_token")),
        google_access_token=str(access_token),
        expires_in=int(token_payload.get("expires_in", 0)) if token_payload.get("expires_in") else None,
        refresh_token=token_payload.get("refresh_token"),
        scope=token_payload.get("scope"),
    )


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization header.")
    return token


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    authorization: Annotated[str | None, Header(alias="Authorization")],
    user_dao: UserDAO = Depends(get_user_dao),
) -> LogoutResponse:
    token = _extract_bearer_token(authorization)
    decoded = decode_access_token(token)
    if decoded:
        return LogoutResponse(detail="Local session cleared.")

    user = await user_dao.get_by_google_access_token(token)
    if user:
        await revoke_google_token(token)
        await user_dao.clear_google_tokens(user)
        return LogoutResponse(detail="Google session revoked.")

    id_info = await verify_id_token(token)
    google_sub = id_info.get("sub")
    if not google_sub:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Google token.",
        )

    user = await user_dao.get_by_google_sub(google_sub)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found for Google token.",
        )

    token_to_revoke = user.google_access_token or token
    await revoke_google_token(token_to_revoke)
    await user_dao.clear_google_tokens(user)
    return LogoutResponse(detail="Google session revoked.")

