"""TOML configuration reader/writer for index.toml and labels.toml."""

from __future__ import annotations

import logging
import os
import tempfile
import tomllib
import zoneinfo
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomli_w

logger = logging.getLogger(__name__)


@dataclass
class SiteConfig:
    """Parsed site configuration from index.toml."""

    title: str = "My Blog"
    description: str = ""
    timezone: str = "UTC"
    pages: list[PageConfig] = field(default_factory=list)

    def with_pages(self, pages: list[PageConfig]) -> SiteConfig:
        """Return a copy with the pages list replaced."""
        return SiteConfig(
            title=self.title,
            description=self.description,
            timezone=self.timezone,
            pages=pages,
        )


@dataclass
class PageConfig:
    """A top-level page configuration."""

    id: str
    title: str
    file: str | None = None


@dataclass
class LabelDef:
    """A label definition from labels.toml."""

    id: str
    names: list[str] = field(default_factory=list)
    parents: list[str] = field(default_factory=list)
    is_implicit: bool = False


def parse_site_config(content_dir: Path) -> SiteConfig:
    """Parse index.toml from the content directory.

    Returns safe defaults if the file is missing, corrupt, or structurally invalid.
    """
    index_path = content_dir / "index.toml"
    if not index_path.exists():
        return SiteConfig()

    try:
        data = tomllib.loads(index_path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as exc:
        logger.error("Failed to parse %s, using defaults: %s", index_path, exc)
        return SiteConfig()

    site_data = data.get("site", {})

    pages: list[PageConfig] = []
    try:
        for page_data in data.get("pages", []):
            if "id" not in page_data:
                msg = f"Page entry missing required 'id' field: {page_data}"
                raise ValueError(msg)
            pages.append(
                PageConfig(
                    id=page_data["id"],
                    title=page_data.get("title", page_data["id"].title()),
                    file=page_data.get("file"),
                )
            )
    except (ValueError, TypeError) as exc:
        logger.warning("Invalid page config in %s, using defaults: %s", index_path, exc)
        return SiteConfig()

    raw_timezone = site_data.get("timezone", "UTC")
    try:
        zoneinfo.ZoneInfo(raw_timezone)
        timezone = raw_timezone
    except KeyError:
        logger.warning("Invalid timezone %r in %s, falling back to UTC", raw_timezone, index_path)
        timezone = "UTC"
    except TypeError:
        logger.warning("Invalid timezone %r in %s, falling back to UTC", raw_timezone, index_path)
        timezone = "UTC"
    except ValueError:
        logger.warning("Invalid timezone %r in %s, falling back to UTC", raw_timezone, index_path)
        timezone = "UTC"

    return SiteConfig(
        title=site_data.get("title", "My Blog"),
        description=site_data.get("description", ""),
        timezone=timezone,
        pages=pages,
    )


def parse_labels_config(content_dir: Path) -> dict[str, LabelDef]:
    """Parse labels.toml from the content directory.

    Returns a dict of label_id -> LabelDef. Returns empty dict if the file
    is missing or corrupt.
    """
    labels_path = content_dir / "labels.toml"
    if not labels_path.exists():
        return {}

    try:
        data = tomllib.loads(labels_path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as exc:
        logger.warning("Failed to parse %s, using empty labels: %s", labels_path, exc)
        return {}
    labels_data: dict[str, Any] = data.get("labels", {})

    result: dict[str, LabelDef] = {}
    for label_id, label_info in labels_data.items():
        if not isinstance(label_info, dict):
            logger.warning("Skipping non-dict label entry %r in labels.toml", label_id)
            continue
        names = label_info.get("names", [])
        # Handle both parent (single) and parents (list)
        raw_parent = label_info.get("parent")
        raw_parents = label_info.get("parents", [])
        if not isinstance(raw_parents, list):
            logger.warning("Skipping non-list 'parents' for label %r in labels.toml", label_id)
            raw_parents = []
        parents: list[str] = []
        if raw_parent:
            parents.append(str(raw_parent).removeprefix("#"))
        for p in raw_parents:
            parents.append(str(p).removeprefix("#"))

        result[label_id] = LabelDef(
            id=label_id,
            names=names,
            parents=parents,
        )

    return result


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    """Atomically write *data* to *target* via a temp file in the same directory."""
    fd, tmp_path_str = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        tmp_path.replace(target)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def write_labels_config(content_dir: Path, labels: dict[str, LabelDef]) -> None:
    """Write labels back to labels.toml."""
    _atomic_write_bytes(content_dir / "labels.toml", serialize_labels_config(labels))


def serialize_labels_config(labels: dict[str, LabelDef]) -> bytes:
    """Serialize labels.toml content for a label mapping."""
    labels_data: dict[str, Any] = {}
    for label_id, label_def in labels.items():
        entry: dict[str, Any] = {"names": label_def.names}
        if len(label_def.parents) == 1:
            entry["parent"] = f"#{label_def.parents[0]}"
        elif len(label_def.parents) > 1:
            entry["parents"] = [f"#{p}" for p in label_def.parents]
        labels_data[label_id] = entry

    return tomli_w.dumps({"labels": labels_data}).encode("utf-8")


def write_site_config(content_dir: Path, config: SiteConfig) -> None:
    """Write site configuration back to index.toml."""
    _atomic_write_bytes(content_dir / "index.toml", serialize_site_config(config))


def serialize_site_config(config: SiteConfig) -> bytes:
    """Serialize index.toml content for a site configuration."""
    site_data: dict[str, Any] = {
        "title": config.title,
        "description": config.description,
        "timezone": config.timezone,
    }

    pages_data: list[dict[str, Any]] = []
    for page in config.pages:
        entry: dict[str, Any] = {"id": page.id, "title": page.title}
        if page.file is not None:
            entry["file"] = page.file
        pages_data.append(entry)

    return tomli_w.dumps({"site": site_data, "pages": pages_data}).encode("utf-8")
