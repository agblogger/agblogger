"""Content storage quota tracker.

Tracks total byte usage under the content directory so API handlers can
enforce a configurable size limit before accepting new uploads or posts.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class ContentSizeTracker:
    """Track cumulative file-size usage under a content directory.

    Designed for asyncio's single-threaded cooperative model. All public
    methods are synchronous with no await points, so no interleaving can
    occur under normal use. Do NOT call from multiple OS threads without
    external synchronization.

    On recompute() failure, usage resets to 0 (quota unenforced until next
    successful recompute).
    """

    def __init__(self, *, content_dir: Path, max_size: int | None) -> None:
        self._content_dir = content_dir
        self._max_size = max_size
        self._usage: int = 0

    @property
    def current_usage(self) -> int:
        """Current tracked byte usage."""
        return self._usage

    def recompute(self) -> None:
        """Walk content_dir, sum file sizes (skipping symlinks).

        Catches individual OSError on stat() calls (skips unreadable files).
        Catches top-level OSError on rglob (logs the error, sets usage to 0).
        Logs usage info at INFO level when max_size is configured.
        """
        try:
            paths = list(self._content_dir.rglob("*"))
        except OSError as exc:
            logger.error("Failed to walk content directory %s: %s", self._content_dir, exc)
            self._usage = 0
            return

        total = 0
        for path in paths:
            if path.is_file() and not path.is_symlink():
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

    def adjust(self, delta: int) -> None:
        """Add delta to the tracked counter. Clamps to 0 (never goes negative)."""
        self._usage = max(0, self._usage + delta)
