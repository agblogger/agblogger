from __future__ import annotations

from contextlib import suppress
from functools import lru_cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path


def _resolve_version(base_dir: Path) -> str:
    """Build version string from VERSION and optional BUILD file under *base_dir*."""
    version = (base_dir / "VERSION").read_text(encoding="utf-8").strip()
    build_path = base_dir / "BUILD"
    if build_path.exists():
        try:
            commit = build_path.read_text(encoding="utf-8").strip()
        except OSError, UnicodeDecodeError:
            return version
        if commit:
            return f"{version}+{commit}"
    return version


@lru_cache(maxsize=1)
def get_version() -> str:
    """Return the application version (cached for process lifetime)."""
    repo_root = Path(__file__).resolve().parents[1]
    if (repo_root / "VERSION").exists():
        return _resolve_version(repo_root)

    for dist_name in ("agblogger-server", "agblogger"):
        with suppress(PackageNotFoundError):
            return package_version(dist_name)

    raise RuntimeError("Could not determine AgBlogger version")
