# CLI Persistent Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate repeated password prompts in the agblogger sync CLI by storing session refresh tokens locally and reusing them across runs.

**Architecture:** A new `credentials.py` module in `agblogger_cli` owns credential file I/O (load/save/delete/revoke), keyed by server URL, stored in `platformdirs.user_config_dir("agblogger")/credentials.json` at `0o600`. `SyncClient` gains `restore_session()` and loses its auto-revoke `logout()`. `main()` gains `login`/`logout` subcommands and a `_authenticate()` helper that tries stored credentials first, falls back to full login on failure.

**Tech Stack:** Python, httpx, platformdirs (new dependency)

---

## File Map

| Action | Path | Purpose |
|--------|------|---------|
| Create | `agblogger_cli/agblogger_cli/credentials.py` | Credential file I/O + revoke HTTP call |
| Modify | `agblogger_cli/pyproject.toml` | Add `platformdirs>=4.0` dependency |
| Modify | `agblogger_cli/agblogger_cli/sync_client.py` | Remove `logout()`/`token` param; add `restore_session()`; make `login_interactive()` return `str`; add `_authenticate()`; add `login`/`logout` subcommands |
| Create | `tests/test_cli/test_credentials.py` | Unit tests for credentials module |
| Modify | `tests/test_cli/test_sync_client.py` | Remove logout tests; add `restore_session` tests |
| Modify | `tests/test_cli/test_sync_client_ux.py` | Update mocks (`login_interactive` return value); add login/logout command tests; add stored-credentials and fallback tests |

---

## Task 1: Add platformdirs dependency

**Files:**
- Modify: `agblogger_cli/pyproject.toml`

- [ ] **Step 1: Add platformdirs to dependencies**

Edit `agblogger_cli/pyproject.toml` — add `"platformdirs>=4.0"` to the `dependencies` list:

```toml
dependencies = [
    "httpx>=0.28",
    "httpcore>=1.0,<2",
    "platformdirs>=4.0",
]
```

- [ ] **Step 2: Sync the lockfile**

```bash
uv sync
```

Expected: resolves without error, `platformdirs` appears in the installed packages.

- [ ] **Step 3: Verify import works**

```bash
uv run python -c "from platformdirs import user_config_dir; print(user_config_dir('agblogger'))"
```

Expected: prints a path like `/home/user/.config/agblogger` or equivalent for the platform.

- [ ] **Step 4: Commit**

```bash
git add agblogger_cli/pyproject.toml uv.lock
git commit -m "feat: add platformdirs dependency to agblogger-cli"
```

---

## Task 2: Create credentials.py — load, save, delete

**Files:**
- Create: `agblogger_cli/agblogger_cli/credentials.py`
- Create: `tests/test_cli/test_credentials.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_cli/test_credentials.py`:

