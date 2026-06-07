"""Persistent credential storage for the agblogger CLI."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import TypedDict

from platformdirs import user_config_dir

_APP_NAME = "agblogger"


class StoredCredentials(TypedDict):
    username: str
    refresh_token: str


def _credentials_path() -> Path:
    return Path(user_config_dir(_APP_NAME)) / "credentials.json"


def _load_all() -> dict[str, StoredCredentials]:
    path = _credentials_path()
    if not path.exists():
        return {}
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        data: dict[str, StoredCredentials] = raw
        return data
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return {}


def _save_all(data: dict[str, StoredCredentials]) -> None:
    path = _credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    with contextlib.suppress(OSError):
        path.chmod(0o600)


def load_credentials(server_url: str) -> StoredCredentials | None:
    """Return stored credentials for server_url, or None if not found."""
    return _load_all().get(server_url)


def save_credentials(server_url: str, username: str, refresh_token: str) -> None:
    """Persist credentials for server_url, creating or overwriting the entry."""
    data = _load_all()
    data[server_url] = StoredCredentials(username=username, refresh_token=refresh_token)
    _save_all(data)


def delete_credentials(server_url: str) -> None:
    """Remove stored credentials for server_url. No-op if not present."""
    data = _load_all()
    data.pop(server_url, None)
    _save_all(data)
