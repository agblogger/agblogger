"""Content directory scanner and file manager."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from pathlib import Path

from backend.filesystem.frontmatter import PostData, generate_markdown_excerpt, parse_post
from backend.filesystem.toml_manager import (
    LabelDef,
    SiteConfig,
    parse_labels_config,
    parse_site_config,
)
from backend.utils.slug import is_directory_post_path

logger = logging.getLogger(__name__)

_MAX_POST_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def hash_content(content: str | bytes) -> str:
    """Compute SHA-256 hash of content."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def discover_posts(content_dir: Path) -> list[Path]:
    """Recursively discover canonical directory-backed post files."""
    posts_dir = content_dir / "posts"
    if not posts_dir.exists():
        return []
    return sorted(
        path
        for path in posts_dir.rglob("index.md")
        if is_directory_post_path(str(path.relative_to(content_dir)))
    )


@dataclass
class ContentManager:
    """Manages reading and writing content files."""

    content_dir: Path
    _site_config: SiteConfig | None = field(default=None, repr=False)
    _labels: dict[str, LabelDef] | None = field(default=None, repr=False)

    @property
    def site_config(self) -> SiteConfig:
        """Get site configuration, loading if needed."""
        if self._site_config is None:
            self._site_config = parse_site_config(self.content_dir)
        return self._site_config

    def reload_config(self) -> None:
        """Reload site configuration from disk.

        Parses both configs into local variables first so that a failure
        in either parse leaves the existing state unchanged.
        """
        new_site_config = parse_site_config(self.content_dir)
        new_labels = parse_labels_config(self.content_dir)
        self._site_config = new_site_config
        self._labels = new_labels

    @property
    def labels(self) -> dict[str, LabelDef]:
        """Get label definitions, loading if needed."""
        if self._labels is None:
            self._labels = parse_labels_config(self.content_dir)
        return self._labels

    def scan_posts(self) -> list[PostData]:
        """Scan all posts from the content directory."""
        post_files = discover_posts(self.content_dir)
        posts: list[PostData] = []
        for post_path in post_files:
            rel_path = str(post_path.relative_to(self.content_dir))
            try:
                file_size = post_path.stat().st_size
                if file_size > _MAX_POST_FILE_SIZE:
                    logger.warning(
                        "Skipping post %s: file size %d exceeds limit %d",
                        rel_path,
                        file_size,
                        _MAX_POST_FILE_SIZE,
                    )
                    continue
                raw_content = post_path.read_text(encoding="utf-8")
                if "\x00" in raw_content:
                    logger.warning("Skipping post %s: contains null bytes", rel_path)
                    continue
                post_data = parse_post(
                    raw_content,
                    file_path=rel_path,
                    default_tz=self.site_config.timezone,
                )
            except (
                UnicodeDecodeError,
                ValueError,
                yaml.YAMLError,
                OSError,
                KeyError,
                TypeError,
            ) as exc:
                logger.warning("Skipping post %s due to parse error: %s", rel_path, exc)
                continue
            posts.append(post_data)
        return posts

    def _validate_path(self, rel_path: str) -> Path:
        """Validate that a relative path stays within the content directory.

        Raises ValueError if the resolved path escapes content_dir.
        """
        full_path = (self.content_dir / rel_path).resolve()
        if not full_path.is_relative_to(self.content_dir.resolve()):
            raise ValueError("Path traversal detected")
        return full_path

    def read_post_from_string(
        self, raw_content: str, *, title_override: str | None = None
    ) -> PostData:
        """Parse a post from raw markdown string (for upload)."""
        post_data = parse_post(
            raw_content,
            file_path="",
            default_tz=self.site_config.timezone,
        )
        if title_override and (not post_data.title or post_data.title == "Untitled"):
            post_data.title = title_override
        return post_data

    def read_post(self, rel_path: str) -> PostData | None:
        """Read a single post by relative path."""
        if not is_directory_post_path(rel_path):
            logger.warning("Rejected unsupported post path %s", rel_path)
            return None
        full_path = self._validate_path(rel_path)
        if not full_path.exists() or not full_path.is_file():
            return None
        try:
            file_size = full_path.stat().st_size
            if file_size > _MAX_POST_FILE_SIZE:
                logger.warning(
                    "Post file %s exceeds size limit (%d > %d)",
                    rel_path,
                    file_size,
                    _MAX_POST_FILE_SIZE,
                )
                return None
            raw_content = full_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.error("Failed to read post file %s: %s", rel_path, exc)
            return None
        if "\x00" in raw_content:
            logger.warning("Post file %s contains null bytes", rel_path)
            return None
        try:
            post_data = parse_post(
                raw_content,
                file_path=rel_path,
                default_tz=self.site_config.timezone,
            )
        except (UnicodeDecodeError, ValueError, yaml.YAMLError, KeyError, TypeError) as exc:
            logger.warning("Failed to parse post %s: %s", rel_path, exc)
            return None
        return post_data

    def write_post(self, rel_path: str, post_data: PostData) -> None:
        """Write a post to disk.

        Raises OSError if directory creation or file write fails.
        """
        from backend.filesystem.frontmatter import serialize_post

        if not is_directory_post_path(rel_path):
            raise ValueError(f"Unsupported post path: {rel_path}")
        full_path = self._validate_path(rel_path)
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(serialize_post(post_data), encoding="utf-8")
        except OSError:
            logger.error("Failed to write post to %s", rel_path, exc_info=True)
            raise

    def delete_post(self, rel_path: str, *, delete_assets: bool = False) -> bool:
        """Delete a post from disk.

        Only accepts canonical directory-backed paths (``posts/<slug>/index.md``).
        If *delete_assets* is True, removes the entire directory and any symlinks
        in the parent directory pointing to it.  Otherwise, only the post file
        itself is removed.

        Returns True if the file existed.
        Raises OSError if the deletion fails.
        """
        import shutil

        if not is_directory_post_path(rel_path):
            logger.warning("Rejected delete for unsupported post path %s", rel_path)
            return False

        full_path = self._validate_path(rel_path)
        if not full_path.exists():
            return False

        try:
            if delete_assets:
                # Use the non-resolved path so we can detect if the directory
                # itself is a symlink (resolve() in _validate_path follows symlinks).
                raw_post_dir: Path = (self.content_dir / rel_path).parent
                parent = raw_post_dir.parent
                if raw_post_dir.is_symlink():
                    # The directory is a symlink (created during title rename);
                    # remove only the symlink, not the target it points to.
                    raw_post_dir.unlink()
                else:
                    resolved_dir = raw_post_dir.resolve()
                    # Remove symlinks in the parent directory pointing to this directory
                    try:
                        for item in parent.iterdir():
                            try:
                                if item.is_symlink() and item.resolve() == resolved_dir:
                                    item.unlink()
                            except OSError as exc:
                                logger.warning("Failed to clean up symlink %s: %s", item, exc)
                    except OSError as exc:
                        logger.warning("Failed to iterate parent directory %s: %s", parent, exc)
                    shutil.rmtree(raw_post_dir)
            else:
                full_path.unlink()
        except OSError:
            logger.error("Failed to delete post %s", rel_path, exc_info=True)
            raise
        return True

    def read_page(self, page_id: str) -> str | None:
        """Read a top-level page by its ID."""
        for page_cfg in self.site_config.pages:
            if page_cfg.id == page_id and page_cfg.file:
                try:
                    page_path = self._validate_path(page_cfg.file)
                except ValueError:
                    logger.warning("Rejected unsafe page file path for page %s", page_id)
                    return None
                if page_path.exists():
                    try:
                        return page_path.read_text(encoding="utf-8")
                    except (UnicodeDecodeError, OSError) as exc:
                        logger.warning("Failed to read page %s: %s", page_id, exc)
                        return None
        return None

    def get_markdown_excerpt(self, post_data: PostData) -> str:
        """Generate a markdown excerpt for a post (to be rendered via Pandoc)."""
        return generate_markdown_excerpt(post_data.content)

    def get_plain_excerpt(self, post_data: PostData, max_length: int = 200) -> str:
        """Generate a plain-text excerpt for cross-posting.

        Strips all markdown formatting including links, bold/italic,
        inline code, headings, code blocks, and images.
        """
        lines: list[str] = []
        in_code_block = False
        for line in post_data.content.split("\n"):
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue
            if line.strip().startswith("#"):
                continue
            if line.strip().startswith("!["):
                continue
            stripped = line.strip()
            if stripped:
                stripped = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", stripped)
                stripped = re.sub(r"[*_]+", "", stripped)
                stripped = re.sub(r"`([^`]+)`", r"\1", stripped)
                stripped = re.sub(r"\$[^$]+\$", "", stripped)
                lines.append(stripped)
        text = " ".join(lines)
        if len(text) > max_length:
            text = text[:max_length].rsplit(" ", maxsplit=1)[0] + "..."
        return text