```python
"""Tests for CLI credential storage."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from agblogger_cli.credentials import delete_credentials, load_credentials, save_credentials


class TestLoadCredentials:
    def test_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        with patch("agblogger_cli.credentials._credentials_path", return_value=tmp_path / "credentials.json"):
            result = load_credentials("https://blog.example.com")
        assert result is None

    def test_returns_none_for_unknown_server(self, tmp_path: Path) -> None:
        creds_path = tmp_path / "credentials.json"
        creds_path.write_text(json.dumps({"https://other.example.com": {"username": "admin", "refresh_token": "tok"}}))
        with patch("agblogger_cli.credentials._credentials_path", return_value=creds_path):
            result = load_credentials("https://blog.example.com")
        assert result is None

    def test_returns_credentials_for_known_server(self, tmp_path: Path) -> None:
        creds_path = tmp_path / "credentials.json"
        creds_path.write_text(json.dumps({"https://blog.example.com": {"username": "admin", "refresh_token": "mytoken"}}))
        with patch("agblogger_cli.credentials._credentials_path", return_value=creds_path):
            result = load_credentials("https://blog.example.com")
        assert result is not None
        assert result["username"] == "admin"
        assert result["refresh_token"] == "mytoken"

    def test_returns_none_on_malformed_json(self, tmp_path: Path) -> None:
        creds_path = tmp_path / "credentials.json"
        creds_path.write_text("not-json{{{")
        with patch("agblogger_cli.credentials._credentials_path", return_value=creds_path):
            result = load_credentials("https://blog.example.com")
        assert result is None


class TestSaveCredentials:
    def test_round_trip(self, tmp_path: Path) -> None:
        creds_path = tmp_path / "credentials.json"
        with patch("agblogger_cli.credentials._credentials_path", return_value=creds_path):
            save_credentials("https://blog.example.com", "admin", "mytoken")
            result = load_credentials("https://blog.example.com")
        assert result is not None
        assert result["username"] == "admin"
        assert result["refresh_token"] == "mytoken"

    def test_sets_restrictive_permissions(self, tmp_path: Path) -> None:
        creds_path = tmp_path / "credentials.json"
        with patch("agblogger_cli.credentials._credentials_path", return_value=creds_path):
            save_credentials("https://blog.example.com", "admin", "mytoken")
        mode = stat.S_IMODE(creds_path.stat().st_mode)
        assert mode == 0o600

    def test_multiple_servers_coexist(self, tmp_path: Path) -> None:
        creds_path = tmp_path / "credentials.json"
        with patch("agblogger_cli.credentials._credentials_path", return_value=creds_path):
            save_credentials("https://blog1.example.com", "admin", "token1")
            save_credentials("https://blog2.example.com", "admin", "token2")
            r1 = load_credentials("https://blog1.example.com")
            r2 = load_credentials("https://blog2.example.com")
        assert r1 is not None and r1["refresh_token"] == "token1"
        assert r2 is not None and r2["refresh_token"] == "token2"

    def test_overwrites_existing_entry(self, tmp_path: Path) -> None:
        creds_path = tmp_path / "credentials.json"
        with patch("agblogger_cli.credentials._credentials_path", return_value=creds_path):
            save_credentials("https://blog.example.com", "admin", "old-token")
            save_credentials("https://blog.example.com", "admin", "new-token")
            result = load_credentials("https://blog.example.com")
        assert result is not None
        assert result["refresh_token"] == "new-token"


class TestDeleteCredentials:
    def test_removes_entry(self, tmp_path: Path) -> None:
        creds_path = tmp_path / "credentials.json"
        with patch("agblogger_cli.credentials._credentials_path", return_value=creds_path):
            save_credentials("https://blog.example.com", "admin", "mytoken")
            delete_credentials("https://blog.example.com")
            result = load_credentials("https://blog.example.com")
        assert result is None

    def test_leaves_other_servers_intact(self, tmp_path: Path) -> None:
        creds_path = tmp_path / "credentials.json"
        with patch("agblogger_cli.credentials._credentials_path", return_value=creds_path):
            save_credentials("https://blog1.example.com", "admin", "token1")
            save_credentials("https://blog2.example.com", "admin", "token2")
            delete_credentials("https://blog1.example.com")
            result = load_credentials("https://blog2.example.com")
        assert result is not None
        assert result["refresh_token"] == "token2"

    def test_no_error_when_server_not_present(self, tmp_path: Path) -> None:
        creds_path = tmp_path / "credentials.json"
        with patch("agblogger_cli.credentials._credentials_path", return_value=creds_path):
            delete_credentials("https://blog.example.com")  # should not raise
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_cli/test_credentials.py -v
```

Expected: `ModuleNotFoundError: No module named 'agblogger_cli.credentials'`

- [ ] **Step 3: Create credentials.py**

Create `agblogger_cli/agblogger_cli/credentials.py`:

```python
"""Persistent credential storage for the agblogger CLI."""

from __future__ import annotations

import json
import os
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
        data: dict[str, StoredCredentials] = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return data
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return {}


def _save_all(data: dict[str, StoredCredentials]) -> None:
    path = _credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_cli/test_credentials.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agblogger_cli/agblogger_cli/credentials.py tests/test_cli/test_credentials.py
git commit -m "feat: add credential storage module for CLI persistent auth"
```

---

## Task 3: Add revoke_session to credentials.py

