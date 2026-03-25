"""Pydantic request/response schemas for analytics endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class AnalyticsSettingsResponse(BaseModel):
    """Response for analytics settings."""

    analytics_enabled: bool
    show_views_on_posts: bool


class AnalyticsSettingsUpdate(BaseModel):
    """Request to update analytics settings (partial)."""

    analytics_enabled: bool | None = None
    show_views_on_posts: bool | None = None

    @model_validator(mode="after")
    def check_at_least_one_field(self) -> AnalyticsSettingsUpdate:
        if self.analytics_enabled is None and self.show_views_on_posts is None:
            raise ValueError("At least one field must be provided")
        return self


class ViewCountResponse(BaseModel):
    """View count for a single post path."""

    views: int | None = Field(default=None, ge=0)


class TotalStatsResponse(BaseModel):
    """Aggregated total stats across all paths."""

    total_views: int = Field(ge=0)
    total_unique: int = Field(ge=0)


class PathHit(BaseModel):
    """Hit counts for a single path."""

    path_id: int = Field(ge=1)
    path: str = Field(min_length=1)
    views: int = Field(ge=0)
    unique: int = Field(ge=0)


class PathHitsResponse(BaseModel):
    """Hit counts for multiple paths."""

    paths: list[PathHit] = Field(default_factory=list)


class ReferrerEntry(BaseModel):
    """A single referrer entry for a path."""

    referrer: str
    count: int = Field(ge=0)


class PathReferrersResponse(BaseModel):
    """Referrer breakdown for a given path ID."""

    path_id: int
    referrers: list[ReferrerEntry] = Field(default_factory=list)


class BreakdownEntry(BaseModel):
    """A single breakdown entry (browser, OS, country, etc.)."""

    name: str
    count: int = Field(ge=0)
    percent: float = Field(ge=0, le=100)


BreakdownCategory = Literal["browsers", "systems", "languages", "locations", "sizes", "campaigns"]


class BreakdownResponse(BaseModel):
    """Breakdown stats for a category."""

    category: BreakdownCategory
    entries: list[BreakdownEntry] = Field(default_factory=list)
