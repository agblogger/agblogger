"""Slug generation for post URLs and directory paths."""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

MAX_SLUG_LENGTH = 80
_UNTITLED_FALLBACK = "untitled"
_UNTITLED_COLLISION_SLUG = "untitled-post"
_MAX_SLUG_COLLISION = 1000
_DATE_PREFIX_RE = re.compile(r"^(?P<prefix>\d{4}-\d{2}-\d{2}-)")


def generate_post_slug(title: str) -> str:
    """Generate a URL-safe slug from a post title.

    - Normalize unicode to ASCII (NFKD)
    - Lowercase, strip
    - Replace non-alphanumeric chars with hyphens
    - Collapse multiple hyphens
    - Strip leading/trailing hyphens
    - Truncate to 80 chars (don't cut mid-word if possible)
    - Return "untitled" for empty/whitespace-only input
    - Avoid colliding with the reserved fallback slug for real titles
    """
    # Normalize unicode to decomposed form, then drop non-ASCII
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    # Lowercase and strip
    text = text.lower().strip()
    # Replace non-alphanumeric chars with hyphens
    text = re.sub(r"[^a-z0-9]+", "-", text)
    # Strip leading/trailing hyphens
    text = text.strip("-")

    if not text:
        return _UNTITLED_FALLBACK

    if text == _UNTITLED_FALLBACK:
        text = _UNTITLED_COLLISION_SLUG

    # Truncate to MAX_SLUG_LENGTH without cutting mid-word
    if len(text) > MAX_SLUG_LENGTH:
        truncated = text[:MAX_SLUG_LENGTH]
        # Try to break at a word boundary, but only if the break point
        # is in the latter half — otherwise just hard-truncate
        last_hyphen = truncated.rfind("-")
        if last_hyphen > MAX_SLUG_LENGTH // 2:
            truncated = truncated[:last_hyphen]
        text = truncated.rstrip("-")

    return text


def generate_post_path(
    title: str,
    posts_dir: Path,
    current_dir: Path | None = None,
    slug_prefix: str = "",
) -> Path:
    """Generate a unique post directory path.

    Creates a path of the form: posts_dir / {slug} / index.md.
    If the directory already exists, appends -2, -3, etc.

    When *current_dir* is provided, that directory is treated as reusable so
    callers can resolve the canonical path for an existing post without
    spuriously colliding with its current location.
    """
    slug = f"{slug_prefix}{generate_post_slug(title)}"
    return _resolve_unique_post_path(slug, posts_dir, current_dir=current_dir)


def date_slug_prefix(directory_name: str) -> str:
    """Return the leading ``YYYY-MM-DD-`` prefix from an existing post directory."""
    match = _DATE_PREFIX_RE.match(directory_name)
    if match is None:
        return ""
    return match.group("prefix")


def _resolve_unique_post_path(
    slug: str,
    posts_dir: Path,
    current_dir: Path | None = None,
) -> Path:
    """Resolve a unique canonical post path for *slug* within *posts_dir*.

    When *current_dir* is provided, that directory is treated as reusable so
    callers can ask for the canonical path of an existing post without forcing
    a spurious collision suffix.
    """
    dir_path = posts_dir / slug
    if _is_available_directory(dir_path, current_dir):
        return dir_path / "index.md"

    counter = 2
    while counter <= _MAX_SLUG_COLLISION:
        candidate = posts_dir / f"{slug}-{counter}"
        if _is_available_directory(candidate, current_dir):
            return candidate / "index.md"
        counter += 1
    raise ValueError(f"Too many slug collisions for '{slug}' (>{_MAX_SLUG_COLLISION})")


def _is_available_directory(candidate: Path, current_dir: Path | None) -> bool:
    """Return True when *candidate* can be used as the canonical post directory."""
    return candidate == current_dir or not candidate.exists()