**Files:**
- Modify: `agblogger_cli/agblogger_cli/credentials.py`
- Modify: `tests/test_cli/test_credentials.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_cli/test_credentials.py`:

```python
import httpx
from unittest.mock import MagicMock, patch
from agblogger_cli.credentials import revoke_session


class TestRevokeSession:
    def test_posts_refresh_token_to_logout_endpoint(self) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        with patch("agblogger_cli.credentials.httpx") as mock_httpx:
            mock_client = MagicMock()
            mock_httpx.Client.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_httpx.Client.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_response
            revoke_session("https://blog.example.com", "mytoken")
        mock_client.post.assert_called_once_with(
            "/api/auth/logout",
            json={"refresh_token": "mytoken"},
        )

    def test_prints_warning_on_http_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("agblogger_cli.credentials.httpx") as mock_httpx:
            mock_client = MagicMock()
            mock_httpx.Client.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_httpx.Client.return_value.__exit__ = MagicMock(return_value=False)
            mock_httpx.HTTPError = httpx.HTTPError
            request = httpx.Request("POST", "https://blog.example.com/api/auth/logout")
            mock_client.post.side_effect = httpx.HTTPStatusError(
                "server error",
                request=request,
                response=httpx.Response(status_code=500, request=request),
            )
            revoke_session("https://blog.example.com", "mytoken")
        captured = capsys.readouterr()
        assert "Warning" in captured.err
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
uv run pytest tests/test_cli/test_credentials.py::TestRevokeSession -v
```

Expected: `ImportError: cannot import name 'revoke_session'`

- [ ] **Step 3: Implement revoke_session**

Add to `agblogger_cli/agblogger_cli/credentials.py`:

```python
import sys

import httpx


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
```

Also add `import sys` and `import httpx` at the top of the file (if not already there).

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_cli/test_credentials.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agblogger_cli/agblogger_cli/credentials.py tests/test_cli/test_credentials.py
git commit -m "feat: add revoke_session to credentials module"
```

---

## Task 4: Refactor SyncClient — remove logout(), remove token param, simplify close()

**Files:**
- Modify: `agblogger_cli/agblogger_cli/sync_client.py`
- Modify: `tests/test_cli/test_sync_client.py`

- [ ] **Step 1: Update tests — remove logout tests, add close() test**

In `tests/test_cli/test_sync_client.py`, find `class TestSyncClientLogin` and replace the two logout tests with:

```python
def test_close_does_not_revoke_session(self, tmp_path: Path) -> None:
    content_dir = tmp_path / "content"
    content_dir.mkdir()

    client = SyncClient.__new__(SyncClient)
    client.content_dir = content_dir
    client.server_url = "http://localhost:8000"
    client._csrf_token = "cli-csrf"
    client.client = MagicMock()

    client.close()

    client.client.post.assert_not_called()
    client.client.close.assert_called_once_with()
```

- [ ] **Step 2: Run updated test to confirm it fails**

```bash
uv run pytest tests/test_cli/test_sync_client.py::TestSyncClientLogin::test_close_does_not_revoke_session -v
```

Expected: FAIL (because `close()` currently calls `logout()` which calls `post`).

- [ ] **Step 3: Refactor SyncClient.__init__ and close()**

In `agblogger_cli/agblogger_cli/sync_client.py`:

Replace `__init__`:
```python
def __init__(self, server_url: str, content_dir: Path) -> None:
    self.server_url = server_url.rstrip("/")
    self.content_dir = content_dir
    self.client = httpx.Client(
        base_url=self.server_url,
        timeout=60.0,
    )
    self._csrf_token: str | None = None
```

Replace `close()`:
```python
def close(self) -> None:
    """Close the HTTP client."""
    self.client.close()
