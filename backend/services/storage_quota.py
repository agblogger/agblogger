"""Content storage quota tracker.

Tracks managed, non-hidden content files under the content directory so API
handlers can enforce a configurable size limit before accepting new writes.
Hidden runtime state such as ``.git`` is intentionally excluded.
"""

from __future__ import annotations

import logging
import stat as _stat
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class QuotaExceededError(Exception):
    """Raised when a write would exceed the storage quota."""


class ContentSizeTracker:
    """Track cumulative file-size usage for managed files under a content directory.

    Designed for asyncio's single-threaded cooperative model. All public
    methods are synchronous with no await points, so no interleaving can
    occur under normal use. Do NOT call from multiple OS threads without
    external synchronization.

    recompute() performs blocking filesystem I/O (rglob + stat) and should
    only be called during startup or other infrequent operations.
    When called via asyncio.to_thread(), the caller must hold the content write lock
    to ensure exclusive access.
    """

    def __init__(self, *, content_dir: Path, max_size: int | None) -> None:
        self._content_dir: Final = content_dir
        self._max_size: Final = max_size
        self._usage: int = 0

    @property
    def current_usage(self) -> int:
        """Current tracked byte usage."""
        return self._usage

    def _is_tracked_path(self, path: Path) -> bool:
        """Return True when *path* is a managed, non-hidden path under content_dir."""
        try:
            relative_parts = path.relative_to(self._content_dir).parts
        except ValueError:
            return False
        return bool(relative_parts) and all(not part.startswith(".") for part in relative_parts)

    def file_size(self, path: Path) -> int:
        """Return the tracked size of a managed file path, or 0 when absent/untracked."""
        if not self._is_tracked_path(path):
            return 0
        try:
            st = path.lstat()
            if _stat.S_ISREG(st.st_mode):
                return st.st_size
        except OSError as exc:
            logger.warning("Failed to stat tracked path %s: %s", path, exc)
        return 0

    def delta_for_paths(self, updated_sizes: dict[Path, int | None]) -> int:
        """Return the net tracked-byte delta for a set of final file sizes.

        A value of None means the file will be absent (treated as size 0).
        """
        delta = 0
        for path, new_size in updated_sizes.items():
            old_size = self.file_size(path)
            delta += (0 if new_size is None else new_size) - old_size
        return delta

    def recompute(self) -> None:
        """Walk content_dir, sum tracked file sizes (skipping hidden paths and symlinks).

        Catches individual OSError on stat() calls (skips unreadable files).
        Catches top-level OSError on rglob (logs the error, preserves previous
        usage — fails closed rather than resetting to 0).
        Logs usage info at INFO level when max_size is configured.
        """
        try:
            paths = list(self._content_dir.rglob("*"))
        except OSError as exc:
            logger.error("Failed to walk content directory %s: %s", self._content_dir, exc)
            # Preserve previous usage — fail closed rather than fail open
            return

        total = 0
        for path in paths:
            if self._is_tracked_path(path) and path.is_file() and not path.is_symlink():
                try:
                    total += path.stat().st_size
                except OSError as exc:
                    logger.warning("Skipping unreadable file %s: %s", path, exc)

        self._usage = total

        if self._max_size is not None:
            pct = (self._usage / self._max_size * 100) if self._max_size > 0 else 0.0
            logger.info(
                "Content storage: %d bytes used of %d limit (%.1f%%)",
                self._usage,
                self._max_size,
                pct,
            )

    def check(self, incoming_bytes: int) -> bool:
        """Return True if current_usage + incoming_bytes fits within max_size.

        Always returns True when max_size is None (unlimited).
        """
        if self._max_size is None:
            return True
        return self._usage + incoming_bytes <= self._max_size

    def require_quota(self, delta: int) -> None:
        """Raise QuotaExceededError if a positive delta would push usage over the limit.

        Negative deltas (deletions/shrinkages) are always allowed.
        A zero delta is a no-op: it neither consumes space nor triggers a limit check.
        """
        if delta > 0 and not self.check(delta):
            raise QuotaExceededError()

    def adjust(self, delta: int) -> None:
        """Add delta to the tracked counter. Clamps to 0 (never goes negative)."""
        self._usage = max(0, self._usage + delta)
