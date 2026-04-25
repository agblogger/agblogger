"""Shared request-size limits and format whitelists for multipart upload endpoints.

The favicon and site-image upload endpoints, the public-serve routes in
``backend.main``, and the frontend admin UI all need to agree on which extensions
are valid for each asset kind. Define each whitelist once here and derive the
lookup maps used elsewhere.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

MAX_MULTIPART_BODY_SIZE = 55 * 1024 * 1024
MAX_SYNC_MULTIPART_BODY_SIZE = 100 * 1024 * 1024
MAX_FAVICON_SIZE = 2 * 1024 * 1024
MAX_IMAGE_SIZE = 5 * 1024 * 1024


# Extension → MIME type. Extensions are the canonical disk form ("image/jpeg" maps
# to ".jpg", not ".jpeg"). Read-only views are exposed to discourage callers from
# mutating the shared maps.
FAVICON_FORMATS: Mapping[str, str] = MappingProxyType(
    {
        ".png": "image/png",
        ".ico": "image/x-icon",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
    }
)
SITE_IMAGE_FORMATS: Mapping[str, str] = MappingProxyType(
    {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
)


def _invert(formats: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType({mime: ext for ext, mime in formats.items()})


# MIME → extension, for validating multipart-upload Content-Type headers.
FAVICON_CONTENT_TYPE_TO_EXT: Mapping[str, str] = _invert(FAVICON_FORMATS)
SITE_IMAGE_CONTENT_TYPE_TO_EXT: Mapping[str, str] = _invert(SITE_IMAGE_FORMATS)


def get_multipart_body_limit(path: str) -> int | None:
    """Return the configured multipart body-size limit for a request path."""
    if path == "/api/posts/upload" or path.endswith("/assets"):
        return MAX_MULTIPART_BODY_SIZE
    if path == "/api/sync/commit":
        return MAX_SYNC_MULTIPART_BODY_SIZE
    if path == "/api/admin/favicon":
        return MAX_FAVICON_SIZE
    if path == "/api/admin/image":
        return MAX_IMAGE_SIZE
    return None
