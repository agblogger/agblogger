"""Slug utility functions for canonical directory-backed post paths."""

from __future__ import annotations


def is_directory_post_path(file_path: str) -> bool:
    """Return True when a path is a canonical directory-backed post path."""
    normalized = file_path.strip().strip("/")
    if not normalized.startswith("posts/") or not normalized.endswith("/index.md"):
        return False

    parts = normalized.split("/")
    return len(parts) >= 3 and parts[-1] == "index.md"


def file_path_to_slug(file_path: str) -> str:
    """Convert a canonical post file path like ``posts/my-post/index.md`` to ``my-post``.

    Already-extracted slugs pass through unchanged. Non-canonical legacy post
    paths are rejected so callers cannot quietly rebuild removed flat-file URLs.
    """
    normalized = file_path.strip().strip("/")
    if normalized.startswith("posts/"):
        if not is_directory_post_path(normalized):
            msg = f"Unsupported post path: {file_path}"
            raise ValueError(msg)
        return normalized.removeprefix("posts/").removesuffix("/index.md")
    return normalized


def resolve_slug_candidates(slug: str) -> tuple[str, ...]:
    """Return candidate file paths for a bare slug.

    Bare slugs resolve only to the canonical directory-backed layout.
    """
    return (f"posts/{slug}/index.md",)
