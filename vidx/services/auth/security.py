
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from jose import JWTError, jwt
from passlib.context import CryptContext

from vidx.settings import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a plaintext password."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str | None) -> bool:
    """Verify a plaintext password against a stored hash."""
    if not hashed_password:
        return False
    return pwd_context.verify(plain_password, hashed_password)


def _default_expiration() -> timedelta:
    return timedelta(minutes=settings.jwt_expiration_minutes)


def create_access_token(data: Dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """Create an encoded JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or _default_expiration())
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Dict[str, Any] | None:
    """Decode a JWT access token, returning ``None`` if invalid."""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


def create_state_token(state_data: Dict[str, Any], expires_seconds: int = 600) -> str:
    """Create a short-lived signed token used as OAuth state."""
    to_encode = state_data.copy()
    expire = datetime.now(timezone.utc) + timedelta(seconds=expires_seconds)
    to_encode.update({"exp": expire, "type": "state"})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_state_token(token: str) -> Dict[str, Any] | None:
    """Decode an OAuth state token."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
    if payload.get("type") != "state":
        return None
    return payload

