from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from starlette import status

import vidx.web.api.auth.views as auth_views
from vidx.services.auth.security import (
    create_access_token,
    create_state_token,
    hash_password,
    verify_password,
)
from vidx.settings import settings
from vidx.web.api.auth.views import get_user_dao


@dataclass
class FakeUser:
    email: str
    hashed_password: Optional[str] = None
    full_name: Optional[str] = None
    providers: list[str] = field(default_factory=list)
    google_sub: Optional[str] = None
    google_access_token: Optional[str] = None
    google_refresh_token: Optional[str] = None
    id: str = field(default_factory=lambda: str(uuid4()))
    last_login_at: Optional[datetime] = None


class FakeUserDAO:
    def __init__(self) -> None:
        self._by_email: dict[str, FakeUser] = {}
        self._by_google_sub: dict[str, FakeUser] = {}
        self._by_google_access: dict[str, FakeUser] = {}

    def _sync_indexes(self, user: FakeUser) -> None:
        self._by_email[user.email] = user
        # purge existing entries for this user
        for sub, existing in list(self._by_google_sub.items()):
            if existing is user:
                del self._by_google_sub[sub]
        for token, existing in list(self._by_google_access.items()):
            if existing is user:
                del self._by_google_access[token]
        if user.google_sub:
            self._by_google_sub[user.google_sub] = user
        if user.google_access_token:
            self._by_google_access[user.google_access_token] = user

    async def get_by_email(self, email: str) -> FakeUser | None:
        return self._by_email.get(email)

    async def get_by_google_sub(self, google_sub: str) -> FakeUser | None:
        return self._by_google_sub.get(google_sub)

    async def get_by_google_access_token(self, access_token: str) -> FakeUser | None:
        return self._by_google_access.get(access_token)

    async def create_user(
        self,
        *,
        email: str,
        hashed_password: Optional[str] = None,
        full_name: Optional[str] = None,
        providers: Optional[list[str]] = None,
        google_sub: Optional[str] = None,
        google_access_token: Optional[str] = None,
        google_refresh_token: Optional[str] = None,
    ) -> FakeUser:
        user = FakeUser(
            email=email,
            hashed_password=hashed_password,
            full_name=full_name,
            providers=list(providers or []),
            google_sub=google_sub,
            google_access_token=google_access_token,
            google_refresh_token=google_refresh_token,
            last_login_at=datetime.utcnow(),
        )
        self._sync_indexes(user)
        return user

    async def update_google_tokens(
        self,
        user: FakeUser,
        *,
        access_token: str,
        refresh_token: Optional[str],
        google_sub: str,
    ) -> FakeUser:
        user.google_access_token = access_token
        if refresh_token:
            user.google_refresh_token = refresh_token
        user.google_sub = google_sub
        if "google" not in user.providers:
            user.providers.append("google")
        user.last_login_at = datetime.utcnow()
        self._sync_indexes(user)
        return user

    async def clear_google_tokens(self, user: FakeUser) -> FakeUser:
        user.google_access_token = None
        user.google_refresh_token = None
        self._sync_indexes(user)
        return user

    async def touch_login(self, user: FakeUser) -> FakeUser:
        user.last_login_at = datetime.utcnow()
        self._sync_indexes(user)
        return user


@pytest.fixture(autouse=True)
def configure_google(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "google_client_id", "test-client")
    monkeypatch.setattr(settings, "google_client_secret", "test-secret")
    monkeypatch.setattr(settings, "google_redirect_uri", "http://test/api/auth/google/callback")


@pytest.fixture
def fake_user_dao(fastapi_app: FastAPI) -> FakeUserDAO:
    dao = FakeUserDAO()
    fastapi_app.dependency_overrides[get_user_dao] = lambda: dao
    try:
        yield dao
    finally:
        fastapi_app.dependency_overrides.pop(get_user_dao, None)


