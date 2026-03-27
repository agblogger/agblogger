"""Tests for datetime parsing service."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.utils.datetime import format_datetime, now_utc, parse_datetime


class TestDatetimeParsing:
    def test_parse_full_format(self) -> None:
        result = parse_datetime("2026-02-02 22:21:29.975359+00")
        assert result.year == 2026
        assert result.month == 2
        assert result.day == 2
        assert result.hour == 22
        assert result.minute == 21

    def test_parse_date_only(self) -> None:
        result = parse_datetime("2026-02-02")
        assert result.year == 2026
        assert result.month == 2
        assert result.day == 2
        assert result.hour == 0
        assert result.minute == 0

    def test_parse_with_default_timezone(self) -> None:
        result = parse_datetime("2026-02-02 10:30", fallback_tz="America/New_York")
        assert result.year == 2026
        assert result.hour == 10

    def test_parse_datetime_object(self) -> None:
        dt = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        result = parse_datetime(dt)
        assert result == dt

    def test_parse_datetime_naive_adds_tz(self) -> None:
        dt = datetime(2026, 1, 1, 12, 0)
        result = parse_datetime(dt, fallback_tz="UTC")
        assert result.tzinfo is not None

    def test_format_datetime(self) -> None:
        dt = datetime(2026, 2, 2, 22, 21, 29, 975359, tzinfo=UTC)
        result = format_datetime(dt)
        assert "2026-02-02" in result
        assert "22:21:29" in result

    def test_now_utc(self) -> None:
        result = now_utc()
        assert result.tzinfo is not None
