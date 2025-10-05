
from __future__ import annotations

from datetime import datetime

from vidx.db.models.user import User


class UserDAO:
    """Data access helpers for ``User`` documents."""

    async def get_by_email(self, email: str) -> User | None:
        return await User.find_one(User.email == email)

    async def get_by_google_sub(self, google_sub: str) -> User | None:
        return await User.find_one(User.google_sub == google_sub)

    async def get_by_google_access_token(self, access_token: str) -> User | None:
        return await User.find_one(User.google_access_token == access_token)

    async def create_user(
        self,
        *,
        email: str,
        hashed_password: str | None = None,
        full_name: str | None = None,
        providers: list[str] | None = None,
        google_sub: str | None = None,
        google_access_token: str | None = None,
        google_refresh_token: str | None = None,
    ) -> User:
        providers = providers or []
        user = User(
            email=email,
            hashed_password=hashed_password,
            full_name=full_name,
            providers=providers,
            google_sub=google_sub,
            google_access_token=google_access_token,
            google_refresh_token=google_refresh_token,
            last_login_at=datetime.utcnow(),
        )
        await user.insert()
        return user

    async def update_google_tokens(
        self,
        user: User,
        *,
        access_token: str,
        refresh_token: str | None,
        google_sub: str,
    ) -> User:
        user.google_access_token = access_token
        if refresh_token:
            user.google_refresh_token = refresh_token
        user.google_sub = google_sub
        if 'google' not in user.providers:
            user.providers.append('google')
        user.last_login_at = datetime.utcnow()
        return await user.save()

    async def clear_google_tokens(self, user: User) -> User:
        user.google_access_token = None
        user.google_refresh_token = None
        return await user.save()

    async def touch_login(self, user: User) -> User:
        user.last_login_at = datetime.utcnow()
        return await user.save()

