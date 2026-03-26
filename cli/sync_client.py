"""CLI sync client for AgBlogger bidirectional sync."""

from __future__ import annotations

import argparse
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

try:
    import httpx
except ImportError:
    print("Error: httpx is required. Install with: pip install httpx")
    sys.exit(1)

MANIFEST_FILE = ".agblogger-manifest.json"
CONFIG_FILE = ".agblogger.json"
_LOCALHOST_HOSTS = {"localhost", "127.0.0.1", "::1"}


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


def load_config(dir_path: Path) -> dict[str, str]:
    """Load sync config from file."""
    config_path = dir_path / CONFIG_FILE
    if not config_path.exists():
        return {}
    try:
        config: dict[str, str] = json.loads(config_path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        print(f"Error: Could not read {CONFIG_FILE}: {exc}")
        sys.exit(1)
    return config


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
        lines.append(f"  ! {c['file_path']} (conflict)")
    return "\n".join(lines)


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
    server_url: str,
    *,
    cli_username: str | None,
    config_username: str | None,
) -> str:
    """Interactively authenticate and return an access token."""
    username = cli_username or config_username
    if not username:
        username = input("Username: ")
    password = getpass.getpass("Password: ")

    try:
        client = httpx.Client(base_url=server_url, timeout=30.0)
        try:
            resp = client.post(
                "/api/auth/token-login",
                json={"username": username, "password": password},
            )
        finally:
            client.close()
    except httpx.ConnectError:
        print(f"Error: Could not connect to server at {server_url}")
        sys.exit(1)
    except httpx.TimeoutException:
        print(f"Error: Connection to {server_url} timed out")
        sys.exit(1)

    if resp.status_code == 401:
        print("Error: Invalid username or password")
        sys.exit(1)
    if resp.status_code != 200:
        print(f"Error: Login failed (HTTP {resp.status_code})")
        sys.exit(1)

    try:
        data = resp.json()
    except ValueError, UnicodeDecodeError:
        print("Error: Server returned invalid response")
        sys.exit(1)
    if "access_token" not in data:
        print("Error: Server response missing access token")
        sys.exit(1)
    result: str = data["access_token"]
    return result


# ── Sync client ──────────────────────────────────────────────────────


