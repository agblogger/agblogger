"""Version resolution for the AgBlogger CLI."""

from __future__ import annotations

import sys
from functools import lru_cache
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


@lru_cache(maxsize=1)
def get_cli_version() -> str:
    """Return the CLI version string, cached for process lifetime."""
    base = _base_dir()
    try:
        version = (base / "VERSION").read_text(encoding="utf-8").strip()
    except OSError, UnicodeDecodeError:
        return "unknown"
    build_path = base / "BUILD"
    if build_path.exists():
        try:
            commit = build_path.read_text(encoding="utf-8").strip()
        except OSError, UnicodeDecodeError:
            return version
        if commit:
            return f"{version}+{commit}"
    return version
