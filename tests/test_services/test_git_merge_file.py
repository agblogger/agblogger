"""Tests for GitService.merge_file_content using git merge-file."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from backend.services.git_service import GitService

if TYPE_CHECKING:
    from pathlib import Path


class TestMergeFileContent:
    async def test_clean_merge_non_overlapping(self, tmp_path: Path) -> None:
        git = GitService(tmp_path)
        await git.init_repo()
        base = "line1\nline2\nline3\n"
        ours = "line1 changed\nline2\nline3\n"
        theirs = "line1\nline2\nline3 changed\n"
        merged, conflicted = await git.merge_file_content(base, ours, theirs)
        assert not conflicted
        assert "line1 changed" in merged
        assert "line3 changed" in merged

    async def test_conflict_overlapping(self, tmp_path: Path) -> None:
        git = GitService(tmp_path)
        await git.init_repo()
        base = "line1\noriginal\nline3\n"
        ours = "line1\nours-version\nline3\n"
        theirs = "line1\ntheirs-version\nline3\n"
        _merged, conflicted = await git.merge_file_content(base, ours, theirs)
        assert conflicted

    async def test_identical_changes(self, tmp_path: Path) -> None:
        git = GitService(tmp_path)
        await git.init_repo()
        base = "original\n"
        ours = "same change\n"
        theirs = "same change\n"
        merged, conflicted = await git.merge_file_content(base, ours, theirs)
        assert not conflicted
        assert merged == "same change\n"

    async def test_multiple_conflict_regions(self, tmp_path: Path) -> None:
        git = GitService(tmp_path)
        await git.init_repo()
        base = "para1\n\nseparator\n\npara2\n"
        ours = "para1-ours\n\nseparator\n\npara2-ours\n"
        theirs = "para1-theirs\n\nseparator\n\npara2-theirs\n"
        _merged, conflicted = await git.merge_file_content(base, ours, theirs)
        assert conflicted

    async def test_one_side_unchanged(self, tmp_path: Path) -> None:
        git = GitService(tmp_path)
        await git.init_repo()
        base = "original\n"
        ours = "original\n"
        theirs = "changed\n"
        merged, conflicted = await git.merge_file_content(base, ours, theirs)
        assert not conflicted
        assert merged == "changed\n"

    async def test_temp_files_not_in_content_dir(self, tmp_path: Path) -> None:
        """Temp merge files must not be created inside the git-tracked content_dir."""
        git = GitService(tmp_path)
        await git.init_repo()
        base = "line1\nline2\n"
        ours = "line1 changed\nline2\n"
        theirs = "line1\nline2 changed\n"

        import tempfile as _tempfile

        with patch(
            "backend.services.git_service.tempfile.TemporaryDirectory",
            wraps=_tempfile.TemporaryDirectory,
        ) as mock_td:
            await git.merge_file_content(base, ours, theirs)

        mock_td.assert_called_once()
        kwargs = mock_td.call_args.kwargs
        # dir must not be set to content_dir (should use system temp)
        assert kwargs.get("dir") is None or kwargs["dir"] != tmp_path

    async def test_merge_preserves_non_ascii_content(self, tmp_path: Path) -> None:
        """Merge must correctly handle non-ASCII characters (CJK, emoji, accented)."""
        git = GitService(tmp_path)
        await git.init_repo()
        base = "line1\nline2\nline3\nline4\nline5\n"
        ours = "line1\nline2\n\u4e16\u754c\u4f60\u597d\nline4\nline5\n"
        theirs = "line1\nline2\nline3\nline4\n\u00c9mile \U0001f680\n"
        merged, conflicted = await git.merge_file_content(base, ours, theirs)
        assert not conflicted
        assert "\u4e16\u754c\u4f60\u597d" in merged
        assert "\u00c9mile" in merged
        assert "\U0001f680" in merged

    async def test_raises_on_high_exit_code(self, tmp_path: Path) -> None:
        """Exit codes >= 128 from git merge-file indicate errors, not conflicts."""
        git = GitService(tmp_path)
        await git.init_repo()

        proc = AsyncMock()
        proc.communicate.return_value = (b"", b"fatal: some error")
        proc.returncode = 128

        with patch(
            "backend.services.git_service.asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=proc,
        ):
            with pytest.raises(subprocess.CalledProcessError) as exc_info:
                await git.merge_file_content("base\n", "ours\n", "theirs\n")
            assert exc_info.value.returncode == 128