class SyncClient:
    """Client for syncing with AgBlogger server."""

    def __init__(self, server_url: str, content_dir: Path, token: str) -> None:
        self.server_url = server_url.rstrip("/")
        self.content_dir = content_dir
        self.client = httpx.Client(
            base_url=self.server_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=60.0,
        )

    def close(self) -> None:
        """Close the HTTP client."""
        self.client.close()

    def __enter__(self) -> SyncClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def login(self, username: str, password: str) -> str:
        """Login and return access token."""
        resp = self.client.post(
            "/api/auth/token-login",
            json={"username": username, "password": password},
        )
        resp.raise_for_status()
        result: str = resp.json()["access_token"]
        return result

    def _get_last_sync_commit(self) -> str | None:
        """Get the commit hash from the last sync."""
        config = load_config(self.content_dir)
        return config.get("last_sync_commit")

    def _save_commit_hash(self, commit_hash: str | None) -> None:
        """Save the commit hash from a sync response."""
        if commit_hash is None:
            return
        config = load_config(self.content_dir)
        config["last_sync_commit"] = commit_hash
        save_config(self.content_dir, config)

    def status(self) -> dict[str, Any]:
        """Show what would change without syncing."""
        local_files = scan_local_files(self.content_dir)
        manifest = [asdict(e) for e in local_files.values()]

        resp = self.client.post(
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
            resp = self.client.get(f"/api/sync/download/{file_path}")
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            print(f"  ERROR: Failed to download {file_path} (HTTP {exc.response.status_code})")
            return False
        except httpx.TransportError as exc:
            print(f"  ERROR: Failed to download {file_path}: {exc}")
            return False
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(resp.content)
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
            except OSError:
                pass
            return None
        return backup_dir

    def sync(self, plan: dict[str, Any] | None = None) -> None:
        """Bidirectional sync with the server."""
        if plan is None:
            plan = self.status()
        to_upload: list[str] = plan.get("to_upload", [])
        to_download_plan: list[str] = plan.get("to_download", [])
        to_delete_remote: list[str] = plan.get("to_delete_remote", [])
        to_delete_local: list[str] = plan.get("to_delete_local", [])
        conflicts: list[dict[str, Any]] = plan.get("conflicts", [])
        last_sync_commit = self._get_last_sync_commit()

        # Collect all files to upload: plan's to_upload + conflict files
        file_paths_to_upload: list[str] = list(to_upload)
        for conflict in conflicts:
            fp = conflict["file_path"]
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
        for fp in file_paths_to_upload:
            full_path = _is_safe_local_path(self.content_dir, fp)
            if full_path is None:
                print(f"  Skip (path traversal in upload): {fp}")
                continue
            if not full_path.exists():
                print(f"  Skip (missing): {fp}")
                continue
            files_to_send.append(("files", (fp, full_path.read_bytes())))
            print(f"  Upload: {fp}")

        try:
            resp = self.client.post(
                "/api/sync/commit",
                data={"metadata": metadata},
                files=files_to_send if files_to_send else None,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
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
        for fp in commit_data.get("to_download", []):
            if fp not in all_downloads:
                all_downloads.append(fp)

        downloads_ok = 0
        for fp in all_downloads:
            if self._download_file(fp):
                print(f"  Download: {fp}")
                downloads_ok += 1

        # Delete local files
        deletes_done = 0
        for fp in to_delete_local:
            local_path = _is_safe_local_path(self.content_dir, fp)
            if local_path is None:
                print(f"  Skip (path traversal in delete): {fp}")
                continue
            if local_path.exists():
                local_path.unlink()
                print(f"  Delete local: {fp}")
                deletes_done += 1

        # Report conflicts
        for c in response_conflicts:
            fp = c["file_path"]
            details: list[str] = []
            if c.get("body_conflicted"):
                details.append("body")
            field_conflicts = c.get("field_conflicts", [])
            if field_conflicts:
                details.append(f"fields: {', '.join(field_conflicts)}")
            print(f"  CONFLICT: {fp} ({', '.join(details) or 'unknown'})")
        if backup_dir is not None:
            print(f"  Backups of your local versions saved to .backups/{backup_dir.name}/")

        # Report warnings
        for warning in commit_data.get("warnings", []):
            print(f"  Warning: {warning}")

        # Save commit hash and update local manifest
        self._save_commit_hash(commit_data.get("commit_hash"))
        local_files = scan_local_files(self.content_dir)
        save_manifest(self.content_dir, local_files)

        total = len(files_to_send) + downloads_ok + deletes_done
        print(f"Sync complete. {total} file(s) synced, {len(response_conflicts)} conflict(s).")


# ── CLI entry point ──────────────────────────────────────────────────


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="agblogger",
        description="Sync local content with AgBlogger server",
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
    token = login_interactive(
        server_url,
        cli_username=args.username,
        config_username=config.get("username"),
    )

    try:
        with SyncClient(server_url, content_dir, token) as client:
            if args.command == "status":
                plan = client.status()
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
                for c in plan.get("conflicts", []):
                    print(f"    ! {c['file_path']} (conflict)")

            elif args.command == "sync":
                plan = client.status()
                if has_pending_changes(plan) and not args.yes and not confirm_sync(plan):
                    print("Sync cancelled.")
                    sys.exit(0)
                client.sync(plan)
            else:
                parser.print_help()
    except httpx.HTTPStatusError as exc:
        print(f"Error: Server returned HTTP {exc.response.status_code}")
        sys.exit(1)


if __name__ == "__main__":
    main()
