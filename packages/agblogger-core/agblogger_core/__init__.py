"""Shared post-filesystem path and slug utilities for AgBlogger.

Single source of truth for the canonical post-path rules and the sync-managed
path surface, imported by both the server (``backend``) and the standalone sync
CLI (``agblogger_cli``). Pure functions, no third-party dependencies.
"""

from __future__ import annotations

from agblogger_core.slug import (
    CanonicalPostPath,
    file_path_to_slug,
    is_directory_post_path,
    resolve_slug_candidates,
    validated_post_path,
)
from agblogger_core.sync_paths import is_sync_managed_path

__all__ = [
    "CanonicalPostPath",
    "file_path_to_slug",
    "is_directory_post_path",
    "is_sync_managed_path",
    "resolve_slug_candidates",
    "validated_post_path",
]
