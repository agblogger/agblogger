"""Version resolution for the AgBlogger CLI."""

from __future__ import annotations

import sys
from functools import lru_cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path


def _base_dir() -> Path:
    """Return the directory containing VERSION and BUILD files.

    In a PyInstaller bundle, data files are extracted to ``sys._MEIPASS``.
    Otherwise, resolve relative to this file (cli/ -> repo root).
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        return Path(meipass)
    return Path(__file__).resolve().parents[1]


def _installed_package_version() -> str | None:
    """Return the installed agblogger package version, if available."""
    try:
        return package_version("agblogger")
    except PackageNotFoundError:
        return None


@lru_cache(maxsize=1)
def get_cli_version() -> str:
    """Return the CLI version string, cached for process lifetime."""
    base = _base_dir()
    try:
        version = (base / "VERSION").read_text(encoding="utf-8").strip()
    except OSError, UnicodeDecodeError:
        return _installed_package_version() or "unknown"
    build_path = base / "BUILD"
    if build_path.exists():
        try:
            commit = build_path.read_text(encoding="utf-8").strip()
        except OSError, UnicodeDecodeError:
            return version
        if commit:
            return f"{version}+{commit}"
    return version
