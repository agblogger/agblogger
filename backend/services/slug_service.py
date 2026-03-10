"""Slug generation for post URLs and directory paths."""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

MAX_SLUG_LENGTH = 80
_UNTITLED_FALLBACK = "untitled"
_UNTITLED_COLLISION_SLUG = "untitled-post"
_MAX_SLUG_COLLISION = 1000


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


def generate_post_path(title: str, posts_dir: Path) -> Path:
    """Generate a unique post directory path.

    Creates a path of the form: posts_dir / YYYY-MM-DD-{slug} / index.md
    If the directory already exists, appends -2, -3, etc.
    """
    slug = generate_post_slug(title)
    today = date.today().isoformat()
    base_name = f"{today}-{slug}"

    dir_path = posts_dir / base_name
    if not dir_path.exists():
        return dir_path / "index.md"

    counter = 2
    while counter <= _MAX_SLUG_COLLISION:
        candidate = posts_dir / f"{base_name}-{counter}"
        if not candidate.exists():
            return candidate / "index.md"
        counter += 1
    raise ValueError(f"Too many slug collisions for '{base_name}' (>{_MAX_SLUG_COLLISION})")
