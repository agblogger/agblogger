"""Persistent credential storage for the agblogger CLI."""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path
from typing import TypedDict

import httpx
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
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError, UnicodeDecodeError, OSError:
        return {}
    if not isinstance(raw, dict):
        return {}
    result: dict[str, StoredCredentials] = {}
    for k, v in raw.items():
        if (
            isinstance(k, str)
            and isinstance(v, dict)
            and isinstance(v.get("username"), str)
            and isinstance(v.get("refresh_token"), str)
        ):
            result[k] = StoredCredentials(username=v["username"], refresh_token=v["refresh_token"])
    return result


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
    if server_url not in data:
        return
    del data[server_url]
    _save_all(data)


def revoke_session(server_url: str, refresh_token: str) -> None:
    """Revoke a refresh token server-side. Prints a warning on failure."""
    try:
        with httpx.Client(base_url=server_url, timeout=10.0) as client:
            resp = client.post(
                "/api/auth/logout",
                json={"refresh_token": refresh_token},
            )
            resp.raise_for_status()
    except (httpx.HTTPError, OSError) as exc:
        print(f"Warning: failed to revoke session: {exc}", file=sys.stderr)
