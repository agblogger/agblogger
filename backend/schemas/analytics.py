"""Analytics schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AnalyticsSettingsResponse(BaseModel):
    """Response for analytics settings."""

    analytics_enabled: bool
    show_views_on_posts: bool


class AnalyticsSettingsUpdate(BaseModel):
    """Request to update analytics settings (partial)."""

    analytics_enabled: bool | None = None
    show_views_on_posts: bool | None = None


class ViewCountResponse(BaseModel):
    """View count for a single post path."""

    views: int | None = None


class TotalStatsResponse(BaseModel):
    """Aggregated total stats across all paths."""

    total_views: int
    total_unique: int


class PathHit(BaseModel):
    """Hit counts for a single path."""

    path_id: int
    path: str
    views: int
    unique: int


class PathHitsResponse(BaseModel):
    """Hit counts for multiple paths."""

    paths: list[PathHit] = Field(default_factory=list)


class ReferrerEntry(BaseModel):
    """A single referrer entry for a path."""

    referrer: str
    count: int


class PathReferrersResponse(BaseModel):
    """Referrer breakdown for a given path ID."""

    path_id: int
    referrers: list[ReferrerEntry] = Field(default_factory=list)


class BreakdownEntry(BaseModel):
    """A single breakdown entry (browser, OS, country, etc.)."""

    name: str
    count: int
    percent: float


class BreakdownResponse(BaseModel):
    """Breakdown stats for a category."""

    category: str
    entries: list[BreakdownEntry] = Field(default_factory=list)
