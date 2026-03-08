from __future__ import annotations

from contextlib import suppress
from functools import lru_cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path


@lru_cache(maxsize=1)
def get_version() -> str:
    """Return the application version (cached for process lifetime)."""
    version_path = Path(__file__).resolve().parents[1] / "VERSION"
    if version_path.exists():
        return version_path.read_text(encoding="utf-8").strip()

    for dist_name in ("agblogger-server", "agblogger"):
        with suppress(PackageNotFoundError):
            return package_version(dist_name)

    raise RuntimeError("Could not determine AgBlogger version")
