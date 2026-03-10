"""Tests for shared validation utilities."""

from __future__ import annotations

from backend.validation import is_valid_trusted_host


class TestIsValidTrustedHost:
    def test_explicit_hostname(self) -> None:
        assert is_valid_trusted_host("example.com") is True

    def test_subdomain(self) -> None:
        assert is_valid_trusted_host("blog.example.com") is True

    def test_narrow_wildcard(self) -> None:
        assert is_valid_trusted_host("*.example.com") is True

    def test_rejects_catch_all_wildcard(self) -> None:
        assert is_valid_trusted_host("*") is False

    def test_rejects_empty(self) -> None:
        assert is_valid_trusted_host("") is False

    def test_rejects_whitespace_only(self) -> None:
        assert is_valid_trusted_host("   ") is False

    def test_rejects_bare_wildcard_dot(self) -> None:
        assert is_valid_trusted_host("*.") is False

    def test_rejects_multiple_wildcards(self) -> None:
        assert is_valid_trusted_host("*.*.example.com") is False

    def test_rejects_mid_wildcard(self) -> None:
        assert is_valid_trusted_host("sub.*.example.com") is False
