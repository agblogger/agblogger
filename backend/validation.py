"""Shared validation utilities used by both the backend and CLI."""

from __future__ import annotations


def is_valid_trusted_host(host: str) -> bool:
    """Return True for explicit hosts and narrow subdomain wildcards."""
    candidate = host.strip()
    if not candidate or candidate == "*":
        return False
    if "*" not in candidate:
        return True
    return candidate.startswith("*.") and candidate.count("*") == 1 and len(candidate) > 2
