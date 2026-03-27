"""Authentication schemas."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

_USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")

_USERNAME_FORMAT_ERROR = (
    "Username must start with a letter or digit and contain only"
    " letters, digits, dots, hyphens, or underscores"
)


def _validate_username(v: str) -> str:
    """Validate username format for DB and YAML storage safety."""
    if not _USERNAME_PATTERN.match(v):
        raise ValueError(_USERNAME_FORMAT_ERROR)
    return v


def _default_token_type() -> Literal["bearer"]:
    return "bearer"


class LoginRequest(BaseModel):
    """Login request."""

    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    """Bearer access token response for non-browser clients."""

    access_token: str
    token_type: Literal["bearer"] = Field(default_factory=_default_token_type)


class SessionAuthResponse(BaseModel):
    """Cookie-authenticated session response."""

    csrf_token: str


class CsrfTokenResponse(BaseModel):
    """Stateless CSRF token response for cookie-authenticated sessions."""

    csrf_token: str


class RefreshRequest(BaseModel):
    """Token refresh request."""

    refresh_token: str | None = Field(default=None, min_length=1, max_length=512)


class LogoutRequest(BaseModel):
    """Logout request."""

    refresh_token: str | None = Field(default=None, min_length=1, max_length=512)


class ProfileUpdate(BaseModel):
    """Request to update the admin's profile."""

    username: str | None = Field(default=None, min_length=3, max_length=50)
    display_name: str | None = Field(default=None, max_length=100)

    @field_validator("username")
    @classmethod
    def validate_username_format(cls, v: str | None) -> str | None:
        """Ensure username is safe for DB and YAML storage."""
        if v is not None:
            return _validate_username(v)
        return v

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, v: str | None) -> str | None:
        """Strip whitespace; whitespace-only strings become empty string ''."""
        if v is not None:
            return v.strip()
        return v


class UserResponse(BaseModel):
    """User info response."""

    id: int
    username: str
    email: str
    display_name: str | None = None

    @classmethod
    def from_user(cls, user: Any) -> UserResponse:
        """Build from an object matching the admin-user shape."""
        return cls(
            id=user.id,
            username=user.username,
            email=user.email,
            display_name=user.display_name,
        )
