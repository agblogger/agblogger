"""Pydantic request/response schemas for analytics endpoints."""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


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

    @classmethod
    def from_goatcounter(cls, data: dict[str, Any]) -> TotalStatsResponse:
        """Construct from a raw GoatCounter JSON dict, logging DEBUG on missing keys."""
        missing = [k for k in ("total", "total_unique") if k not in data]
        if missing:
            logger.debug(
                "GoatCounter total stats response missing expected keys: %s (got: %s)",
                missing,
                list(data.keys()),
            )
        return cls(
            total_views=data.get("total", 0),
            total_unique=data.get("total_unique", 0),
        )


class PathHit(BaseModel):
    """Hit counts for a single path."""

    path_id: int = Field(ge=1)
    path: str = Field(min_length=1)
    views: int = Field(ge=0)
    unique: int = Field(ge=0)

    @classmethod
    def from_goatcounter(cls, entry: dict[str, Any]) -> PathHit:
        """Construct from a raw GoatCounter hit entry, logging DEBUG on missing keys."""
        missing = [k for k in ("id", "path", "count", "count_unique") if k not in entry]
        if missing:
            logger.debug(
                "GoatCounter hit entry missing expected keys: %s (got: %s)",
                missing,
                list(entry.keys()),
            )
        return cls(
            path_id=entry.get("id", 0),
            path=entry.get("path", ""),
            views=entry.get("count", 0),
            unique=entry.get("count_unique", 0),
        )


class PathHitsResponse(BaseModel):
    """Hit counts for multiple paths."""

    paths: list[PathHit] = Field(default_factory=list)


class ReferrerEntry(BaseModel):
    """A single referrer entry for a path."""

    referrer: str
    count: int = Field(ge=0)

    @classmethod
    def from_goatcounter(cls, entry: dict[str, Any]) -> ReferrerEntry:
        """Construct from a raw GoatCounter referrer entry, logging DEBUG on missing keys."""
        missing = [k for k in ("name", "count") if k not in entry]
        if missing:
            logger.debug(
                "GoatCounter referrer entry missing expected keys: %s (got: %s)",
                missing,
                list(entry.keys()),
            )
        return cls(
            referrer=entry.get("name", ""),
            count=entry.get("count", 0),
        )


class PathReferrersResponse(BaseModel):
    """Referrer breakdown for a given path ID."""

    path_id: int = Field(ge=1)
    referrers: list[ReferrerEntry] = Field(default_factory=list)


class BreakdownEntry(BaseModel):
    """A single breakdown entry (browser, OS, country, etc.)."""

    name: str
    count: int = Field(ge=0)
    percent: float = Field(ge=0, le=100)

    @classmethod
    def from_goatcounter(cls, entry: dict[str, Any]) -> BreakdownEntry:
        """Construct from a raw GoatCounter breakdown entry, logging DEBUG on missing keys."""
        missing = [k for k in ("name", "count", "percent") if k not in entry]
        if missing:
            logger.debug(
                "GoatCounter breakdown entry missing expected keys: %s (got: %s)",
                missing,
                list(entry.keys()),
            )
        return cls(
            name=entry.get("name", ""),
            count=entry.get("count", 0),
            percent=entry.get("percent", 0.0),
        )


BreakdownCategory = Literal["browsers", "systems", "languages", "locations", "sizes", "campaigns"]


class BreakdownResponse(BaseModel):
    """Breakdown stats for a category."""

    category: BreakdownCategory
    entries: list[BreakdownEntry] = Field(default_factory=list)