```

Delete the entire `logout()` method.

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_cli/test_sync_client.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Fix any test_sync_client_ux.py failures from token param removal**

The UX tests construct `SyncClient(server_url, content_dir)` — the `token` param removal may not affect them since they likely don't pass a token. Check:

```bash
uv run pytest tests/test_cli/test_sync_client_ux.py -v
```

If any tests fail with `unexpected keyword argument 'token'`, remove the `token=...` argument from those test calls.

- [ ] **Step 6: Commit**

```bash
git add agblogger_cli/agblogger_cli/sync_client.py tests/test_cli/test_sync_client.py
git commit -m "refactor: remove SyncClient logout and bearer token param"
```

---

## Task 5: Add restore_session() to SyncClient

**Files:**
- Modify: `agblogger_cli/agblogger_cli/sync_client.py`
- Modify: `tests/test_cli/test_sync_client.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_cli/test_sync_client.py` in `class TestSyncClientLogin`:

```python
def test_restore_session_returns_true_on_success(self, tmp_path: Path) -> None:
    content_dir = tmp_path / "content"
    content_dir.mkdir()

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"csrf_token": "new-csrf"}

    client = SyncClient.__new__(SyncClient)
    client.content_dir = content_dir
    client.server_url = "http://localhost:8000"
    client._csrf_token = None
    client.client = MagicMock()
    client.client.post.return_value = response

    result = client.restore_session("stored-refresh-token")

    assert result is True
    assert client._csrf_token == "new-csrf"
    client.client.post.assert_called_once_with(
        "/api/auth/refresh",
        json={"refresh_token": "stored-refresh-token"},
    )

def test_restore_session_returns_false_on_401(self, tmp_path: Path) -> None:
    content_dir = tmp_path / "content"
    content_dir.mkdir()

    response = MagicMock()
    response.status_code = 401

    client = SyncClient.__new__(SyncClient)
    client.content_dir = content_dir
    client.server_url = "http://localhost:8000"
    client._csrf_token = None
    client.client = MagicMock()
    client.client.post.return_value = response

    result = client.restore_session("expired-token")

    assert result is False
    assert client._csrf_token is None

def test_restore_session_returns_false_on_transport_error(self, tmp_path: Path) -> None:
    import httpx

    content_dir = tmp_path / "content"
    content_dir.mkdir()

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"csrf_token": "new-csrf"}

    client = SyncClient.__new__(SyncClient)
    client.content_dir = content_dir
    client.server_url = "http://localhost:8000"
    client._csrf_token = None
    client.client = MagicMock()
    client.client.post.side_effect = httpx.TransportError("connection failed")

    result = client.restore_session("some-token")

    assert result is False
    assert client._csrf_token is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_cli/test_sync_client.py::TestSyncClientLogin::test_restore_session_returns_true_on_success tests/test_cli/test_sync_client.py::TestSyncClientLogin::test_restore_session_returns_false_on_401 tests/test_cli/test_sync_client.py::TestSyncClientLogin::test_restore_session_rotated_token_readable_from_cookie_jar -v
```

Expected: `AttributeError: 'SyncClient' object has no attribute 'restore_session'`

- [ ] **Step 3: Implement restore_session()**

Add to `SyncClient` in `agblogger_cli/agblogger_cli/sync_client.py` (after `login()`):

```python
def restore_session(self, refresh_token: str) -> bool:
    """Restore a session from a stored refresh token.

    Sends refresh_token in the request body. On success, sets self._csrf_token
    and the server's rotated refresh token is available via
    self.client.cookies.get("refresh_token"). Returns False on failure.
    """
    try:
        resp = self._call(
            "POST",
            "/api/auth/refresh",
            json={"refresh_token": refresh_token},
        )
    except httpx.TransportError:
        return False
    if resp.status_code != 200:
        return False
    try:
        data = resp.json()
    except ValueError:
        return False
    csrf_token = data.get("csrf_token")
    if not isinstance(csrf_token, str) or not csrf_token:
        return False
    self._csrf_token = csrf_token
    return True
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_cli/test_sync_client.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agblogger_cli/agblogger_cli/sync_client.py tests/test_cli/test_sync_client.py
git commit -m "feat: add restore_session() to SyncClient"
```

---

## Task 6: Add login and logout subcommands

**Files:**
- Modify: `agblogger_cli/agblogger_cli/sync_client.py`
- Modify: `tests/test_cli/test_sync_client_ux.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_cli/test_sync_client_ux.py`:

```python
from agblogger_cli.credentials import StoredCredentials


