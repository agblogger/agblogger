"""Shared request-size limits for multipart upload endpoints."""

from __future__ import annotations

MAX_MULTIPART_BODY_SIZE = 55 * 1024 * 1024
MAX_SYNC_MULTIPART_BODY_SIZE = 100 * 1024 * 1024
MAX_FAVICON_SIZE = 2 * 1024 * 1024


def get_multipart_body_limit(path: str) -> int | None:
    """Return the configured multipart body-size limit for a request path."""
    if path == "/api/posts/upload" or path.endswith("/assets"):
        return MAX_MULTIPART_BODY_SIZE
    if path == "/api/sync/commit":
        return MAX_SYNC_MULTIPART_BODY_SIZE
    if path == "/api/admin/favicon":
        return MAX_FAVICON_SIZE
    return None
