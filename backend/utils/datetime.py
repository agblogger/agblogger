"""Shared low-level datetime helpers used across backend layers."""

from __future__ import annotations

from datetime import UTC, datetime

import pendulum
from pendulum.parsing.exceptions import ParserError

# Strict output format: YYYY-MM-DD HH:MM:SS.ffffff±TZ
STRICT_FORMAT = "%Y-%m-%d %H:%M:%S.%f%z"


def parse_datetime(value: str | datetime, fallback_tz: str = "UTC") -> datetime:
    """Parse a lax datetime string into a strict timezone-aware datetime."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            tz = pendulum.timezone(fallback_tz)
            value = value.replace(tzinfo=tz)
        return value

    value_str = value.strip()

    try:
        parsed = pendulum.parse(value_str, tz=fallback_tz, strict=False)
    except ParserError as exc:
        raise ValueError(f"Cannot parse date from: {value_str}") from exc
    if isinstance(parsed, pendulum.DateTime):
        return parsed
    if not isinstance(parsed, pendulum.Date):
        msg = f"Cannot parse date from: {value_str}"
        raise ValueError(msg)
    return pendulum.datetime(parsed.year, parsed.month, parsed.day, tz=fallback_tz)


def format_datetime(dt: datetime) -> str:
    """Format a datetime to the strict output format."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.strftime(STRICT_FORMAT)


def now_utc() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(UTC)


def format_iso(dt: datetime) -> str:
    """Format datetime as ISO 8601 for JSON serialization."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()
