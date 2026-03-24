"""Slug utility functions for canonical directory-backed post paths."""

from __future__ import annotations

from typing import NewType

CanonicalPostPath = NewType("CanonicalPostPath", str)
"""A validated canonical directory-backed post path (``posts/<slug>/index.md``)."""


def validated_post_path(raw: str) -> CanonicalPostPath:
    """Validate and normalize *raw* into a ``CanonicalPostPath``.

    Raises ``ValueError`` if *raw* is not a canonical directory-backed post path.
    Leading slashes and surrounding whitespace are stripped during normalization.
    """
    normalized = raw.strip().strip("/")
    if not is_directory_post_path(normalized):
        msg = f"Not a canonical post path: {raw}"
        raise ValueError(msg)
    return CanonicalPostPath(normalized)


def is_directory_post_path(file_path: str) -> bool:
    """Return True when a path is a canonical directory-backed post path.

    A canonical directory-backed post path has the form ``posts/<slug>/index.md``
    where ``<slug>`` is at least one path segment. Leading slashes and surrounding
    whitespace are stripped before evaluation.

    Accepted examples::

        posts/hello/index.md          → True
        posts/2026/recap/index.md     → True   (nested slug directories)
        /posts/hello/index.md         → True   (leading slash stripped)

    Rejected examples::

        posts/hello.md                → False  (flat file, not directory-backed)
        posts/hello/                  → False  (trailing slash, no index.md)
        hello/index.md                → False  (missing posts/ prefix)
        posts/index.md                → False  (no slug directory between posts/ and index.md)
    """
    normalized = file_path.strip().strip("/")
    if not normalized.startswith("posts/") or not normalized.endswith("/index.md"):
        return False

    parts = normalized.split("/")
    return len(parts) >= 3


def file_path_to_slug(file_path: str) -> str:
    """Convert a canonical post file path like ``posts/my-post/index.md`` to ``my-post``.

    If the input starts with ``posts/``, it must be a valid directory-backed path
    (i.e. ``posts/<slug>/index.md``); otherwise a ``ValueError`` is raised.

    Inputs that do **not** start with ``posts/`` are assumed to already be bare
    slugs and are returned unchanged. This allows callers to pass either a raw
    filesystem path or an already-extracted slug without branching.

    Examples::

        file_path_to_slug("posts/my-post/index.md")  → "my-post"
        file_path_to_slug("my-post")                 → "my-post"   (bare slug, pass-through)
        file_path_to_slug("posts/my-post.md")        → ValueError  (flat file rejected)
        file_path_to_slug("posts/my-post/")          → ValueError  (no index.md)
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
