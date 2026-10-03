
from __future__ import annotations

from typing import Callable

from fastapi import HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from vidx.db.dao.user_dao import UserDAO
from vidx.db.models.user import User
from vidx.services.auth.google import verify_id_token
from vidx.services.auth.security import decode_access_token


class AuthMiddleware(BaseHTTPMiddleware):
    """Authenticate requests targeting protected API prefixes."""

    def __init__(
        self,
        app: ASGIApp,
        protected_prefixes: tuple[str, ...] = (
            "/api/video",
            "/api/projects",
            "/api/posts",
            "/api/scenes",
        ),
    ) -> None:
        super().__init__(app)
        self.protected_prefixes = protected_prefixes
        self.user_dao = UserDAO()

    async def dispatch(self, request: Request, call_next: Callable[[Request], Response]) -> Response:
        is_protected = any(
            request.url.path.startswith(prefix) for prefix in self.protected_prefixes
        )
        if not is_protected or request.method == "OPTIONS":
            return await call_next(request)

        authorization = request.headers.get("Authorization")
        if not authorization:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Authorization header missing."},
            )
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid authorization header."},
            )

        user, provider = await self._authenticate_local(token)
        if user is None:
            user, provider = await self._authenticate_google(token)

        if user is None:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid or expired token."},
            )

        request.state.user = user
        request.state.auth_provider = provider
        return await call_next(request)

    async def _authenticate_local(self, token: str) -> tuple[User | None, str | None]:
        payload = decode_access_token(token)
        if not payload:
            return None, None
        email = payload.get("email")
        if not email:
            return None, None
        user = await self.user_dao.get_by_email(email)
        if not user:
            return None, None
        return user, payload.get("provider") or "local"

    async def _authenticate_google(self, token: str) -> tuple[User | None, str | None]:
        try:
            id_info = await verify_id_token(token)
        except HTTPException:
            # A token that cannot be verified (expired/invalid JWT) or a server
            # without Google configuration is simply not a Google session:
            # fall through to a clean 401 rather than a 500.
            return None, None
        except Exception:
            return None, None

        google_sub = id_info.get("sub")
        email = id_info.get("email")
        if not google_sub and not email:
            return None, None

        user = None
        if google_sub:
            user = await self.user_dao.get_by_google_sub(google_sub)
        if not user and email:
            user = await self.user_dao.get_by_email(email)
        if not user:
            return None, None
        return user, "google"

