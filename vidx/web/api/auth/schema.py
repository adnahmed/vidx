
from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    provider: str


class GoogleAuthResponse(TokenResponse):
    id_token: str
    google_access_token: str
    expires_in: int | None = None
    refresh_token: str | None = None
    scope: str | None = None


class LogoutResponse(BaseModel):
    detail: str

