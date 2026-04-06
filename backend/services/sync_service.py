"""Sync service: manifest comparison, change detection, and merge logic."""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import tomllib
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import frontmatter as fm
import tomli_w
import yaml
from sqlalchemy import delete, select

from backend.filesystem.frontmatter import RECOGNIZED_FIELDS, extract_title, strip_leading_heading
from backend.models.sync import SyncManifest
from backend.sync_paths import is_sync_managed_path as is_sync_managed_path
from backend.utils.datetime import format_datetime, format_iso, now_utc, parse_datetime
from backend.utils.slug import is_directory_post_path

logger = logging.getLogger(__name__)

_TOML_PARSE_ERRORS = (tomllib.TOMLDecodeError, ValueError)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.services.git_service import GitService


class ChangeType(StrEnum):
    """Type of change detected between client, server, and manifest."""

    NO_CHANGE = "no_change"
    LOCAL_ADD = "local_add"
    LOCAL_MODIFY = "local_modify"
    LOCAL_DELETE = "local_delete"
    REMOTE_ADD = "remote_add"
    REMOTE_MODIFY = "remote_modify"
    REMOTE_DELETE = "remote_delete"
    CONFLICT = "conflict"
    DELETE_MODIFY_CONFLICT = "delete_modify_conflict"


@dataclass
class FileEntry:
    """Represents a file's state."""

    file_path: str
    content_hash: str
    file_size: int
    file_mtime: str


@dataclass
class SyncChange:
    """A single change in the sync plan."""

    file_path: str
    change_type: ChangeType
    action: str  # "push", "pull", "merge", "skip", "delete_remote", "delete_local"


@dataclass
class SyncPlan:
    """The computed sync plan."""

    to_upload: list[str] = field(default_factory=list)
    to_download: list[str] = field(default_factory=list)
    to_delete_remote: list[str] = field(default_factory=list)
    to_delete_local: list[str] = field(default_factory=list)
    conflicts: list[SyncChange] = field(default_factory=list)
    no_change: list[str] = field(default_factory=list)