@pytest.mark.anyio
async def test_register_creates_local_user(
    client: AsyncClient,
    fake_user_dao: FakeUserDAO,
) -> None:
    response = await client.post(
        "/api/auth/register",
        json={"email": "person@example.com", "password": "secret123", "full_name": "Person"},
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["provider"] == "local"
    assert data["token_type"] == "bearer"
    stored = await fake_user_dao.get_by_email("person@example.com")
    assert stored is not None
    assert stored.full_name == "Person"
    assert "local" in stored.providers
    assert stored.hashed_password is not None
    assert verify_password("secret123", stored.hashed_password)


@pytest.mark.anyio
async def test_register_rejects_existing_email(
    client: AsyncClient,
    fake_user_dao: FakeUserDAO,
) -> None:
    payload = {"email": "dupe@example.com", "password": "secret123"}
    first = await client.post("/api/auth/register", json=payload)
    assert first.status_code == status.HTTP_201_CREATED
    second = await client.post("/api/auth/register", json=payload)
    assert second.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.anyio
async def test_login_returns_token_for_valid_credentials(
    client: AsyncClient,
    fake_user_dao: FakeUserDAO,
) -> None:
    await fake_user_dao.create_user(
        email="person@example.com",
        hashed_password=hash_password("secret123"),
        providers=["local"],
    )
    response = await client.post(
        "/api/auth/login",
        json={"email": "person@example.com", "password": "secret123"},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["provider"] == "local"
    assert data["token_type"] == "bearer"


@pytest.mark.anyio
async def test_login_rejects_bad_credentials(
    client: AsyncClient,
    fake_user_dao: FakeUserDAO,
) -> None:
    await fake_user_dao.create_user(
        email="person@example.com",
        hashed_password=hash_password("secret123"),
        providers=["local"],
    )
    response = await client.post(
        "/api/auth/login",
        json={"email": "person@example.com", "password": "wrong"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_google_login_redirects_to_provider(client: AsyncClient) -> None:
    response = await client.get("/api/auth/google/login")
    assert response.status_code == status.HTTP_307_TEMPORARY_REDIRECT
    location = response.headers["location"]
    assert settings.google_authorize_uri in location
    assert "state=" in location


@pytest.mark.anyio
async def test_google_callback_creates_user_and_tokens(
    client: AsyncClient,
    fake_user_dao: FakeUserDAO,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state_token({"nonce": "abc"})

    async def fake_exchange(code: str) -> dict[str, str]:
        assert code == "auth-code"
        return {
            "id_token": "id-token",
            "access_token": "google-access",
            "refresh_token": "google-refresh",
            "expires_in": 3600,
            "scope": "profile email",
        }

    async def fake_verify(token: str) -> dict[str, str]:
        assert token == "id-token"
        return {"sub": "google-123", "email": "oauth@example.com", "name": "OAuth User"}

    monkeypatch.setattr(auth_views, "exchange_code_for_tokens", fake_exchange)
    monkeypatch.setattr(auth_views, "verify_id_token", fake_verify)

    response = await client.get(
        "/api/auth/google/callback",
        params={"code": "auth-code", "state": state},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["provider"] == "google"
    assert data["id_token"] == "id-token"
    stored = await fake_user_dao.get_by_email("oauth@example.com")
    assert stored is not None
    assert stored.google_access_token == "google-access"
    assert "google" in stored.providers


@pytest.mark.anyio
async def test_google_callback_links_existing_email(
    client: AsyncClient,
    fake_user_dao: FakeUserDAO,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await fake_user_dao.create_user(
        email="oauth@example.com",
        hashed_password=hash_password("secret123"),
        providers=["local"],
    )
    state = create_state_token({"nonce": "abc"})

    async def fake_exchange(_: str) -> dict[str, str]:
        return {
            "id_token": "id-token",
            "access_token": "new-google-access",
            "refresh_token": None,
        }

    async def fake_verify(_: str) -> dict[str, str]:
        return {"sub": "google-123", "email": "oauth@example.com", "name": "OAuth User"}

    monkeypatch.setattr(auth_views, "exchange_code_for_tokens", fake_exchange)
    monkeypatch.setattr(auth_views, "verify_id_token", fake_verify)

    response = await client.get(
        "/api/auth/google/callback",
        params={"code": "auth-code", "state": state},
    )
    assert response.status_code == status.HTTP_200_OK
    linked = await fake_user_dao.get_by_google_sub("google-123")
    assert linked is not None
    assert linked.google_access_token == "new-google-access"
    assert "google" in linked.providers
    assert linked.full_name == "OAuth User"


@pytest.mark.anyio
async def test_logout_with_local_jwt(
    client: AsyncClient,
    fake_user_dao: FakeUserDAO,
) -> None:
    user = await fake_user_dao.create_user(
        email="person@example.com",
        hashed_password=hash_password("secret123"),
        providers=["local"],
    )
    token = create_access_token({"sub": user.id, "email": user.email, "provider": "local"})
    response = await client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"detail": "Local session cleared."}


@pytest.mark.anyio
async def test_logout_with_google_access_token(
    client: AsyncClient,
    fake_user_dao: FakeUserDAO,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await fake_user_dao.create_user(
        email="oauth@example.com",
        providers=["google"],
        google_sub="google-123",
        google_access_token="live-google-access",
    )

    revoked: list[str] = []

    async def fake_revoke(token: str) -> None:
        revoked.append(token)

    async def fail_verify(_: str) -> dict[str, str]:
        raise AssertionError("verify_id_token should not be called for stored access tokens")

    monkeypatch.setattr(auth_views, "revoke_google_token", fake_revoke)
    monkeypatch.setattr(auth_views, "verify_id_token", fail_verify)

    response = await client.post(
        "/api/auth/logout",
        headers={"Authorization": "Bearer live-google-access"},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"detail": "Google session revoked."}
    assert revoked == ["live-google-access"]
    stored = await fake_user_dao.get_by_google_sub("google-123")
    assert stored is not None
    assert stored.google_access_token is None


@pytest.mark.anyio
async def test_logout_with_google_id_token_falls_back_to_profile_lookup(
    client: AsyncClient,
    fake_user_dao: FakeUserDAO,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await fake_user_dao.create_user(
        email="oauth@example.com",
        providers=["google"],
        google_sub="google-123",
        google_access_token="persisted-access",
        google_refresh_token="persisted-refresh",
    )

    revoked: list[str] = []

    async def fake_revoke(token: str) -> None:
        revoked.append(token)

    async def fake_verify(token: str) -> dict[str, str]:
        assert token == "id-token"
        return {"sub": "google-123"}

    monkeypatch.setattr(auth_views, "revoke_google_token", fake_revoke)
    monkeypatch.setattr(auth_views, "verify_id_token", fake_verify)

    response = await client.post(
        "/api/auth/logout",
        headers={"Authorization": "Bearer id-token"},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"detail": "Google session revoked."}
    assert revoked == ["persisted-access"]
    stored = await fake_user_dao.get_by_google_sub("google-123")
    assert stored is not None
    assert stored.google_access_token is None
    assert stored.google_refresh_token is None