class TestLoginCommand:
    def test_login_command_saves_credentials(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / ".agblogger.json").write_text(
            '{"server": "http://localhost:8000"}'
        )

        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.client.cookies.get.return_value = "new-refresh-token"

        monkeypatch.setattr(
            "sys.argv", ["agblogger", "--dir", str(content_dir), "login", "--username", "admin"]
        )
        with (
            patch("agblogger_cli.sync_client.SyncClient", return_value=mock_client_instance),
            patch("agblogger_cli.sync_client.getpass.getpass", return_value="secret"),
            patch("agblogger_cli.sync_client.save_credentials") as mock_save,
        ):
            from agblogger_cli.sync_client import main
            main()

        mock_save.assert_called_once_with("http://localhost:8000", "admin", "new-refresh-token")

    def test_login_command_exits_on_invalid_credentials(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import httpx
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / ".agblogger.json").write_text(
            '{"server": "http://localhost:8000"}'
        )

        request = httpx.Request("POST", "http://localhost:8000/api/auth/login")
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.login.side_effect = httpx.HTTPStatusError(
            "unauthorized",
            request=request,
            response=httpx.Response(status_code=401, request=request),
        )

        monkeypatch.setattr(
            "sys.argv", ["agblogger", "--dir", str(content_dir), "login", "--username", "admin"]
        )
        with (
            patch("agblogger_cli.sync_client.SyncClient", return_value=mock_client_instance),
            patch("agblogger_cli.sync_client.getpass.getpass", return_value="wrong"),
            pytest.raises(SystemExit) as exc_info,
        ):
            from agblogger_cli.sync_client import main
            main()

        assert exc_info.value.code == 1


class TestLogoutCommand:
    def test_logout_command_revokes_and_deletes_credentials(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / ".agblogger.json").write_text(
            '{"server": "http://localhost:8000"}'
        )

        stored: StoredCredentials = {"username": "admin", "refresh_token": "my-token"}

        monkeypatch.setattr("sys.argv", ["agblogger", "--dir", str(content_dir), "logout"])
        with (
            patch("agblogger_cli.sync_client.load_credentials", return_value=stored),
            patch("agblogger_cli.sync_client.revoke_session") as mock_revoke,
            patch("agblogger_cli.sync_client.delete_credentials") as mock_delete,
        ):
            from agblogger_cli.sync_client import main
            main()

        mock_revoke.assert_called_once_with("http://localhost:8000", "my-token")
        mock_delete.assert_called_once_with("http://localhost:8000")

    def test_logout_command_exits_cleanly_when_no_credentials(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / ".agblogger.json").write_text(
            '{"server": "http://localhost:8000"}'
        )

        monkeypatch.setattr("sys.argv", ["agblogger", "--dir", str(content_dir), "logout"])
        with patch("agblogger_cli.sync_client.load_credentials", return_value=None):
            from agblogger_cli.sync_client import main
            main()

        captured = capsys.readouterr()
        assert "No stored credentials" in captured.out
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_cli/test_sync_client_ux.py::TestLoginCommand tests/test_cli/test_sync_client_ux.py::TestLogoutCommand -v
```

Expected: errors about unknown `login`/`logout` subcommands or missing imports.

- [ ] **Step 3: Add imports and subcommands to sync_client.py**

At the top of `agblogger_cli/agblogger_cli/sync_client.py`, add imports:

```python
from agblogger_cli.credentials import (
    StoredCredentials,
    delete_credentials,
    load_credentials,
    revoke_session,
    save_credentials,
)
```

In `main()`, register the new subcommands after the existing ones:

```python
subparsers.add_parser("login", help="Save credentials for this server")
subparsers.add_parser("logout", help="Revoke and delete stored credentials")
```

In `main()`, add handlers before the "Load config" comment. The `login` and `logout` commands follow the same server-URL resolution as sync/status — they go in the normal config-loading path. Add after the server URL is resolved and validated:

```python
if args.command == "login":
    username = args.username or config.get("username")
    if not username:
        username = input("Username: ")
    password = getpass.getpass("Password: ")
    with SyncClient(server_url, content_dir) as client:
        try:
            client.login(username, password)
        except httpx.ConnectError:
            print(f"Error: Could not connect to server at {server_url}")
            sys.exit(1)
        except httpx.TimeoutException:
            print(f"Error: Connection to {server_url} timed out")
            sys.exit(1)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                print("Error: Invalid username or password")
                sys.exit(1)
            print(f"Error: Login failed (HTTP {exc.response.status_code})")
            sys.exit(1)
        refresh_token = client.client.cookies.get("refresh_token")
        if refresh_token:
            save_credentials(server_url, username, refresh_token)
            print(f"Logged in. Credentials saved for {server_url}")
        else:
            print("Warning: server did not return a refresh token; session will not persist.")
    return