def hash_file(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


def scan_content_files(content_dir: Path) -> dict[str, FileEntry]:
    """Scan content directory and build file entry map."""
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
            try:
                stat = full.stat()
                entries[rel] = FileEntry(
                    file_path=rel,
                    content_hash=hash_file(full),
                    file_size=stat.st_size,
                    file_mtime=str(stat.st_mtime),
                )
            except OSError as exc:
                logger.warning("Skipping file %s during content scan: %s", rel, exc)
    return entries


def compute_sync_plan(
    client_manifest: dict[str, FileEntry],
    server_manifest: dict[str, FileEntry],
    server_current: dict[str, FileEntry],
) -> SyncPlan:
    """Compute sync plan by comparing client manifest, server manifest, and server current state.

    client_manifest is the client's current file state, server_manifest is the
    agreed-upon state from the last sync, and server_current is the server's
    current file state on disk.
    """
    plan = SyncPlan()

    all_paths = (
        set(client_manifest.keys()) | set(server_manifest.keys()) | set(server_current.keys())
    )

    for path in sorted(all_paths):
        in_client = path in client_manifest
        in_manifest = path in server_manifest
        in_server = path in server_current

        if in_client and in_manifest and in_server:
            client_hash = client_manifest[path].content_hash
            manifest_hash = server_manifest[path].content_hash
            server_hash = server_current[path].content_hash

            client_changed = client_hash != manifest_hash
            server_changed = server_hash != manifest_hash

            if not client_changed and not server_changed:
                plan.no_change.append(path)
            elif client_changed and not server_changed:
                plan.to_upload.append(path)
            elif not client_changed and server_changed:
                plan.to_download.append(path)
            else:
                # Both changed
                if client_hash == server_hash:
                    plan.no_change.append(path)
                else:
                    plan.conflicts.append(
                        SyncChange(
                            file_path=path,
                            change_type=ChangeType.CONFLICT,
                            action="merge",
                        )
                    )

        elif in_client and not in_manifest and not in_server:
            # New local file
            plan.to_upload.append(path)

        elif not in_client and not in_manifest and in_server:
            # New remote file
            plan.to_download.append(path)

        elif in_client and in_manifest and not in_server:
            # Server deleted the file — check if client modified it
            client_hash = client_manifest[path].content_hash
            manifest_hash = server_manifest[path].content_hash
            if client_hash != manifest_hash:
                # Client modified a file the server deleted
                plan.conflicts.append(
                    SyncChange(
                        file_path=path,
                        change_type=ChangeType.DELETE_MODIFY_CONFLICT,
                        action="merge",
                    )
                )
            else:
                plan.to_delete_local.append(path)

        elif not in_client and in_manifest and in_server:
            # Local deletion; preserve remote edits as conflict.
            manifest_hash = server_manifest[path].content_hash
            server_hash = server_current[path].content_hash
            if server_hash != manifest_hash:
                plan.conflicts.append(
                    SyncChange(
                        file_path=path,
                        change_type=ChangeType.DELETE_MODIFY_CONFLICT,
                        action="merge",
                    )
                )
            else:
                plan.to_delete_remote.append(path)

        elif in_client and not in_manifest and in_server:
            # Both added independently
            client_hash = client_manifest[path].content_hash
            server_hash = server_current[path].content_hash
            if client_hash == server_hash:
                plan.no_change.append(path)
            else:
                plan.conflicts.append(
                    SyncChange(
                        file_path=path,
                        change_type=ChangeType.CONFLICT,
                        action="merge",
                    )
                )

        elif not in_client and in_manifest and not in_server:
            # Both deleted
            plan.no_change.append(path)

    return plan


async def get_server_manifest(session: AsyncSession) -> dict[str, FileEntry]:
    """Load the server's sync manifest from DB."""
    stmt = select(SyncManifest)
    result = await session.execute(stmt)
    entries: dict[str, FileEntry] = {}
    for row in result.scalars().all():
        entries[row.file_path] = FileEntry(
            file_path=row.file_path,
            content_hash=row.content_hash,
            file_size=row.file_size,
            file_mtime=row.file_mtime,
        )
    return entries


async def update_server_manifest(
    session: AsyncSession,
    entries: dict[str, FileEntry],
) -> None:
    """Replace the server manifest with new entries."""
    await session.execute(delete(SyncManifest))
    for entry in entries.values():
        session.add(
            SyncManifest(
                file_path=entry.file_path,
                content_hash=entry.content_hash,
                file_size=entry.file_size,
                file_mtime=entry.file_mtime,
                synced_at=format_iso(now_utc()),
            )
        )
    await session.commit()


@dataclass
class FrontmatterMergeResult:
    """Result of merging front matter fields semantically."""

    merged: dict[str, Any]
    field_conflicts: list[str]


def merge_frontmatter(
    base: dict[str, Any] | None,
    server: dict[str, Any],
    client: dict[str, Any],
) -> FrontmatterMergeResult:
    """Merge front matter fields semantically.

    Rules:
    - modified_at: excluded from merge (caller sets server time via normalization)
    - labels: set-based merge (additions/removals relative to base from both sides)
    - title, author, created_at, draft:
      if both changed differently, server wins + reported
    - unrecognized fields: if one side changed, take that change; if both, server wins
      (silently, not reported as a conflict)
    - field deletion: removing a field counts as a change; if both sides changed and
      server wins with deletion, the field is omitted from the merged result
    """
    if base is None:
        conflicts = [
            k
            for k in ("title", "author", "created_at", "draft")
            if k in server and k in client and server.get(k) != client.get(k)
        ]
        return FrontmatterMergeResult(merged=dict(server), field_conflicts=conflicts)

    merged: dict[str, Any] = {}
    field_conflicts: list[str] = []

    # Collect all keys except modified_at
    all_keys = (set(base) | set(server) | set(client)) - {"modified_at"}

    for key in all_keys:
        base_val = base.get(key)
        server_val = server.get(key)
        client_val = client.get(key)

        if key == "labels":
            # Set-based merge
            base_set = set(base_val) if isinstance(base_val, list) else set()
            server_set = set(server_val) if isinstance(server_val, list) else set()
            client_set = set(client_val) if isinstance(client_val, list) else set()

            server_added = server_set - base_set
            server_removed = base_set - server_set
            client_added = client_set - base_set
            client_removed = base_set - client_set

            result_set = (base_set | server_added | client_added) - server_removed - client_removed
            merged["labels"] = sorted(result_set)
            continue

        # For all other fields: three-way scalar merge
        server_changed = server_val != base_val
        client_changed = client_val != base_val

        if not server_changed and not client_changed:
            if base_val is not None:
                merged[key] = base_val
        elif server_changed and not client_changed:
            if server_val is not None:
                merged[key] = server_val
        elif not server_changed and client_changed:
            if client_val is not None:
                merged[key] = client_val
        else:
            # Both changed
            if server_val == client_val:
                if server_val is not None:
                    merged[key] = server_val
            else:
                # Conflict: server wins
                if server_val is not None:
                    merged[key] = server_val
                if key in ("title", "author", "created_at", "draft"):
                    field_conflicts.append(key)

    return FrontmatterMergeResult(merged=merged, field_conflicts=field_conflicts)


@dataclass
class LabelsMergeResult:
    """Result of merging labels.toml files."""

    merged_content: str
    field_conflicts: list[str]


def _set_merge(base: list[str], server: list[str], client: list[str]) -> list[str]:
    """Three-way set merge: apply additions and removals from both sides."""
    base_set = set(base)
    server_set = set(server)
    client_set = set(client)

    server_added = server_set - base_set
    server_removed = base_set - server_set
    client_added = client_set - base_set
    client_removed = base_set - client_set

    result = (base_set | server_added | client_added) - server_removed - client_removed
    return sorted(result)


def _ordered_set_merge(base: list[str], server: list[str], client: list[str]) -> list[str]:
    """Three-way merge that preserves meaningful list order while merging membership."""
    merged_items = set(_set_merge(base, server, client))
    if not merged_items:
        return []

    if server == base and client != base:
        preferred_orders = (client, server, base)
    elif client == base and server != base:
        preferred_orders = (server, client, base)
    elif client == server:
        preferred_orders = (client, server, base)
    else:
        preferred_orders = (base, server, client)

    merged: list[str] = []
    seen: set[str] = set()
    for values in preferred_orders:
        for value in values:
            if value in merged_items and value not in seen:
                merged.append(value)
                seen.add(value)
    return merged


def _get_label_list(label: object, key: str) -> list[str]:
    """Extract a list field from a parsed label entry."""
    if not isinstance(label, dict):
        return []
    raw = label.get(key, [])
    return raw if isinstance(raw, list) else []


def _get_label_parents(label: object) -> list[str]:
    """Extract parent references from either singular or plural TOML fields."""
    if not isinstance(label, dict):
        return []

    parents = _get_label_list(label, "parents")
    raw_parent = label.get("parent")
    if isinstance(raw_parent, str):
        return [raw_parent, *parents]
    return parents


def merge_labels_toml(
    base: str | None,
    server: str,
    client: str,
) -> LabelsMergeResult:
    """Merge labels.toml using three-way set-based merge for names and parents.

    Each label's names and parents are merged as sets (additions/removals from
    both sides are applied). The set of label IDs is also merged as a set.
    Falls back to client content when semantic merge is not possible.
    """
    try:
        server_data = tomllib.loads(server).get("labels", {})
    except _TOML_PARSE_ERRORS:
        logger.warning("Failed to parse server labels.toml during merge")
        return LabelsMergeResult(merged_content=client, field_conflicts=["_parse_error"])

    if base is None:
        return LabelsMergeResult(merged_content=client, field_conflicts=["_no_base"])

    try:
        base_data = tomllib.loads(base).get("labels", {})
    except _TOML_PARSE_ERRORS:
        logger.warning("Failed to parse base labels.toml during merge")
        return LabelsMergeResult(merged_content=client, field_conflicts=["_parse_error"])

    try:
        client_data = tomllib.loads(client).get("labels", {})
    except _TOML_PARSE_ERRORS:
        logger.warning("Failed to parse client labels.toml during merge")
        return LabelsMergeResult(merged_content=client, field_conflicts=["_parse_error"])

    # Three-way set merge for which label IDs exist
    base_ids = set(base_data)
    server_ids = set(server_data)
    client_ids = set(client_data)

    server_added_ids = server_ids - base_ids
    server_removed_ids = base_ids - server_ids
    client_added_ids = client_ids - base_ids
    client_removed_ids = base_ids - client_ids

    merged_ids = (
        (base_ids | server_added_ids | client_added_ids) - server_removed_ids - client_removed_ids
    )

    # Merge each label's fields
    merged_labels: dict[str, Any] = {}
    for label_id in sorted(merged_ids):
        base_label = base_data.get(label_id, {})
        server_label = server_data.get(label_id, {})
        client_label = client_data.get(label_id, {})

        base_names = _get_label_list(base_label, "names")
        server_names = _get_label_list(server_label, "names")
        client_names = _get_label_list(client_label, "names")

        base_parents = _get_label_parents(base_label)
        server_parents = _get_label_parents(server_label)
        client_parents = _get_label_parents(client_label)

        merged_names = _ordered_set_merge(base_names, server_names, client_names)
        merged_parents = _ordered_set_merge(base_parents, server_parents, client_parents)

        entry: dict[str, Any] = {"names": merged_names}
        if len(merged_parents) == 1:
            entry["parent"] = merged_parents[0]
        elif len(merged_parents) > 1:
            entry["parents"] = merged_parents
        merged_labels[label_id] = entry

    merged_content = tomli_w.dumps({"labels": merged_labels})
    return LabelsMergeResult(merged_content=merged_content, field_conflicts=[])


@dataclass
class PostMergeResult:
    """Result of merging a complete post file (front matter + body)."""

    merged_content: str
    body_conflicted: bool
    field_conflicts: list[str]


async def merge_post_file(
    base: str | None,
    server: str,
    client: str,
    git_service: GitService,
) -> PostMergeResult:
    """Merge a markdown post file using hybrid strategy.

    Front matter is merged semantically (set-based labels, server-wins scalars).
    Body is merged via git merge-file. modified_at is excluded during front matter
    merge (the caller sets server time after merge via normalization).
    """
    try:
        server_post = fm.loads(server)
        client_post = fm.loads(client)
    except (yaml.YAMLError, ValueError) as exc:
        logger.warning("Failed to parse front matter during merge: %s", exc)
        return PostMergeResult(merged_content=server, body_conflicted=True, field_conflicts=[])

    if base is None:
        # Without a merge base, three-way merge is impossible. Conservatively report
        # body as conflicted and keep the server version.
        fm_result = merge_frontmatter(None, dict(server_post.metadata), dict(client_post.metadata))
        return PostMergeResult(
            merged_content=server,
            body_conflicted=True,
            field_conflicts=fm_result.field_conflicts,
        )

    try:
        base_post = fm.loads(base)
    except (yaml.YAMLError, ValueError) as exc:
        logger.warning("Failed to parse base front matter during merge: %s", exc)
        return PostMergeResult(merged_content=server, body_conflicted=True, field_conflicts=[])

    # Merge front matter semantically
    fm_result = merge_frontmatter(
        dict(base_post.metadata), dict(server_post.metadata), dict(client_post.metadata)
    )

    # Merge body via git merge-file
    base_body = base_post.content
    server_body = server_post.content
    client_body = client_post.content

    if server_body == client_body:
        merged_body = server_body
        body_conflicted = False
    elif server_body == base_body:
        merged_body = client_body
        body_conflicted = False
    elif client_body == base_body:
        merged_body = server_body
        body_conflicted = False
    else:
        try:
            merged_body, body_conflicted = await git_service.merge_file_content(
                base_body, server_body, client_body
            )
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
            logger.warning("Git merge failed (%s), using server version", exc, exc_info=True)
            merged_body = server_body
            body_conflicted = True
        if body_conflicted:
            merged_body = server_body

    # Reassemble
    merged_post = fm.Post(merged_body, **fm_result.merged)
    try:
        merged_content = fm.dumps(merged_post) + "\n"
    except yaml.YAMLError as exc:
        logger.warning("Failed to serialize merged post: %s", exc)
        merged_content = server

    return PostMergeResult(
        merged_content=merged_content,
        body_conflicted=body_conflicted,
        field_conflicts=fm_result.field_conflicts,
    )


def normalize_post_frontmatter(
    uploaded_files: list[str],
    old_manifest: dict[str, FileEntry],
    content_dir: Path,
    *,
    force_edit_paths: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Normalize YAML front matter for uploaded post files during sync.

    Fills missing fields (timestamps, title) with defaults, strips the
    leading heading from the body when backfilling title, normalizes existing
    timestamps to strict format, and warns about unrecognized front matter fields.

    *force_edit_paths* overrides the ``is_edit`` detection for files that went
    through a merge — even when the manifest is empty (first sync), merged files
    should get ``modified_at = current_time`` rather than copying ``created_at``.

    Returns ``(warnings, modified_files)`` where *modified_files* lists paths
    whose on-disk content was actually changed by normalization.
    """
    warnings: list[str] = []
    modified_files: list[str] = []
    current_time = format_datetime(now_utc())

    for file_path in uploaded_files:
        # Skip non-post files
        if not is_directory_post_path(file_path):
            continue

        full_path = (content_dir / file_path).resolve()

        # Validate path stays within content_dir
        try:
            full_path.relative_to(content_dir.resolve())
        except ValueError:
            logger.warning("Path traversal attempt: %s", file_path)
            warnings.append(f"{file_path}: skipped normalization due to invalid path")
            continue

        # Skip if file doesn't exist on disk
        if not full_path.is_file():
            continue

        try:
            raw = full_path.read_text(encoding="utf-8")
            post = fm.loads(raw)
        except (UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
            logger.warning("Failed to parse %s: %s", file_path, exc)
            warnings.append(f"{file_path}: skipped normalization due to parse error")
            continue

        # Check for unrecognized fields
        for key in post.metadata:
            if key not in RECOGNIZED_FIELDS:
                warnings.append(f"{file_path}: unrecognized front matter field '{key}'")

        # Determine new vs edit — merged files are always edits even on first sync
        is_edit = file_path in old_manifest or (
            force_edit_paths is not None and file_path in force_edit_paths
        )

        # Normalize timestamps that already exist
        for ts_field in ("created_at", "modified_at"):
            raw_value = post.get(ts_field)
            if raw_value is not None:
                try:
                    if isinstance(raw_value, date) and not isinstance(raw_value, datetime):
                        raw_value = datetime(
                            raw_value.year,
                            raw_value.month,
                            raw_value.day,
                            tzinfo=UTC,
                        )
                    if isinstance(raw_value, datetime):
                        post[ts_field] = format_datetime(raw_value)
                    else:
                        post[ts_field] = format_datetime(parse_datetime(str(raw_value)))
                except (ValueError, TypeError, OverflowError) as exc:
                    logger.warning(
                        "Invalid %s value in %s (%r): %s",
                        ts_field,
                        file_path,
                        raw_value,
                        exc,
                    )
                    warnings.append(
                        f"{file_path}: invalid {ts_field} value; replaced with current time"
                    )
                    post.metadata.pop(ts_field, None)

        if is_edit:
            # Edited post: always update modified_at, fill missing fields
            post["modified_at"] = current_time
            if "created_at" not in post.metadata:
                post["created_at"] = current_time
        else:
            # New post: fill missing timestamps
            if "created_at" not in post.metadata:
                post["created_at"] = current_time
            if "modified_at" not in post.metadata:
                post["modified_at"] = post["created_at"]

        # Backfill title from first heading if not present or not a valid string
        raw_title = post.get("title")
        if not raw_title or not isinstance(raw_title, str) or not raw_title.strip():
            title = extract_title(post.content, file_path)
            post["title"] = title
            # Strip the leading heading from the body if it matches the backfilled title
            new_content = strip_leading_heading(post.content, title)
            if new_content != post.content:
                post.content = new_content

        # Only rewrite when normalization actually changed the content
        normalized = fm.dumps(post) + "\n"
        if normalized == raw:
            continue

        try:
            full_path.write_text(normalized, encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to write normalized front matter for %s: %s", file_path, exc)
            warnings.append(f"{file_path}: failed to write normalized front matter")
            continue

        modified_files.append(file_path)

    return warnings, modified_files
