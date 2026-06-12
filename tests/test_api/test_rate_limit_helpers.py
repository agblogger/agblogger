"""Unit tests for the shared API-layer rate-limit helpers.

These guard the relocated client-IP resolution and HTTP 429 enforcement that
back the auth, refresh, password-change, and subscribe endpoints. The
integration-level abuse-path coverage lives in ``test_security_regressions.py``
and ``test_subscriptions_api.py``; these tests pin the extracted primitives.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException, status
from starlette.requests import Request

from backend.api.rate_limit import (
    client_ip_from_request,
    enforce_rate_limit,
    record_failure_and_enforce,
)
from backend.services.rate_limit_service import InMemoryRateLimiter


def _request(peer: str | None, forwarded: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode()))
    scope: dict[str, object] = {
        "type": "http",
        "headers": headers,
        "client": (peer, 12345) if peer is not None else None,
    }
    return Request(scope)


class TestClientIpFromRequest:
    def test_no_forwarded_header_uses_peer(self) -> None:
        req = _request("198.51.100.7")
        assert client_ip_from_request(req, ["127.0.0.1"]) == "198.51.100.7"

    def test_untrusted_peer_ignores_spoofed_forwarded_for(self) -> None:
        # Abuse path: an untrusted client spoofs X-Forwarded-For to dodge IP-keyed limits.
        req = _request("203.0.113.9", forwarded="1.2.3.4")
        assert client_ip_from_request(req, ["127.0.0.1"]) == "203.0.113.9"

    def test_trusted_peer_uses_first_forwarded_ip(self) -> None:
        req = _request("127.0.0.1", forwarded="5.6.7.8, 9.10.11.12")
        assert client_ip_from_request(req, ["127.0.0.1"]) == "5.6.7.8"

    def test_trusted_via_cidr_uses_forwarded_ip(self) -> None:
        req = _request("127.0.0.5", forwarded="5.6.7.8")
        assert client_ip_from_request(req, ["127.0.0.0/8"]) == "5.6.7.8"

    def test_missing_peer_returns_unknown(self) -> None:
        req = _request(None)
        assert client_ip_from_request(req, []) == "unknown"


class TestEnforceRateLimit:
    def test_under_limit_does_not_raise(self) -> None:
        limiter = InMemoryRateLimiter()
        enforce_rate_limit(limiter, "k", 2, 300, "too many")

    def test_raises_429_with_retry_after_when_limited(self) -> None:
        limiter = InMemoryRateLimiter()
        limiter.add_failure("k", 300)
        limiter.add_failure("k", 300)
        with pytest.raises(HTTPException) as exc:
            enforce_rate_limit(limiter, "k", 2, 300, "too many")
        assert exc.value.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert exc.value.detail == "too many"
        assert "Retry-After" in (exc.value.headers or {})


class TestRecordFailureAndEnforce:
    def test_raises_only_once_threshold_crossed(self) -> None:
        limiter = InMemoryRateLimiter()
        # First recorded failure stays under the limit of 2 → no raise.
        record_failure_and_enforce(limiter, "k", 2, 300, "too many")
        # Second crosses the threshold → 429.
        with pytest.raises(HTTPException) as exc:
            record_failure_and_enforce(limiter, "k", 2, 300, "too many")
        assert exc.value.status_code == status.HTTP_429_TOO_MANY_REQUESTS
