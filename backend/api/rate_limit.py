"""API-layer rate-limiting helpers shared across auth, admin, and subscriptions.

Resolves the client IP used to key per-client limits and translates limiter
state into HTTP 429 responses. The limiter *state* lives in the
framework-agnostic ``backend.services.rate_limit_service`` module; these helpers
are the HTTP-facing boundary that may raise ``HTTPException``.
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from backend.net_utils import is_trusted_proxy
from backend.services.rate_limit_service import InMemoryRateLimiter


def client_ip_from_request(request: Request, trusted_proxy_ips: list[str]) -> str:
    """Resolve the originating client IP for *request*.

    Honors the first ``X-Forwarded-For`` entry only when the direct peer is a
    trusted proxy; otherwise the forwarded header is ignored and the direct peer
    address is used. Returns ``"unknown"`` when the peer address is unavailable.
    """
    host = request.client.host if request.client and request.client.host else "unknown"
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded and is_trusted_proxy(host, trusted_proxy_ips):
        return forwarded.split(",", maxsplit=1)[0].strip()
    return host


def enforce_rate_limit(
    limiter: InMemoryRateLimiter,
    key: str,
    limit: int,
    window_seconds: int,
    detail: str,
) -> None:
    """Raise HTTP 429 with a ``Retry-After`` header if *key* is rate-limited."""
    limited, retry_after = limiter.is_limited(key, limit, window_seconds)
    if limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            headers={"Retry-After": str(retry_after)},
        )


def record_failure_and_enforce(
    limiter: InMemoryRateLimiter,
    key: str,
    limit: int,
    window_seconds: int,
    detail: str,
) -> None:
    """Record a failed attempt, then raise HTTP 429 if now rate-limited."""
    limiter.add_failure(key, window_seconds)
    enforce_rate_limit(limiter, key, limit, window_seconds, detail)
