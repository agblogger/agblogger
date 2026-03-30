"""Unit tests for ContentSizeTracker."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import patch

from backend.services.storage_quota import ContentSizeTracker

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class TestRecompute:
    def test_compute_from_empty_directory(self, tmp_path: Path) -> None:
        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=None)
        tracker.recompute()
        assert tracker.current_usage == 0

    def test_compute_sums_file_sizes(self, tmp_path: Path) -> None:
        (tmp_path / "post1").mkdir()
        (tmp_path / "post1" / "index.md").write_bytes(b"hello")  # 5 bytes
        (tmp_path / "post1" / "image.png").write_bytes(b"x" * 100)  # 100 bytes
        (tmp_path / "post2").mkdir()
        (tmp_path / "post2" / "index.md").write_bytes(b"world!")  # 6 bytes

        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=None)
        tracker.recompute()
        assert tracker.current_usage == 111

    def test_recompute_skips_symlinks(self, tmp_path: Path) -> None:
        real_file = tmp_path / "real.md"
        real_file.write_bytes(b"a" * 50)
        link = tmp_path / "link.md"
        link.symlink_to(real_file)

        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=None)
        tracker.recompute()
        # Only the real file should be counted
        assert tracker.current_usage == 50

    def test_recompute_skips_hidden_runtime_state(self, tmp_path: Path) -> None:
        (tmp_path / "index.toml").write_bytes(b"x" * 50)
        hidden_dir = tmp_path / ".git"
        hidden_dir.mkdir()
        (hidden_dir / "objects.bin").write_bytes(b"y" * 100)

        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=None)
        tracker.recompute()

        assert tracker.current_usage == 50

    def test_recompute_resets_to_actual(self, tmp_path: Path) -> None:
        """Drift in the counter is corrected when recompute is called."""
        (tmp_path / "a.md").write_bytes(b"x" * 200)

        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=None)
        tracker.recompute()
        assert tracker.current_usage == 200

        # Simulate drift by adjusting the counter directly
        tracker.adjust(9999)
        assert tracker.current_usage == 200 + 9999

        # recompute should reset to actual filesystem state
        tracker.recompute()
        assert tracker.current_usage == 200

    def test_recompute_logs_usage_when_max_size_set(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        (tmp_path / "file.md").write_bytes(b"x" * 50)
        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=1000)

        with caplog.at_level(logging.INFO, logger="backend.services.storage_quota"):
            tracker.recompute()

        assert any("50" in record.message for record in caplog.records)

    def test_recompute_handles_oserror_on_rglob(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """If rglob raises OSError, usage is preserved (fail closed) and an error is logged."""
        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=None)
        tracker.adjust(1000)
        assert tracker.current_usage == 1000

        with (
            patch.object(
                type(tracker._content_dir), "rglob", side_effect=OSError("permission denied")
            ),
            caplog.at_level(logging.ERROR, logger="backend.services.storage_quota"),
        ):
            tracker.recompute()

        # Usage must be preserved — not reset to 0 — so quota remains enforced
        assert tracker.current_usage == 1000
        assert any("Failed to walk" in record.message for record in caplog.records)


class TestCheck:
    def test_check_no_limit_always_passes(self, tmp_path: Path) -> None:
        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=None)
        tracker.recompute()
        assert tracker.check(0) is True
        assert tracker.check(10**9) is True

    def test_check_within_limit_passes(self, tmp_path: Path) -> None:
        (tmp_path / "file.md").write_bytes(b"x" * 100)
        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=1000)
        tracker.recompute()
        assert tracker.check(800) is True

    def test_check_exceeding_limit_fails(self, tmp_path: Path) -> None:
        (tmp_path / "file.md").write_bytes(b"x" * 100)
        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=1000)
        tracker.recompute()
        assert tracker.check(901) is False

    def test_check_at_exact_limit_passes(self, tmp_path: Path) -> None:
        (tmp_path / "file.md").write_bytes(b"x" * 100)
        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=1000)
        tracker.recompute()
        # 100 + 900 == 1000 exactly
        assert tracker.check(900) is True


class TestTrackedFiles:
    def test_file_size_ignores_hidden_paths(self, tmp_path: Path) -> None:
        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=None)
        hidden_dir = tmp_path / ".git"
        hidden_dir.mkdir()
        hidden_file = hidden_dir / "objects.bin"
        hidden_file.write_bytes(b"x" * 100)

        assert tracker.file_size(hidden_file) == 0

    def test_delta_for_paths_uses_current_tracked_sizes(self, tmp_path: Path) -> None:
        tracked_file = tmp_path / "index.toml"
        tracked_file.write_bytes(b"x" * 50)
        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=None)

        assert tracker.delta_for_paths({tracked_file: 80}) == 30
        assert tracker.delta_for_paths({tracked_file: 20}) == -30


class TestAdjust:
    def test_adjust_increments(self, tmp_path: Path) -> None:
        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=None)
        tracker.recompute()
        tracker.adjust(500)
        assert tracker.current_usage == 500

    def test_adjust_decrements(self, tmp_path: Path) -> None:
        (tmp_path / "file.md").write_bytes(b"x" * 300)
        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=None)
        tracker.recompute()
        tracker.adjust(-100)
        assert tracker.current_usage == 200

    def test_adjust_does_not_go_negative(self, tmp_path: Path) -> None:
        (tmp_path / "file.md").write_bytes(b"x" * 50)
        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=None)
        tracker.recompute()
        tracker.adjust(-9999)
        assert tracker.current_usage == 0
