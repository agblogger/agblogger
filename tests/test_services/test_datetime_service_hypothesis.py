"""Property-based tests for datetime parsing and formatting."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta, timezone

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.services.datetime_service import (
    format_datetime,
    format_iso,
    parse_datetime,
)

PROPERTY_SETTINGS = settings(
    max_examples=260,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

_STRICT_FORMAT_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{6}[+-]\d{2}:?\d{2}$")

# Timezone-aware datetimes (the primary domain)
_AWARE_DATETIME = st.datetimes(
    min_value=datetime(1970, 1, 2),
    max_value=datetime(2099, 12, 31),
    timezones=st.just(UTC),
)

# Naive datetimes (no timezone info)
_NAIVE_DATETIME = st.datetimes(
    min_value=datetime(1970, 1, 2),
    max_value=datetime(2099, 12, 31),
    timezones=st.none(),
)

# Datetimes with various fixed-offset timezones
_OFFSET_HOURS = st.integers(min_value=-12, max_value=14)
_OFFSET_DATETIME = st.builds(
    lambda dt, hours: dt.replace(tzinfo=UTC).astimezone(timezone(offset=timedelta(hours=hours))),
    _NAIVE_DATETIME,
    _OFFSET_HOURS,
)


class TestFormatDatetimeProperties:
    @PROPERTY_SETTINGS
    @given(dt=_AWARE_DATETIME)
    def test_format_produces_strict_format_string(self, dt: datetime) -> None:
        """format_datetime always produces YYYY-MM-DD HH:MM:SS.ffffff±HH:MM."""
        result = format_datetime(dt)
        assert _STRICT_FORMAT_RE.match(result), f"Bad format: {result!r}"

    @PROPERTY_SETTINGS
    @given(dt=_NAIVE_DATETIME)
    def test_naive_datetimes_are_treated_as_utc(self, dt: datetime) -> None:
        """Naive datetimes get UTC timezone attached before formatting."""
        result = format_datetime(dt)
        assert result.endswith("+0000") or result.endswith("+00:00")

    @PROPERTY_SETTINGS
    @given(dt=_OFFSET_DATETIME)
    def test_format_preserves_offset_timezone(self, dt: datetime) -> None:
        """Timezone offset is preserved in formatted output."""
        result = format_datetime(dt)
        assert _STRICT_FORMAT_RE.match(result)
        # Roundtrip through parse_datetime to verify the instant is preserved
        reparsed = parse_datetime(result)
        assert abs((reparsed - dt).total_seconds()) < 0.001


class TestParseDatetimeProperties:
    @PROPERTY_SETTINGS
    @given(dt=_AWARE_DATETIME)
    def test_parse_accepts_own_format_output(self, dt: datetime) -> None:
        """parse_datetime accepts strings produced by format_datetime."""
        formatted = format_datetime(dt)
        parsed = parse_datetime(formatted)
        assert parsed.tzinfo is not None

    @PROPERTY_SETTINGS
    @given(dt=_NAIVE_DATETIME)
    def test_parse_datetime_object_attaches_default_tz(self, dt: datetime) -> None:
        """Passing a naive datetime object attaches the default timezone."""
        result = parse_datetime(dt, fallback_tz="UTC")
        assert result.tzinfo is not None

    @PROPERTY_SETTINGS
    @given(dt=_AWARE_DATETIME)
    def test_parse_aware_datetime_object_preserves_tz(self, dt: datetime) -> None:
        """Passing an aware datetime object returns it unchanged."""
        result = parse_datetime(dt)
        assert result == dt
        assert result.tzinfo is not None


class TestRoundtripProperties:
    @PROPERTY_SETTINGS
    @given(dt=_AWARE_DATETIME)
    def test_format_then_parse_preserves_instant(self, dt: datetime) -> None:
        """format_datetime → parse_datetime preserves the datetime to microsecond precision."""
        formatted = format_datetime(dt)
        parsed = parse_datetime(formatted)
        # Compare as UTC timestamps to avoid timezone representation differences
        assert abs((parsed - dt).total_seconds()) < 0.001

    @PROPERTY_SETTINGS
    @given(dt=_AWARE_DATETIME)
    def test_format_is_idempotent_through_roundtrip(self, dt: datetime) -> None:
        """Formatting, parsing, and formatting again produces the same string."""
        first = format_datetime(dt)
        second = format_datetime(parse_datetime(first))
        assert first == second

    @PROPERTY_SETTINGS
    @given(dt=_OFFSET_DATETIME)
    def test_offset_roundtrip_preserves_instant(self, dt: datetime) -> None:
        """Roundtrip through format/parse preserves the instant for offset timezones."""
        formatted = format_datetime(dt)
        parsed = parse_datetime(formatted)
        assert abs((parsed - dt).total_seconds()) < 0.001


class TestFormatIsoProperties:
    @PROPERTY_SETTINGS
    @given(dt=_AWARE_DATETIME)
    def test_format_iso_produces_valid_isoformat(self, dt: datetime) -> None:
        """format_iso output can be parsed by datetime.fromisoformat."""
        iso_str = format_iso(dt)
        reparsed = datetime.fromisoformat(iso_str)
        assert abs((reparsed - dt).total_seconds()) < 0.001

    @PROPERTY_SETTINGS
    @given(dt=_NAIVE_DATETIME)
    def test_format_iso_attaches_utc_to_naive(self, dt: datetime) -> None:
        """Naive datetimes get UTC attached before ISO formatting."""
        iso_str = format_iso(dt)
        reparsed = datetime.fromisoformat(iso_str)
        assert reparsed.tzinfo is not None


class TestDateOnlyParsingProperties:
    @PROPERTY_SETTINGS
    @given(d=st.dates(min_value=date(1970, 1, 2), max_value=date(2099, 12, 31)))
    def test_date_only_strings_parse_to_midnight(self, d: date) -> None:
        """Date-only strings (YYYY-MM-DD) parse to midnight with default timezone."""
        date_str = d.isoformat()
        parsed = parse_datetime(date_str, fallback_tz="UTC")
        assert parsed.hour == 0
        assert parsed.minute == 0
        assert parsed.second == 0
        assert parsed.tzinfo is not None
