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
    """Aggregated total stats across all paths.

    GoatCounter only tracks unique views (first-visit per session),
    so ``visitors`` maps directly to GoatCounter's ``total`` field.
    """

    visitors: int = Field(ge=0)

    @classmethod
    def from_goatcounter(cls, data: dict[str, Any]) -> TotalStatsResponse:
        """Construct from a raw GoatCounter JSON dict, logging DEBUG on missing key."""
        if "total" not in data:
            logger.debug(
                "GoatCounter total stats response missing 'total' key (got: %s)",
                list(data.keys()),
            )
        return cls(visitors=data.get("total", 0))


class PathHit(BaseModel):
    """Visitor counts for a single path.

    GoatCounter only tracks unique views (first-visit per session per path),
    so ``views`` maps directly to GoatCounter's ``count`` field.
    """

    path_id: int = Field(ge=1)
    path: str = Field(min_length=1)
    views: int = Field(ge=0)

    @classmethod
    def from_goatcounter(cls, entry: dict[str, Any]) -> PathHit:
        """Construct from a raw GoatCounter hit entry, logging DEBUG on missing keys."""
        missing = [k for k in ("path_id", "path", "count") if k not in entry]
        if missing:
            logger.debug(
                "GoatCounter hit entry missing expected keys: %s (got: %s)",
                missing,
                list(entry.keys()),
            )
        return cls(
            path_id=entry.get("path_id", entry.get("id", 0)),
            path=entry.get("path", ""),
            views=entry.get("count", 0),
        )


class PathHitsResponse(BaseModel):
    """Visitor counts for multiple paths."""

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
        name = entry.get("name", "")
        referrer = name if isinstance(name, str) and name != "" else "Direct"
        return cls(referrer=referrer, count=entry.get("count", 0))


class PathReferrersResponse(BaseModel):
    """Referrer breakdown for a given path ID."""

    path_id: int = Field(ge=1)
    referrers: list[ReferrerEntry] = Field(default_factory=list)


class SiteReferrersResponse(BaseModel):
    """Aggregated referrer counts across all paths."""

    referrers: list[ReferrerEntry] = Field(default_factory=list)


class BreakdownEntry(BaseModel):
    """A single breakdown entry (browser, OS, country, etc.)."""

    name: str
    count: int = Field(ge=0)
    percent: float = Field(ge=0, le=100)
    gc_id: str | None = None  # GoatCounter entry ID for drill-down

    @classmethod
    def from_goatcounter(
        cls,
        entry: dict[str, Any],
        *,
        total_count: int | None = None,
    ) -> BreakdownEntry:
        """Construct from a raw GoatCounter breakdown entry, logging DEBUG on missing keys."""
        missing = [k for k in ("name", "count") if k not in entry]
        if missing:
            logger.debug(
                "GoatCounter breakdown entry missing expected keys: %s (got: %s)",
                missing,
                list(entry.keys()),
            )
        name = entry.get("name", "")
        if not isinstance(name, str) or not name.strip():
            name = "Unknown"
        raw_count = entry.get("count", 0)
        count = raw_count if isinstance(raw_count, int) else 0
        percent = entry.get("percent")
        if percent is None:
            percent = (count / total_count * 100.0) if total_count and total_count > 0 else 0.0
        gc_id_raw = entry.get("id")
        gc_id = gc_id_raw if isinstance(gc_id_raw, str) and gc_id_raw else None
        return cls(
            name=name,
            count=count,
            percent=percent,
            gc_id=gc_id,
        )


BreakdownCategory = Literal["browsers", "systems", "languages", "locations", "sizes", "campaigns"]


class BreakdownResponse(BaseModel):
    """Breakdown stats for a category."""

    category: BreakdownCategory
    entries: list[BreakdownEntry] = Field(default_factory=list)


BreakdownDetailCategory = Literal["browsers", "systems"]


class BreakdownDetailEntry(BaseModel):
    """A version entry within a breakdown category (e.g. Chrome 120)."""

    name: str
    count: int = Field(ge=0)
    percent: float = Field(ge=0, le=100)

    @classmethod
    def from_goatcounter(
        cls,
        entry: dict[str, Any],
        *,
        total_count: int | None = None,
    ) -> BreakdownDetailEntry:
        """Construct from a raw GoatCounter detail entry."""
        name = entry.get("name", "")
        if not isinstance(name, str) or not name.strip():
            name = "Unknown"
        raw_count = entry.get("count", 0)
        count = raw_count if isinstance(raw_count, int) else 0
        percent = entry.get("percent")
        if percent is None:
            percent = (count / total_count * 100.0) if total_count and total_count > 0 else 0.0
        return cls(name=name, count=count, percent=percent)


class BreakdownDetailResponse(BaseModel):
    """Version detail for a breakdown entry (e.g. all Chrome versions)."""

    category: BreakdownDetailCategory
    entry_id: str = Field(min_length=1, max_length=200)
    entries: list[BreakdownDetailEntry] = Field(default_factory=list)


class DailyViewCount(BaseModel):
    """View count for a single day."""

    date: str = Field(min_length=10, max_length=10)
    views: int = Field(ge=0)


class ViewsOverTimeResponse(BaseModel):
    """Daily view counts aggregated across all paths."""

    days: list[DailyViewCount] = Field(default_factory=list)


class ExportCreateResponse(BaseModel):
    """Response after creating a CSV export job."""

    id: int = Field(ge=1)


class ExportStatusResponse(BaseModel):
    """Status of a CSV export job."""

    id: int = Field(ge=0)
    finished: bool
