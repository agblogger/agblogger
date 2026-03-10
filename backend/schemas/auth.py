"""Authentication schemas."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

if TYPE_CHECKING:
    from backend.models.user import User

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


class RegisterRequest(BaseModel):
    """User registration request."""

    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    display_name: str | None = Field(default=None, max_length=100)
    invite_code: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("username")
    @classmethod
    def validate_username_format(cls, v: str) -> str:
        """Ensure username is safe for DB and YAML storage."""
        return _validate_username(v)


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


class InviteCreateRequest(BaseModel):
    """Request to create a registration invite code."""

    expires_days: int | None = Field(default=None, ge=1, le=90)


class InviteCreateResponse(BaseModel):
    """Response containing a new invite code."""

    invite_code: str
    created_at: str
    expires_at: str


class PersonalAccessTokenCreateRequest(BaseModel):
    """Request to create a personal access token."""

    name: str = Field(min_length=1, max_length=100)
    expires_days: int | None = Field(default=30, ge=1, le=3650)


class PersonalAccessTokenResponse(BaseModel):
    """Personal access token metadata."""

    id: int
    name: str
    created_at: str
    expires_at: str | None = None
    last_used_at: str | None = None
    revoked_at: str | None = None


class PersonalAccessTokenCreateResponse(PersonalAccessTokenResponse):
    """Created token metadata including one-time plaintext token."""

    token: str


class ProfileUpdate(BaseModel):
    """Request to update the current user's profile."""

    username: str | None = Field(default=None, min_length=3, max_length=50)
    display_name: str | None = Field(default=None, max_length=100)

    @field_validator("username")
    @classmethod
    def validate_username_format(cls, v: str | None) -> str | None:
        """Ensure username is safe for DB and YAML storage."""
        if v is not None:
            _validate_username(v)
        return v

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, v: str | None) -> str | None:
        """Strip whitespace; empty/whitespace-only strings become empty."""
        if v is not None:
            return v.strip()
        return v


class UserResponse(BaseModel):
    """User info response."""

    id: int
    username: str
    email: str
    display_name: str | None = None
    is_admin: bool = False

    @classmethod
    def from_user(cls, user: User) -> UserResponse:
        """Build from a User ORM model."""
        return cls(
            id=user.id,
            username=user.username,
            email=user.email,
            display_name=user.display_name,
            is_admin=user.is_admin,
        )
