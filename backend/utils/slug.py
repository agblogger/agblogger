"""Slug utility functions for converting between file paths and URL slugs."""

from __future__ import annotations


def file_path_to_slug(file_path: str) -> str:
    """Convert a file_path like 'posts/my-post/index.md' to a URL slug 'my-post'.

    Handles: posts/ prefix, /index.md suffix (directory-backed), .md suffix (flat-file).
    Idempotent: already-extracted slugs pass through unchanged.
    """
    slug = file_path
    if slug.startswith("posts/"):
        slug = slug.removeprefix("posts/")
    # Strip trailing slash (e.g. "posts/my-post/" -> "my-post")
    slug = slug.rstrip("/")
    # Strip /index.md for directory-backed posts (e.g. "my-post/index.md" -> "my-post")
    if slug.endswith("/index.md"):
        slug = slug.removesuffix("/index.md")
    # Strip .md for flat-file posts (e.g. "hello.md" -> "hello")
    elif slug.endswith(".md"):
        slug = slug.removesuffix(".md")
    return slug


def resolve_slug_candidates(slug: str) -> tuple[str, ...]:
    """Return candidate file paths for a bare slug.

    Returns ('posts/{slug}/index.md', 'posts/{slug}.md') for slug resolution.
    """
    return (f"posts/{slug}/index.md", f"posts/{slug}.md")
