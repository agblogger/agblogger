"""Admin panel request/response schemas."""

from __future__ import annotations

import re
import zoneinfo

from pydantic import BaseModel, Field, field_validator, model_validator

PAGE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
PAGE_ID_ERROR = (
    "Invalid page ID: must start with a lowercase letter or digit, "
    "and contain only lowercase alphanumeric characters, hyphens, or underscores."
)


class SiteSettingsUpdate(BaseModel):
    """Request to update site settings."""

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    timezone: str = Field(default="UTC", max_length=100)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        try:
            zoneinfo.ZoneInfo(v)
        except (KeyError, ValueError) as err:
            raise ValueError(f"Invalid timezone: {v}") from err
        return v


class SiteSettingsResponse(BaseModel):
    """Site settings response."""

    title: str
    description: str
    timezone: str
    password_change_disabled: bool


class AdminPageConfig(BaseModel):
    """Page config for admin panel."""

    id: str
    title: str
    file: str | None = None
    is_builtin: bool = False
    content: str | None = None


class AdminPagesResponse(BaseModel):
    """Response for admin pages listing."""

    pages: list[AdminPageConfig]


class PageCreate(BaseModel):
    """Request to create a new page."""

    id: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    title: str = Field(min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=500_000)


class PageUpdate(BaseModel):
    """Request to update a page's title and/or content."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, max_length=500_000)


class PageOrderItem(BaseModel):
    """A single page in the reorder list."""

    id: str
    title: str
    file: str | None = None

    @field_validator("file")
    @classmethod
    def validate_file_path(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v.startswith("/") or ".." in v.split("/"):
            raise ValueError("Invalid file path")
        return v


class PageOrderUpdate(BaseModel):
    """Request to update page order."""

    pages: list[PageOrderItem]


class PasswordChange(BaseModel):
    """Request to change admin password."""

    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def passwords_match(self) -> PasswordChange:
        if self.new_password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self
