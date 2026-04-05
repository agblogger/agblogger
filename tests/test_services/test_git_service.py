"""Tests for the git service."""

from __future__ import annotations

import asyncio
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.git_service import GIT_TIMEOUT_SECONDS, GitService

if TYPE_CHECKING:
    from collections.abc import Awaitable
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

    async def test_commit_serializes_concurrent_writers(self, tmp_path: Path) -> None:
        class ControlledGitService(GitService):
            def __init__(self, content_dir: Path) -> None:
                super().__init__(content_dir)
                self.first_add_released = asyncio.Event()
                self.first_add_paused = asyncio.Event()
                self.second_writer_reached_git = asyncio.Event()
                self.first_writer_task: asyncio.Task[str | None] | None = None
                self.pause_commit_add = False

            async def _run(
                self,
                *args: str,
                check: bool = True,
                capture_output: bool = True,
            ) -> subprocess.CompletedProcess[str]:
                result = await super()._run(
                    *args,
                    check=check,
                    capture_output=capture_output,
                )
                current_task = asyncio.current_task()
                if (
                    self.pause_commit_add
                    and args == ("add", "-A")
                    and not self.first_add_paused.is_set()
                ):
                    if current_task is not None:
                        self.first_writer_task = current_task
                    self.first_add_paused.set()
                    await self.first_add_released.wait()
                elif (
                    self.pause_commit_add
                    and self.first_add_paused.is_set()
                    and current_task is not self.first_writer_task
                    and not self.first_add_released.is_set()
                ):
                    self.second_writer_reached_git.set()
                return result

        gs = ControlledGitService(tmp_path)
        (tmp_path / "init.txt").write_text("init")
        await gs.init_repo()
        gs.pause_commit_add = True

        (tmp_path / "first.txt").write_text("first")
        first_writer_task = asyncio.create_task(gs.commit_all("first commit"))
        await asyncio.wait_for(gs.first_add_paused.wait(), timeout=1)

        (tmp_path / "second.txt").write_text("second")
        second_writer_task = asyncio.create_task(gs.commit_all("second commit"))

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(gs.second_writer_reached_git.wait(), timeout=0.1)

        gs.first_add_released.set()
        first_hash, second_hash = await asyncio.gather(first_writer_task, second_writer_task)

        assert first_hash is not None
        assert second_hash is not None
        assert await gs.show_file_at_commit(first_hash, "first.txt") == "first"
        assert await gs.show_file_at_commit(first_hash, "second.txt") is None
        assert await gs.show_file_at_commit(second_hash, "second.txt") == "second"


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
    """Async git subprocesses are launched with timeout enforcement."""

    async def test_run_uses_asyncio_subprocess_with_timeout(self, tmp_path: Path) -> None:
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        await gs.init_repo()

        proc = AsyncMock()
        proc.communicate.return_value = (b"deadbeef\n", b"")
        proc.returncode = 0
        captured_timeout: dict[str, float] = {}

        async def fake_wait_for(awaitable: Awaitable[object], *, timeout: float) -> object:
            captured_timeout["value"] = timeout
            return await awaitable

        with (
            patch(
                "backend.services.git_service.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=proc,
            ) as mock_exec,
            patch("backend.services.git_service.asyncio.wait_for", side_effect=fake_wait_for),
        ):
            result = await gs._run("rev-parse", "HEAD")

        assert result.stdout == "deadbeef\n"
        assert captured_timeout["value"] == GIT_TIMEOUT_SECONDS
        mock_exec.assert_awaited_once()

    async def test_merge_file_uses_asyncio_subprocess_with_timeout(self, tmp_path: Path) -> None:
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        await gs.init_repo()

        proc = AsyncMock()
        proc.communicate.return_value = (b"merged body", b"")
        proc.returncode = 0
        captured_timeout: dict[str, float] = {}

        async def fake_wait_for(awaitable: Awaitable[object], *, timeout: float) -> object:
            captured_timeout["value"] = timeout
            return await awaitable

        with (
            patch(
                "backend.services.git_service.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=proc,
            ) as mock_exec,
            patch("backend.services.git_service.asyncio.wait_for", side_effect=fake_wait_for),
        ):
            merged, conflicted = await gs.merge_file_content("base", "ours", "theirs")

        assert merged == "merged body"
        assert conflicted is False
        assert captured_timeout["value"] == GIT_TIMEOUT_SECONDS
        mock_exec.assert_awaited_once()
        assert mock_exec.await_args.args[:3] == ("git", "merge-file", "-p")

    def test_timeout_constant_is_positive(self) -> None:
        assert GIT_TIMEOUT_SECONDS > 0