if args.command == "logout":
    creds = load_credentials(server_url)
    if creds is None:
        print("No stored credentials for this server.")
        return
    revoke_session(server_url, creds["refresh_token"])
    delete_credentials(server_url)
    print(f"Logged out from {server_url}")
    return
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_cli/test_sync_client_ux.py::TestLoginCommand tests/test_cli/test_sync_client_ux.py::TestLogoutCommand -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run full CLI test suite to catch regressions**

```bash
uv run pytest tests/test_cli/test_sync_client.py tests/test_cli/test_sync_client_ux.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add agblogger_cli/agblogger_cli/sync_client.py tests/test_cli/test_sync_client_ux.py
git commit -m "feat: add agblogger login and logout subcommands"
```

---

## Task 7: Update session startup flow — use stored credentials for sync/status

**Files:**
- Modify: `agblogger_cli/agblogger_cli/sync_client.py`
- Modify: `tests/test_cli/test_sync_client_ux.py`

- [ ] **Step 1: Make login_interactive return the username**

In `agblogger_cli/agblogger_cli/sync_client.py`, update `login_interactive` signature and body:

```python
def login_interactive(
    client: SyncClient,
    *,
    cli_username: str | None,
    config_username: str | None,
) -> str:
    """Interactively authenticate and return the username used."""
    username = cli_username or config_username
    if not username:
        username = input("Username: ")
    password = getpass.getpass("Password: ")

    try:
        client.login(username, password)
    except httpx.ConnectError:
        print(f"Error: Could not connect to server at {client.server_url}")
        sys.exit(1)
    except httpx.TimeoutException:
        print(f"Error: Connection to {client.server_url} timed out")
        sys.exit(1)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401:
            print("Error: Invalid username or password")
            sys.exit(1)
        print(f"Error: Login failed (HTTP {exc.response.status_code})")
        sys.exit(1)
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(1)

    return username
```

- [ ] **Step 2: Add _authenticate() helper**

Add to `agblogger_cli/agblogger_cli/sync_client.py` (module-level function, after `login_interactive`):

```python
def _authenticate(
    client: SyncClient,
    server_url: str,
    cli_username: str | None,
    config_username: str | None,
) -> None:
    """Authenticate client using stored credentials if available, falling back to interactive login."""
    creds = load_credentials(server_url)

    if creds is not None and client.restore_session(creds["refresh_token"]):
        rotated = client.client.cookies.get("refresh_token")
        if rotated:
            save_credentials(server_url, creds["username"], rotated)
        return

    # Stored token missing or expired — fall back to interactive login
    fallback_username = cli_username or (creds["username"] if creds else None) or config_username
    used_username = login_interactive(
        client,
        cli_username=fallback_username,
        config_username=None,
    )
    refresh_token = client.client.cookies.get("refresh_token")
    if refresh_token:
        save_credentials(server_url, used_username, refresh_token)
```

- [ ] **Step 3: Write failing tests for _authenticate**

Add to `tests/test_cli/test_sync_client_ux.py`:

