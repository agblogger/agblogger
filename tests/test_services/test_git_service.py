"""Tests for the git service."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from backend.services.git_service import GIT_TIMEOUT_SECONDS, GitService

if TYPE_CHECKING:
    from pathlib import Path


class TestGitServiceInit:
    async def test_init_creates_repo(self, tmp_path: Path) -> None:
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        await gs.init_repo()
        assert (tmp_path / ".git").is_dir()

    async def test_init_is_idempotent(self, tmp_path: Path) -> None:
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        await gs.init_repo()
        head1 = await gs.head_commit()
        await gs.init_repo()
        head2 = await gs.head_commit()
        assert head1 == head2

    async def test_init_commits_existing_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("aaa")
        (tmp_path / "b.txt").write_text("bbb")
        gs = GitService(tmp_path)
        await gs.init_repo()
        head = await gs.head_commit()
        assert head is not None
        assert await gs.show_file_at_commit(head, "a.txt") == "aaa"
        assert await gs.show_file_at_commit(head, "b.txt") == "bbb"


class TestGitServiceCommit:
    async def test_commit_returns_hash(self, tmp_path: Path) -> None:
        gs = GitService(tmp_path)
        (tmp_path / "init.txt").write_text("init")
        await gs.init_repo()
        (tmp_path / "new.txt").write_text("content")
        result = await gs.commit_all("add new file")
        assert result is not None
        assert len(result) == 40

    async def test_commit_returns_none_when_clean(self, tmp_path: Path) -> None:
        gs = GitService(tmp_path)
        (tmp_path / "init.txt").write_text("init")
        await gs.init_repo()
        result = await gs.commit_all("nothing changed")
        assert result is None

    async def test_commit_stages_new_files(self, tmp_path: Path) -> None:
        gs = GitService(tmp_path)
        (tmp_path / "init.txt").write_text("init")
        await gs.init_repo()
        (tmp_path / "added.txt").write_text("new content")
        commit_hash = await gs.commit_all("add file")
        assert commit_hash is not None
        assert await gs.show_file_at_commit(commit_hash, "added.txt") == "new content"

    async def test_commit_stages_deleted_files(self, tmp_path: Path) -> None:
        gs = GitService(tmp_path)
        (tmp_path / "to_delete.txt").write_text("will be deleted")
        await gs.init_repo()
        old_hash = await gs.head_commit()
        assert old_hash is not None
        (tmp_path / "to_delete.txt").unlink()
        new_hash = await gs.commit_all("delete file")
        assert new_hash is not None
        assert await gs.show_file_at_commit(old_hash, "to_delete.txt") == "will be deleted"
        assert await gs.show_file_at_commit(new_hash, "to_delete.txt") is None


class TestGitServiceShow:
    async def test_show_at_current_commit(self, tmp_path: Path) -> None:
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("v1")
        await gs.init_repo()
        head = await gs.head_commit()
        assert head is not None
        assert await gs.show_file_at_commit(head, "file.txt") == "v1"

    async def test_show_nonexistent_file(self, tmp_path: Path) -> None:
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("v1")
        await gs.init_repo()
        head = await gs.head_commit()
        assert head is not None
        assert await gs.show_file_at_commit(head, "nonexistent.txt") is None

    async def test_show_at_old_commit(self, tmp_path: Path) -> None:
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("v1")
        await gs.init_repo()
        old_hash = await gs.head_commit()
        assert old_hash is not None
        (tmp_path / "file.txt").write_text("v2")
        await gs.commit_all("update")
        head = await gs.head_commit()
        assert head is not None
        assert await gs.show_file_at_commit(old_hash, "file.txt") == "v1"
        assert await gs.show_file_at_commit(head, "file.txt") == "v2"

    async def test_commit_exists(self, tmp_path: Path) -> None:
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("v1")
        await gs.init_repo()
        head = await gs.head_commit()
        assert head is not None
        assert await gs.commit_exists(head) is True
        assert await gs.commit_exists("0000000000000000000000000000000000000000") is False
        assert await gs.commit_exists("not-a-hash") is False


class TestCommitHashValidation:
    """Issue 1: commit_hash input validation."""

    async def test_commit_exists_rejects_flag_like_input(self, tmp_path: Path) -> None:
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        await gs.init_repo()
        assert await gs.commit_exists("--flag") is False

    async def test_show_file_rejects_flag_like_input(self, tmp_path: Path) -> None:
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        await gs.init_repo()
        assert await gs.show_file_at_commit("--flag", "file.txt") is None

    async def test_commit_exists_rejects_uppercase_hex(self, tmp_path: Path) -> None:
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        await gs.init_repo()
        assert await gs.commit_exists("ABCD1234") is False

    async def test_commit_exists_rejects_short_input(self, tmp_path: Path) -> None:
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        await gs.init_repo()
        assert await gs.commit_exists("abc") is False


class TestHeadCommitEmptyRepo:
    """Issue 11: head_commit on empty repo."""

    async def test_head_commit_returns_none_on_empty_repo(self, tmp_path: Path) -> None:
        # Use GitService._run to init a bare git repo without committing
        fresh_dir = tmp_path / "fresh"
        fresh_dir.mkdir()
        fresh_gs = GitService(fresh_dir)
        await fresh_gs._run("init")
        assert await fresh_gs.head_commit() is None


class TestGitTimeout:
    """subprocess.run is called with timeout kwarg."""

    async def test_run_passes_timeout(self, tmp_path: Path) -> None:
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        await gs.init_repo()

        with patch("subprocess.run", wraps=__import__("subprocess").run) as mock_run:
            await gs.head_commit()
        # Verify timeout was passed
        call_kwargs = mock_run.call_args.kwargs
        assert "timeout" in call_kwargs
        assert call_kwargs["timeout"] == GIT_TIMEOUT_SECONDS

    async def test_merge_file_passes_timeout(self, tmp_path: Path) -> None:
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        await gs.init_repo()

        with patch("subprocess.run", wraps=__import__("subprocess").run) as mock_run:
            await gs.merge_file_content("base", "ours", "theirs")
        # The merge_file subprocess.run call should include timeout
        merge_calls = [c for c in mock_run.call_args_list if "merge-file" in str(c)]
        assert merge_calls, "Expected at least one subprocess.run call for git merge-file"
        for call in merge_calls:
            assert "timeout" in call.kwargs
            assert call.kwargs["timeout"] == GIT_TIMEOUT_SECONDS

    def test_timeout_constant_is_positive(self) -> None:
        assert GIT_TIMEOUT_SECONDS > 0