class TestRunProcessErrorHandling:
    """_run_process handles errors, cancellation, and resource cleanup correctly."""

    async def test_capture_output_false_returns_empty_stdout(self, tmp_path: Path) -> None:
        """capture_output=False discards stdout and returns empty string."""
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        await gs.init_repo()

        proc = AsyncMock()
        proc.communicate.return_value = (b"output that should be ignored", b"")
        proc.returncode = 0

        with patch(
            "backend.services.git_service.asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=proc,
        ):
            result = await gs._run("status", capture_output=False, check=False)

        assert result.stdout == ""

    async def test_timeout_error_converts_to_subprocess_timeout_expired(
        self, tmp_path: Path
    ) -> None:
        """TimeoutError from asyncio.wait_for is converted to subprocess.TimeoutExpired."""
        gs = GitService(tmp_path)
        proc = AsyncMock()
        proc.returncode = 0  # already exited; no kill needed

        async def raise_timeout(awaitable: Awaitable[object], *, timeout: float) -> object:
            if hasattr(awaitable, "close"):
                awaitable.close()
            raise TimeoutError()

        with (
            patch(
                "backend.services.git_service.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=proc,
            ),
            patch("backend.services.git_service.asyncio.wait_for", side_effect=raise_timeout),
            pytest.raises(subprocess.TimeoutExpired),
        ):
            await gs._run("status")

    async def test_timeout_raises_timeout_expired_when_kill_raises_process_lookup_error(
        self, tmp_path: Path
    ) -> None:
        """subprocess.TimeoutExpired is raised even if process.kill() raises ProcessLookupError."""
        gs = GitService(tmp_path)
        proc = AsyncMock()
        proc.returncode = None
        # kill() is synchronous on asyncio.subprocess.Process; must be a sync mock
        proc.kill = MagicMock(side_effect=ProcessLookupError())

        async def raise_timeout(awaitable: Awaitable[object], *, timeout: float) -> object:
            if hasattr(awaitable, "close"):
                awaitable.close()
            raise TimeoutError()

        with (
            patch(
                "backend.services.git_service.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=proc,
            ),
            patch("backend.services.git_service.asyncio.wait_for", side_effect=raise_timeout),
            pytest.raises(subprocess.TimeoutExpired),
        ):
            await gs._run("status")

    async def test_timeout_waits_for_process_death_with_bounded_timeout(
        self, tmp_path: Path
    ) -> None:
        """After killing on timeout, process.wait() is wrapped in a bounded asyncio.wait_for."""
        gs = GitService(tmp_path)
        proc = AsyncMock()
        proc.returncode = None
        proc.kill = MagicMock()  # kill() is synchronous on asyncio.subprocess.Process
        wait_for_call_count = 0

        async def fake_wait_for(awaitable: Awaitable[object], *, timeout: float) -> object:
            nonlocal wait_for_call_count
            wait_for_call_count += 1
            if wait_for_call_count == 1:
                if hasattr(awaitable, "close"):
                    awaitable.close()
                raise TimeoutError()  # simulate communicate() timing out
            return await awaitable  # let process.wait() complete

        with (
            patch(
                "backend.services.git_service.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=proc,
            ),
            patch("backend.services.git_service.asyncio.wait_for", side_effect=fake_wait_for),
            pytest.raises(subprocess.TimeoutExpired),
        ):
            await gs._run("status")

        assert wait_for_call_count == 2  # once for communicate, once for process.wait

    async def test_cancelled_error_kills_subprocess(self, tmp_path: Path) -> None:
        """CancelledError propagation kills the subprocess before re-raising."""
        gs = GitService(tmp_path)
        proc = AsyncMock()
        proc.returncode = None
        proc.kill = MagicMock()  # kill() is synchronous on asyncio.subprocess.Process

        async def raise_cancelled(awaitable: Awaitable[object], *, timeout: float) -> object:
            if hasattr(awaitable, "close"):
                awaitable.close()
            raise asyncio.CancelledError()

        with (
            patch(
                "backend.services.git_service.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=proc,
            ),
            patch(
                "backend.services.git_service.asyncio.wait_for",
                side_effect=raise_cancelled,
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            await gs._run("status")

        proc.kill.assert_called_once()


class TestTryCommitTimeout:
    """Issue 2: try_commit should catch TimeoutExpired in addition to CalledProcessError."""

    async def test_try_commit_catches_timeout(self, tmp_path: Path) -> None:
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        await gs.init_repo()

        timeout_exc = subprocess.TimeoutExpired(cmd=["git", "commit"], timeout=30)
        with patch.object(gs, "commit_all", new_callable=AsyncMock, side_effect=timeout_exc):
            result = await gs.try_commit("test commit")

        assert result is None