```python
from agblogger_cli.sync_client import _authenticate


class TestAuthenticate:
    def test_uses_stored_credentials_when_restore_succeeds(self, tmp_path: Path) -> None:
        stored: StoredCredentials = {"username": "admin", "refresh_token": "stored-token"}
        mock_client = MagicMock()
        mock_client.restore_session.return_value = True
        mock_client.client.cookies.get.return_value = "rotated-token"

        with (
            patch("agblogger_cli.sync_client.load_credentials", return_value=stored),
            patch("agblogger_cli.sync_client.save_credentials") as mock_save,
            patch("agblogger_cli.sync_client.login_interactive") as mock_login,
        ):
            _authenticate(mock_client, "https://blog.example.com", None, None)

        mock_client.restore_session.assert_called_once_with("stored-token")
        mock_save.assert_called_once_with("https://blog.example.com", "admin", "rotated-token")
        mock_login.assert_not_called()

    def test_falls_back_to_login_when_restore_fails(self, tmp_path: Path) -> None:
        stored: StoredCredentials = {"username": "admin", "refresh_token": "expired-token"}
        mock_client = MagicMock()
        mock_client.restore_session.return_value = False
        mock_client.client.cookies.get.return_value = "new-refresh-token"

        with (
            patch("agblogger_cli.sync_client.load_credentials", return_value=stored),
            patch("agblogger_cli.sync_client.login_interactive", return_value="admin") as mock_login,
            patch("agblogger_cli.sync_client.save_credentials") as mock_save,
        ):
            _authenticate(mock_client, "https://blog.example.com", None, None)

        mock_login.assert_called_once_with(mock_client, cli_username="admin", config_username=None)
        mock_save.assert_called_once_with("https://blog.example.com", "admin", "new-refresh-token")

    def test_full_login_when_no_stored_credentials(self, tmp_path: Path) -> None:
        mock_client = MagicMock()
        mock_client.client.cookies.get.return_value = "new-refresh-token"

        with (
            patch("agblogger_cli.sync_client.load_credentials", return_value=None),
            patch("agblogger_cli.sync_client.login_interactive", return_value="admin") as mock_login,
            patch("agblogger_cli.sync_client.save_credentials") as mock_save,
        ):
            _authenticate(mock_client, "https://blog.example.com", "admin", None)

        mock_login.assert_called_once_with(mock_client, cli_username="admin", config_username=None)
        mock_save.assert_called_once_with("https://blog.example.com", "admin", "new-refresh-token")
```

- [ ] **Step 4: Run tests to confirm they fail**

```bash
uv run pytest tests/test_cli/test_sync_client_ux.py::TestAuthenticate -v
```

Expected: `ImportError: cannot import name '_authenticate'`

- [ ] **Step 5: Replace login_interactive call in main() with _authenticate**

In `main()`, find the "Authenticate interactively" block:

```python
# OLD:
try:
    with SyncClient(server_url, content_dir) as client:
        login_interactive(
            client,
            cli_username=args.username,
            config_username=config.get("username"),
        )
        if args.command == "status":
            ...
```

Replace with:

```python
try:
    with SyncClient(server_url, content_dir) as client:
        _authenticate(
            client,
            server_url,
            cli_username=args.username,
            config_username=config.get("username"),
        )
        if args.command == "status":
            ...
```

- [ ] **Step 6: Update existing UX tests that mock login_interactive**

In `tests/test_cli/test_sync_client_ux.py`, find all occurrences of:

```python
patch("agblogger_cli.sync_client.login_interactive", return_value="token"),
```

Replace each with:

```python
patch("agblogger_cli.sync_client._authenticate"),
```

(These tests are testing sync/status behavior after auth, not auth itself — mocking `_authenticate` as a no-op is correct.)

- [ ] **Step 7: Run full test suite**

```bash
uv run pytest tests/test_cli/test_sync_client_ux.py -v
```

Expected: all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add agblogger_cli/agblogger_cli/sync_client.py tests/test_cli/test_sync_client_ux.py
git commit -m "feat: use stored credentials in sync/status session startup"
```

---

## Task 8: Full gate check

**Files:** none

- [ ] **Step 1: Run the full check**

```bash
just check
```

Expected: all static checks and tests pass, coverage targets met.

- [ ] **Step 2: Fix any failures**

If `mypy` or `basedpyright` complains about the `StoredCredentials` TypedDict usage, ensure all call sites pass correct types. If coverage drops below threshold, add missing test cases.

- [ ] **Step 3: Commit any fixes**

```bash
git add -p
git commit -m "fix: address static analysis findings from persistent auth implementation"
```
