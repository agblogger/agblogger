"""CLI sync client for AgBlogger bidirectional sync."""

from __future__ import annotations

import argparse
import contextlib
import getpass
import hashlib
import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from backend.sync_paths import is_sync_managed_path
from cli.version import get_cli_version

try:
    import httpx
except ImportError:
    print("Error: httpx is required. Install with: pip install httpx")
    sys.exit(1)

MANIFEST_FILE = ".agblogger-manifest.json"
CONFIG_FILE = ".agblogger.json"
_LOCALHOST_HOSTS = {"localhost", "127.0.0.1", "::1"}
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass
class FileEntry:
    file_path: str
    content_hash: str
    file_size: int
    file_mtime: str


def hash_file(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


def scan_local_files(content_dir: Path) -> dict[str, FileEntry]:
    """Scan local content directory."""
    entries: dict[str, FileEntry] = {}
    for root, dirs, files in os.walk(content_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for filename in files:
            if filename.startswith("."):
                continue
            full = Path(root) / filename
            rel = str(full.relative_to(content_dir))
            if not is_sync_managed_path(rel):
                continue
            stat = full.stat()
            entries[rel] = FileEntry(
                file_path=rel,
                content_hash=hash_file(full),
                file_size=stat.st_size,
                file_mtime=str(stat.st_mtime),
            )
    return entries


def load_manifest(content_dir: Path) -> dict[str, FileEntry]:
    """Load local manifest from file."""
    manifest_path = content_dir / MANIFEST_FILE
    if not manifest_path.exists():
        return {}
    data = json.loads(manifest_path.read_text())
    return {k: FileEntry(**v) for k, v in data.items()}


def save_manifest(content_dir: Path, entries: dict[str, FileEntry]) -> None:
    """Save local manifest to file."""
    manifest_path = content_dir / MANIFEST_FILE
    data = {k: asdict(v) for k, v in entries.items()}
    manifest_path.write_text(json.dumps(data, indent=2))


def _is_safe_local_path(content_dir: Path, file_path: str) -> Path | None:
    """Resolve a server-provided path within content_dir, returning None on traversal."""
    local_path = (content_dir / file_path).resolve()
    if not local_path.is_relative_to(content_dir.resolve()):
        return None
    return local_path


def _prune_empty_parents(start: Path, *, stop_at: Path) -> None:
    """Remove empty parent directories from *start* upward, stopping at *stop_at*."""
    current = start
    resolved_stop = stop_at.resolve()
    while current.resolve() != resolved_stop:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


# ── Config management ────────────────────────────────────────────────


def validate_server_url(server_url: str, allow_insecure_http: bool = False) -> str:
    """Validate server URL and enforce HTTPS for non-localhost hosts by default."""
    normalized = server_url.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Server URL must include scheme and host (e.g. https://example.com)")

    hostname = parsed.hostname
    if parsed.scheme == "http" and not allow_insecure_http and hostname not in _LOCALHOST_HOSTS:
        raise ValueError(
            "HTTPS is required for non-localhost servers. "
            "Use --allow-insecure-http only on trusted networks."
        )

    return normalized


def read_config(dir_path: Path) -> dict[str, str]:
    """Read sync config from file.

    Returns the parsed config dict, or an empty dict if the file doesn't exist.
    Raises ``json.JSONDecodeError``, ``UnicodeDecodeError``, or ``OSError``
    when the file exists but cannot be read or parsed.
    """
    config_path = dir_path / CONFIG_FILE
    if not config_path.exists():
        return {}
    config: dict[str, str] = json.loads(config_path.read_text())
    return config


def load_config(dir_path: Path) -> dict[str, str]:
    """Load sync config from file, exiting the process on error."""
    try:
        return read_config(dir_path)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        print(f"Error: Could not read {CONFIG_FILE}: {exc}")
        sys.exit(1)


def save_config(dir_path: Path, config: dict[str, str]) -> None:
    """Save sync config to file and restrict permissions to owner-only."""
    config_path = dir_path / CONFIG_FILE
    config_path.write_text(json.dumps(config, indent=2))
    try:
        config_path.chmod(0o600)
    except OSError as exc:
        print(
            f"Warning: Could not set restrictive permissions on {CONFIG_FILE}: {exc}",
            file=sys.stderr,
        )


# ── Plan helpers ─────────────────────────────────────────────────────


def has_pending_changes(plan: dict[str, Any]) -> bool:
    """Check whether a sync plan has any pending operations."""
    return bool(
        plan.get("to_upload")
        or plan.get("to_download")
        or plan.get("to_delete_local")
        or plan.get("to_delete_remote")
        or plan.get("conflicts")
    )


def format_plan_summary(plan: dict[str, Any]) -> str:
    """Format a sync plan as a human-readable file list."""
    lines: list[str] = []
    for f in plan.get("to_upload", []):
        lines.append(f"  + {f} (upload)")
    for f in plan.get("to_download", []):
        lines.append(f"  < {f} (download)")
    for f in plan.get("to_delete_local", []):
        lines.append(f"  - {f} (delete local)")
    for f in plan.get("to_delete_remote", []):
        lines.append(f"  - {f} (delete remote)")
    for c in plan.get("conflicts", []):
        lines.append(f"  ! {c['file_path']} (reconcile on sync)")
    return "\n".join(lines)


def format_conflict_details(conflict: dict[str, Any]) -> str:
    """Format sync conflict details for CLI output."""
    details: list[str] = []
    if conflict.get("body_conflicted"):
        details.append("body")

    field_conflicts = conflict.get("field_conflicts", [])
    user_fields: list[str] = []
    for field in field_conflicts:
        if field == "_no_base":
            details.append("no common base")
        elif field == "_parse_error":
            details.append("parse error")
        else:
            user_fields.append(str(field))
    if user_fields:
        details.append(f"fields: {', '.join(user_fields)}")
    return ", ".join(details) or "unknown"


def print_plan_warnings(plan: dict[str, Any]) -> None:
    """Print any warnings returned with a sync plan."""
    for warning in plan.get("warnings", []):
        print(f"  Warning: {warning}")


def confirm_sync(plan: dict[str, Any]) -> bool:
    """Display sync plan and prompt for confirmation."""
    summary = format_plan_summary(plan)
    if summary:
        print(summary)
    try:
        response = input("Proceed with sync? [y/N]: ")
    except KeyboardInterrupt, EOFError:
        print()
        return False
    return response.strip().lower() in {"y", "yes"}


# ── Authentication ───────────────────────────────────────────────────


def login_interactive(
    client: SyncClient,
    *,
    cli_username: str | None,
    config_username: str | None,
) -> None:
    """Interactively authenticate and persist a refreshable session on the client."""
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


# ── Sync client ──────────────────────────────────────────────────────


class SyncClient:
    """Client for syncing with AgBlogger server."""

    def __init__(self, server_url: str, content_dir: Path, token: str | None = None) -> None:
        self.server_url = server_url.rstrip("/")
        self.content_dir = content_dir
        headers: dict[str, str] | None = None
        if token is not None:
            headers = {"Authorization": f"Bearer {token}"}
        self.client = httpx.Client(
            base_url=self.server_url,
            headers=headers,
            timeout=60.0,
        )
        self._csrf_token: str | None = None

    def close(self) -> None:
        """Close the HTTP client."""
        try:
            self.logout()
        finally:
            self.client.close()

    def __enter__(self) -> SyncClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def logout(self) -> None:
        """Revoke the current session refresh token when the CLI exits."""
        if getattr(self, "_csrf_token", None) is None:
            return
        if "Authorization" in self.client.headers:
            return

        try:
            resp = self._call(
                "POST",
                "/api/auth/logout",
                json={},
                headers={"X-CSRF-Token": self._csrf_token},
            )
            resp.raise_for_status()
        except (httpx.HTTPError, ValueError) as exc:
            print(
                f"Warning: failed to revoke CLI session on exit: {exc}",
                file=sys.stderr,
            )
        finally:
            self._csrf_token = None

    def _call(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        if method == "GET":
            return self.client.get(url, **kwargs)
        if method == "POST":
            return self.client.post(url, **kwargs)
        if method == "PUT":
            return self.client.put(url, **kwargs)
        if method == "PATCH":
            return self.client.patch(url, **kwargs)
        if method == "DELETE":
            return self.client.delete(url, **kwargs)
        raise ValueError(f"Unsupported HTTP method: {method}")

    def _build_headers(
        self,
        method: str,
        headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        request_headers = dict(headers or {})
        has_authorization = any(name.lower() == "authorization" for name in request_headers)
        csrf_token = getattr(self, "_csrf_token", None)
        if method in _UNSAFE_METHODS and csrf_token is not None and not has_authorization:
            request_headers["X-CSRF-Token"] = csrf_token
        return request_headers

    def _refresh_session(self) -> bool:
        csrf_token = getattr(self, "_csrf_token", None)
        if csrf_token is None:
            return False

        try:
            resp = self._call(
                "POST",
                "/api/auth/refresh",
                json={},
                headers={"X-CSRF-Token": csrf_token},
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

    def _request(
        self,
        method: str,
        url: str,
        *,
        retry_on_401: bool = True,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        request_headers = self._build_headers(method, headers)
        resp = self._call(method, url, headers=request_headers or None, **kwargs)
        if (
            resp.status_code == 401
            and retry_on_401
            and getattr(self, "_csrf_token", None) is not None
            and url not in {"/api/auth/login", "/api/auth/refresh"}
            and self._refresh_session()
        ):
            retry_headers = self._build_headers(method, headers)
            return self._call(method, url, headers=retry_headers or None, **kwargs)
        return resp

    def login(self, username: str, password: str) -> None:
        """Login and persist a session-backed CSRF token for follow-up requests."""
        resp = self._call(
            "POST",
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError as exc:
            raise ValueError("Server returned invalid response") from exc

        csrf_token = data.get("csrf_token")
        if not isinstance(csrf_token, str) or not csrf_token:
            raise ValueError("Server response missing csrf token")

        self._csrf_token = csrf_token
        if "Authorization" in self.client.headers:
            del self.client.headers["Authorization"]

    def _get_last_sync_commit(self) -> str | None:
        """Get the commit hash from the last sync."""
        try:
            config = read_config(self.content_dir)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            print(
                f"Warning: Could not read {CONFIG_FILE}: {exc}\n"
                f"  Three-way merge disabled for this sync; server version "
                f"will be preferred on all conflicts.",
                file=sys.stderr,
            )
            return None
        return config.get("last_sync_commit")

    def _save_commit_hash(self, commit_hash: str | None) -> None:
        """Save the commit hash from a sync response."""
        if commit_hash is None:
            return
        try:
            config = read_config(self.content_dir)
            config["last_sync_commit"] = commit_hash
            save_config(self.content_dir, config)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            print(
                f"Warning: Could not save sync commit hash: {exc}\n"
                f"  The next sync may produce incorrect merge results.\n"
                f"  Ensure {CONFIG_FILE} is writable before syncing again.",
                file=sys.stderr,
            )

    def status(self) -> dict[str, Any]:
        """Show what would change without syncing."""
        local_files = scan_local_files(self.content_dir)
        manifest = [asdict(e) for e in local_files.values()]

        resp = self._request(
            "POST",
            "/api/sync/status",
            json={"client_manifest": manifest},
        )
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        return result

    def _download_file(self, file_path: str) -> bool:
        """Download a single file from the server. Returns True if successful."""
        local_path = _is_safe_local_path(self.content_dir, file_path)
        if local_path is None:
            print(f"  Skip (path traversal): {file_path}")
            return False
        try:
            resp = self._request("GET", f"/api/sync/download/{file_path}")
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            print(f"  ERROR: Failed to download {file_path} (HTTP {exc.response.status_code})")
            return False
        except httpx.TransportError as exc:
            print(f"  ERROR: Failed to download {file_path}: {exc}")
            return False
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(resp.content)
        except OSError as exc:
            print(f"  ERROR: Failed to write {file_path}: {exc}")
            return False
        return True

    def _backup_conflicted_files(self, conflicts: list[dict[str, Any]]) -> Path | None:
        """Back up local versions of conflicted files before they are overwritten.

        Returns the backup directory path, or None if no files were backed up.
        """
        if not conflicts:
            return None

        backed_up = 0
        timestamp = datetime.now(tz=UTC).strftime("%Y-%m-%d-%H%M%S")
        backups_root = self.content_dir / ".backups"
        backup_dir = backups_root / timestamp
        suffix = 1
        while backup_dir.exists():
            backup_dir = backups_root / f"{timestamp}-{suffix}"
            suffix += 1

        for conflict in conflicts:
            fp = conflict["file_path"]
            local_path = _is_safe_local_path(self.content_dir, fp)
            if local_path is None:
                print(f"  Skip backup (path traversal): {fp}")
                continue
            dest = backup_dir / fp
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(local_path, dest)
            except FileNotFoundError:
                print(f"  Skip backup (file not found locally): {fp}")
                continue
            except OSError as exc:
                print(f"  Warning: Could not back up {fp}: {exc}")
                continue
            backed_up += 1

        if backed_up == 0:
            # Clean up empty backup directory if no files were backed up
            try:
                if backup_dir.exists():
                    shutil.rmtree(backup_dir)
                # Also remove the parent .backups dir if it is now empty
                if backups_root.exists() and not any(backups_root.iterdir()):
                    backups_root.rmdir()
            except OSError as exc:
                print(
                    f"  Warning: Could not clean up empty backup directory: {exc}",
                    file=sys.stderr,
                )
            return None
        return backup_dir

    def sync(self, plan: dict[str, Any] | None = None, *, emit_plan_warnings: bool = True) -> None:
        """Bidirectional sync with the server."""
        if plan is None:
            plan = self.status()
        if emit_plan_warnings:
            print_plan_warnings(plan)
        to_upload: list[str] = plan.get("to_upload", [])
        to_download_plan: list[str] = plan.get("to_download", [])
        to_delete_remote: list[str] = plan.get("to_delete_remote", [])
        to_delete_local: list[str] = plan.get("to_delete_local", [])
        conflicts: list[dict[str, Any]] = plan.get("conflicts", [])
        last_sync_commit = self._get_last_sync_commit()

        # Collect all files to upload: plan's to_upload + conflict files
        file_paths_to_upload: list[str] = list(to_upload)
        conflict_downloads: list[str] = []
        for conflict in conflicts:
            fp = conflict["file_path"]
            local_path = _is_safe_local_path(self.content_dir, fp)
            if (
                conflict.get("change_type") == "delete_modify_conflict"
                and local_path is not None
                and not local_path.exists()
            ):
                if fp not in conflict_downloads:
                    conflict_downloads.append(fp)
                print(f"  Keep server version: {fp}")
                continue
            if fp not in file_paths_to_upload:
                file_paths_to_upload.append(fp)

        # Build multipart request
        metadata = json.dumps(
            {
                "deleted_files": to_delete_remote,
                "last_sync_commit": last_sync_commit,
            }
        )

        files_to_send: list[tuple[str, tuple[str, bytes]]] = []
        synced_paths: set[str] = set()
        for fp in file_paths_to_upload:
            full_path = _is_safe_local_path(self.content_dir, fp)
            if full_path is None:
                print(f"  Skip (path traversal in upload): {fp}")
                continue
            if not full_path.exists():
                print(f"  Skip (missing): {fp}")
                continue
            try:
                content = full_path.read_bytes()
            except OSError as exc:
                print(f"  Warning: Could not read {fp}, skipping: {exc}")
                continue
            files_to_send.append(("files", (fp, content)))
            synced_paths.add(fp)
            print(f"  Upload: {fp}")

        try:
            resp = self._request(
                "POST",
                "/api/sync/commit",
                data={"metadata": metadata},
                files=files_to_send if files_to_send else None,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = ""
            with contextlib.suppress(ValueError, AttributeError):
                detail = exc.response.json().get("detail", "")
            if detail:
                print(f"Error: Sync commit failed (HTTP {exc.response.status_code}): {detail}")
            else:
                print(f"Error: Sync commit failed (HTTP {exc.response.status_code})")
            print("Local state may be inconsistent. Re-run sync to recover.")
            return
        commit_data: dict[str, Any] = resp.json()

        # Back up local versions of conflicted files before downloading server versions
        response_conflicts: list[dict[str, Any]] = commit_data.get("conflicts", [])
        try:
            backup_dir = self._backup_conflicted_files(response_conflicts)
        except OSError as exc:
            print(f"  Warning: Backup failed, continuing with sync: {exc}")
            backup_dir = None

        # Download files: from plan's to_download + from commit response's to_download
        all_downloads: list[str] = list(to_download_plan)
        for fp in conflict_downloads:
            if fp not in all_downloads:
                all_downloads.append(fp)
        for fp in commit_data.get("to_download", []):
            if fp not in all_downloads:
                all_downloads.append(fp)

        for fp in all_downloads:
            if self._download_file(fp):
                print(f"  Download: {fp}")
                synced_paths.add(fp)

        # Delete local files
        for fp in to_delete_local:
            local_path = _is_safe_local_path(self.content_dir, fp)
            if local_path is None:
                print(f"  Skip (path traversal in delete): {fp}")
                continue
            if local_path.exists():
                try:
                    local_path.unlink()
                except OSError as exc:
                    print(f"  Warning: Failed to delete {fp}: {exc}")
                    continue
                _prune_empty_parents(local_path.parent, stop_at=self.content_dir)
                print(f"  Delete local: {fp}")
                synced_paths.add(fp)

        # Report conflicts
        for c in response_conflicts:
            fp = c["file_path"]
            print(f"  CONFLICT: {fp} ({format_conflict_details(c)})")
        if backup_dir is not None:
            print(f"  Backups of your local versions saved to .backups/{backup_dir.name}/")

        # Report warnings
        for warning in commit_data.get("warnings", []):
            print(f"  Warning: {warning}")

        # Save commit hash and update local manifest
        self._save_commit_hash(commit_data.get("commit_hash"))
        local_files = scan_local_files(self.content_dir)
        save_manifest(self.content_dir, local_files)

        total = len(synced_paths)
        print(f"Sync complete. {total} file(s) synced, {len(response_conflicts)} conflict(s).")


# ── CLI entry point ──────────────────────────────────────────────────


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="agblogger",
        description="Sync local content with AgBlogger server",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {get_cli_version()}",
    )
    parser.add_argument("--dir", "-d", default=".", help="Content directory (default: current)")
    parser.add_argument("--server", "-s", help="Server URL")
    parser.add_argument(
        "--allow-insecure-http",
        action="store_true",
        help="Allow http:// server URLs for non-localhost hosts",
    )
    parser.add_argument("--username", "-u", help="Username for authentication")

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("init", help="Initialize sync configuration")
    subparsers.add_parser("status", help="Show what would change")
    sync_parser = subparsers.add_parser("sync", help="Bidirectional sync")
    sync_parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")

    args = parser.parse_args()
    content_dir = Path(args.dir).resolve()

    if args.command is None:
        parser.print_help()
        return

    if args.command == "init":
        if not args.server:
            print("Error: --server required for init")
            sys.exit(1)
        try:
            server_url = validate_server_url(args.server, args.allow_insecure_http)
        except ValueError as exc:
            print(f"Error: {exc}")
            sys.exit(1)
        config: dict[str, str] = {
            "server": server_url,
            "content_dir": str(content_dir),
        }
        if args.username:
            config["username"] = args.username
        save_config(content_dir, config)
        print(f"Initialized sync config in {content_dir / CONFIG_FILE}")
        return

    # Load config
    config = load_config(content_dir)

    configured_server_url = args.server or config.get("server")
    if not configured_server_url:
        print("Error: No server configured. Run 'agblogger init --server <url>' first.")
        sys.exit(1)
    try:
        server_url = validate_server_url(configured_server_url, args.allow_insecure_http)
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(1)

    # Authenticate interactively
    try:
        with SyncClient(server_url, content_dir) as client:
            login_interactive(
                client,
                cli_username=args.username,
                config_username=config.get("username"),
            )
            if args.command == "status":
                plan = client.status()
                print_plan_warnings(plan)
                print("Sync Status:")
                print(f"  To upload:        {len(plan.get('to_upload', []))}")
                print(f"  To download:      {len(plan.get('to_download', []))}")
                print(f"  To delete local:  {len(plan.get('to_delete_local', []))}")
                print(f"  To delete remote: {len(plan.get('to_delete_remote', []))}")
                print(f"  Conflicts:        {len(plan.get('conflicts', []))}")

                for f in plan.get("to_upload", []):
                    print(f"    + {f} (upload)")
                for f in plan.get("to_download", []):
                    print(f"    < {f} (download)")
                for f in plan.get("to_delete_local", []):
                    print(f"    - {f} (delete local)")
                for f in plan.get("to_delete_remote", []):
                    print(f"    - {f} (delete remote)")
                for c in plan.get("conflicts", []):
                    print(f"    ! {c['file_path']} (reconcile on sync)")

            elif args.command == "sync":
                plan = client.status()
                print_plan_warnings(plan)
                if has_pending_changes(plan) and not args.yes and not confirm_sync(plan):
                    print("Sync cancelled.")
                    sys.exit(0)
                client.sync(plan, emit_plan_warnings=False)
    except httpx.HTTPStatusError as exc:
        print(f"Error: Server returned HTTP {exc.response.status_code}")
        sys.exit(1)


if __name__ == "__main__":
    main()
