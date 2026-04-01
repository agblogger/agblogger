"""Shared GoatCounter host normalization helpers."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_DOMAIN_RE = re.compile(
    r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?"
    r"(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)+$"
)


def _is_ipv4_like(host: str) -> bool:
    """Return True when the string looks like a dotted-decimal IPv4 address."""
    parts = host.split(".")
    return len(parts) == 4 and all(part.isdigit() for part in parts)


def normalize_goatcounter_site_host(raw: str) -> str | None:
    """Return a bare domain suitable for GoatCounter site provisioning and lookup."""
    candidate = raw.strip().lower()
    if not candidate:
        return None

    if "://" in candidate:
        parsed = urlsplit(candidate)
        if parsed.hostname is None:
            return None
        candidate = parsed.hostname.lower()
    else:
        candidate = candidate.split("/", 1)[0]
        if candidate.count(":") == 1:
            host, port = candidate.rsplit(":", 1)
            if port.isdigit():
                candidate = host

    candidate = candidate.rstrip(".")
    if not candidate or candidate.startswith("*."):
        return None
    if _is_ipv4_like(candidate) or _DOMAIN_RE.match(candidate) is None:
        return None
    return candidate
