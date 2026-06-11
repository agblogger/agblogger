"""Shared sync path validation rules for the CLI."""

from __future__ import annotations

_SYNC_ALLOWED_TOP_LEVEL_FILES = frozenset({"index.toml", "labels.toml"})


def _is_directory_post_path(file_path: str) -> bool:
    normalized = file_path.strip().strip("/")
    if not normalized.startswith("posts/") or not normalized.endswith("/index.md"):
        return False
    parts = normalized.split("/")
    return len(parts) >= 3


def is_sync_managed_path(file_path: str) -> bool:
    """Return True when the path belongs to the managed sync surface."""
    normalized = file_path.strip().lstrip("/")
    if not normalized:
        return False

    parts = [part for part in normalized.split("/") if part]
    if not parts:
        return False
    if any(part in {".", ".."} or part.startswith(".") for part in parts):
        return False

    if normalized in _SYNC_ALLOWED_TOP_LEVEL_FILES:
        return True
    if len(parts) == 1 and normalized.endswith(".md"):
        return True
    if normalized.startswith("assets/"):
        return True
    if normalized.startswith("posts/"):
        if normalized.endswith(".md"):
            return _is_directory_post_path(normalized)
        return True
    return False
