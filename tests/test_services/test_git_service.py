"""Tests for the git service."""

from __future__ import annotations

import asyncio
import logging
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.git_service import (
    _POST_KILL_WAIT_SECONDS,
    GIT_TIMEOUT_SECONDS,
    GitService,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Coroutine
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
    """Async git subprocesses enforce timeouts and clean up on cancellation."""

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

    async def test_cancelled_run_waits_for_process_exit_before_raising(
        self, tmp_path: Path
    ) -> None:
        gs = GitService(tmp_path)

        class ControlledProcess:
            def __init__(self) -> None:
                self.returncode: int | None = None
                self.communicate_started = asyncio.Event()
                self.wait_started = asyncio.Event()
                self.allow_exit = asyncio.Event()
                self.kill_called = False

            async def communicate(self) -> tuple[bytes, bytes]:
                self.communicate_started.set()
                await asyncio.Future()
                raise AssertionError("unreachable")

            async def wait(self) -> int:
                self.wait_started.set()
                await self.allow_exit.wait()
                self.returncode = -9
                return self.returncode

            def kill(self) -> None:
                self.kill_called = True

        proc = ControlledProcess()

        with patch(
            "backend.services.git_service.asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=proc,
        ):
            task = asyncio.create_task(
                gs._run_process(["git", "status"], cwd=tmp_path, check=False)
            )
            await asyncio.wait_for(proc.communicate_started.wait(), timeout=1)
            task.cancel()

            await asyncio.wait_for(proc.wait_started.wait(), timeout=1)
            assert proc.kill_called is True
            assert task.done() is False

            proc.allow_exit.set()

            with pytest.raises(asyncio.CancelledError):
                await task

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
        assert mock_exec.await_args is not None
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
        proc.communicate.return_value = (None, b"")
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
        proc.kill = MagicMock()

        async def raise_timeout(
            awaitable: Coroutine[object, object, object], *, timeout: float
        ) -> object:
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

        proc.kill.assert_not_called()

    async def test_timeout_raises_timeout_expired_when_kill_raises_process_lookup_error(
        self, tmp_path: Path
    ) -> None:
        """subprocess.TimeoutExpired is raised even if process.kill() raises ProcessLookupError."""
        gs = GitService(tmp_path)
        proc = AsyncMock()
        proc.returncode = None
        # kill() is synchronous on asyncio.subprocess.Process; must be a sync mock
        proc.kill = MagicMock(side_effect=ProcessLookupError())

        async def raise_timeout(
            awaitable: Coroutine[object, object, object], *, timeout: float
        ) -> object:
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
        proc.kill = MagicMock()
        captured_timeouts: list[float] = []

        async def fake_wait_for(
            awaitable: Coroutine[object, object, object], *, timeout: float
        ) -> object:
            captured_timeouts.append(timeout)
            if len(captured_timeouts) == 1:
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

        assert len(captured_timeouts) == 2  # once for communicate, once for process.wait
        assert captured_timeouts[1] == _POST_KILL_WAIT_SECONDS

    async def test_cancelled_error_kills_subprocess(self, tmp_path: Path) -> None:
        """CancelledError propagation kills the subprocess before re-raising."""
        gs = GitService(tmp_path)
        proc = AsyncMock()
        proc.returncode = None
        proc.kill = MagicMock()

        async def raise_cancelled(
            awaitable: Coroutine[object, object, object], *, timeout: float
        ) -> object:
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

    async def test_leaked_handle_logged_when_post_kill_wait_times_out(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When process.wait() times out after kill, an error about a leaked handle is logged."""
        gs = GitService(tmp_path)
        proc = AsyncMock()
        proc.returncode = None
        proc.kill = MagicMock()

        async def fake_wait_for(
            awaitable: Coroutine[object, object, object], *, timeout: float
        ) -> object:
            awaitable.close()
            raise TimeoutError()  # both communicate and wait time out

        with (
            patch(
                "backend.services.git_service.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=proc,
            ),
            patch("backend.services.git_service.asyncio.wait_for", side_effect=fake_wait_for),
            caplog.at_level(logging.ERROR, logger="backend.services.git_service"),
            pytest.raises(subprocess.TimeoutExpired),
        ):
            await gs._run("status")

        assert "handle leaked" in caplog.text

    async def test_returncode_none_after_communicate_raises_runtime_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """RuntimeError is raised if returncode is None after communicate() succeeds."""
        gs = GitService(tmp_path)
        proc = AsyncMock()
        proc.communicate.return_value = (b"output", b"")
        proc.returncode = None  # stays None — simulates broken asyncio

        with (
            patch(
                "backend.services.git_service.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=proc,
            ),
            caplog.at_level(logging.ERROR, logger="backend.services.git_service"),
            pytest.raises(RuntimeError, match="finished without a return code"),
        ):
            await gs._run("status", check=False)

        assert "finished without a return code" in caplog.text

    async def test_non_utf8_output_decoded_with_replacement_and_logged(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Non-UTF-8 bytes in stdout/stderr are replaced with U+FFFD and logged."""
        gs = GitService(tmp_path)
        proc = AsyncMock()
        proc.communicate.return_value = (b"\xff\xfe invalid", b"\x80 stderr")
        proc.returncode = 0

        with (
            patch(
                "backend.services.git_service.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=proc,
            ),
            caplog.at_level(logging.WARNING, logger="backend.services.git_service"),
        ):
            result = await gs._run("status", check=False)

        assert "\ufffd" in result.stdout
        assert "\ufffd" in result.stderr
        assert "Non-UTF-8 bytes in stdout" in caplog.text
        assert "Non-UTF-8 bytes in stderr" in caplog.text

    async def test_check_true_raises_called_process_error_with_correct_attrs(
        self, tmp_path: Path
    ) -> None:
        """check=True raises CalledProcessError with returncode, output, and stderr."""
        gs = GitService(tmp_path)
        proc = AsyncMock()
        proc.communicate.return_value = (b"some output", b"some error")
        proc.returncode = 1

        with (
            patch(
                "backend.services.git_service.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=proc,
            ),
            pytest.raises(subprocess.CalledProcessError) as exc_info,
        ):
            await gs._run("status")

        assert exc_info.value.returncode == 1
        assert exc_info.value.output == "some output"
        assert exc_info.value.stderr == "some error"

    async def test_capture_output_false_still_populates_stderr(self, tmp_path: Path) -> None:
        """capture_output=False discards stdout but preserves stderr."""
        gs = GitService(tmp_path)
        proc = AsyncMock()
        proc.communicate.return_value = (None, b"stderr content")
        proc.returncode = 0

        with patch(
            "backend.services.git_service.asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=proc,
        ):
            result = await gs._run("status", capture_output=False, check=False)

        assert result.stdout == ""
        assert result.stderr == "stderr content"

    async def test_capture_output_false_uses_devnull_for_stdout(self, tmp_path: Path) -> None:
        """capture_output=False creates subprocess with stdout=DEVNULL."""
        gs = GitService(tmp_path)
        proc = AsyncMock()
        proc.communicate.return_value = (None, b"")
        proc.returncode = 0

        with patch(
            "backend.services.git_service.asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=proc,
        ) as mock_exec:
            await gs._run("status", capture_output=False, check=False)

        assert mock_exec.await_args is not None
        assert mock_exec.await_args.kwargs["stdout"] == asyncio.subprocess.DEVNULL

    async def test_capture_output_true_uses_pipe_for_stdout(self, tmp_path: Path) -> None:
        """capture_output=True (default) creates subprocess with stdout=PIPE."""
        gs = GitService(tmp_path)
        proc = AsyncMock()
        proc.communicate.return_value = (b"output", b"")
        proc.returncode = 0

        with patch(
            "backend.services.git_service.asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=proc,
        ) as mock_exec:
            await gs._run("status", check=False)

        assert mock_exec.await_args is not None
        assert mock_exec.await_args.kwargs["stdout"] == asyncio.subprocess.PIPE

    async def test_cancelled_error_skips_kill_when_process_already_exited(
        self, tmp_path: Path
    ) -> None:
        """BaseException handler does not call kill() if returncode is already set."""
        gs = GitService(tmp_path)
        proc = AsyncMock()
        proc.returncode = 0  # already exited
        proc.kill = MagicMock()

        async def raise_cancelled(
            awaitable: Coroutine[object, object, object], *, timeout: float
        ) -> object:
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

        proc.kill.assert_not_called()

    async def test_base_exception_handler_suppresses_kill_failure(self, tmp_path: Path) -> None:
        """If _kill_and_wait_for_process_exit raises, the original exception still propagates."""
        gs = GitService(tmp_path)
        proc = AsyncMock()
        proc.returncode = None
        proc.kill = MagicMock()

        call_count = 0

        async def raise_cancelled_then_timeout(
            awaitable: Coroutine[object, object, object], *, timeout: float
        ) -> object:
            nonlocal call_count
            call_count += 1
            awaitable.close()
            if call_count == 1:
                raise asyncio.CancelledError()  # original exception from communicate
            raise TimeoutError()  # kill_and_wait's process.wait() times out

        with (
            patch(
                "backend.services.git_service.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=proc,
            ),
            patch(
                "backend.services.git_service.asyncio.wait_for",
                side_effect=raise_cancelled_then_timeout,
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            await gs._run("status")

        proc.kill.assert_called_once()

    async def test_non_utf8_stderr_logged_with_capture_output_false(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Non-UTF-8 bytes in stderr trigger a warning even when capture_output=False."""
        gs = GitService(tmp_path)
        proc = AsyncMock()
        proc.communicate.return_value = (None, b"\x80 bad stderr")
        proc.returncode = 0

        with (
            patch(
                "backend.services.git_service.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=proc,
            ),
            caplog.at_level(logging.WARNING, logger="backend.services.git_service"),
        ):
            result = await gs._run("status", capture_output=False, check=False)

        assert "\ufffd" in result.stderr
        assert "Non-UTF-8 bytes in stderr" in caplog.text


class TestTryCommitErrorHandling:
    """try_commit catches subprocess errors and logs them instead of raising."""

    async def test_try_commit_catches_timeout_and_logs(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        await gs.init_repo()

        timeout_exc = subprocess.TimeoutExpired(cmd=["git", "commit"], timeout=30)
        with (
            patch.object(gs, "commit_all", new_callable=AsyncMock, side_effect=timeout_exc),
            caplog.at_level(logging.ERROR, logger="backend.services.git_service"),
        ):
            result = await gs.try_commit("test commit")

        assert result is None
        assert "timed out" in caplog.text

    async def test_try_commit_catches_called_process_error_and_logs(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        await gs.init_repo()

        cpe = subprocess.CalledProcessError(1, "git commit", output="", stderr="index.lock exists")
        with (
            patch.object(gs, "commit_all", new_callable=AsyncMock, side_effect=cpe),
            caplog.at_level(logging.ERROR, logger="backend.services.git_service"),
        ):
            result = await gs.try_commit("test commit")

        assert result is None
        assert "exit 1" in caplog.text
        assert "index.lock exists" in caplog.text

    async def test_try_commit_catches_os_error_and_logs(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """OSError (e.g. FileNotFoundError when git binary is missing) is caught and logged."""
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        await gs.init_repo()

        with (
            patch.object(
                gs,
                "commit_all",
                new_callable=AsyncMock,
                side_effect=FileNotFoundError("git: not found"),
            ),
            caplog.at_level(logging.ERROR, logger="backend.services.git_service"),
        ):
            result = await gs.try_commit("test commit")

        assert result is None
        assert "git: not found" in caplog.text


class TestFileNotFoundPropagation:
    """FileNotFoundError from create_subprocess_exec propagates through _run_process."""

    async def test_file_not_found_propagates_from_create_subprocess_exec(
        self, tmp_path: Path
    ) -> None:
        gs = GitService(tmp_path)

        with (
            patch(
                "backend.services.git_service.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                side_effect=FileNotFoundError("No such file or directory: 'git'"),
            ),
            pytest.raises(FileNotFoundError, match="git"),
        ):
            await gs._run("status")


class TestTimeoutHandlerKillFailure:
    """Timeout handler logs and continues when kill-and-wait raises."""

    async def test_timeout_handler_logs_kill_failure_and_raises_timeout_expired(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """If _kill_and_wait raises during timeout cleanup, TimeoutExpired is still raised."""
        gs = GitService(tmp_path)
        proc = AsyncMock()
        proc.returncode = None
        proc.kill = MagicMock()
        call_count = 0

        async def fake_wait_for(
            awaitable: Coroutine[object, object, object], *, timeout: float
        ) -> object:
            nonlocal call_count
            call_count += 1
            awaitable.close()
            if call_count == 1:
                raise TimeoutError()  # communicate() times out
            raise RuntimeError("broken event loop")  # process.wait() fails unexpectedly

        with (
            patch(
                "backend.services.git_service.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=proc,
            ),
            patch("backend.services.git_service.asyncio.wait_for", side_effect=fake_wait_for),
            caplog.at_level(logging.WARNING, logger="backend.services.git_service"),
            pytest.raises(subprocess.TimeoutExpired),
        ):
            await gs._run("status")

        assert "Failed to reap subprocess" in caplog.text


class TestBaseExceptionHandlerKillLogging:
    """BaseException handler logs kill failures instead of silently suppressing them."""

    async def test_base_exception_handler_logs_kill_failure(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """If _kill_and_wait raises during cleanup, the failure is logged."""
        gs = GitService(tmp_path)
        proc = AsyncMock()
        proc.returncode = None
        proc.kill = MagicMock()
        call_count = 0

        async def fake_wait_for(
            awaitable: Coroutine[object, object, object], *, timeout: float
        ) -> object:
            nonlocal call_count
            call_count += 1
            awaitable.close()
            if call_count == 1:
                raise asyncio.CancelledError()  # original exception from communicate
            raise RuntimeError("broken event loop")  # process.wait() fails unexpectedly

        with (
            patch(
                "backend.services.git_service.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=proc,
            ),
            patch(
                "backend.services.git_service.asyncio.wait_for",
                side_effect=fake_wait_for,
            ),
            caplog.at_level(logging.WARNING, logger="backend.services.git_service"),
            pytest.raises(asyncio.CancelledError),
        ):
            await gs._run("status")

        assert "Failed to kill subprocess" in caplog.text


class TestHeadCommitLogging:
    """head_commit logs unexpected git exit codes."""

    async def test_head_commit_logs_unexpected_exit_code(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        await gs.init_repo()

        bad_result = subprocess.CompletedProcess(
            ["git", "rev-parse", "HEAD"], returncode=1, stdout="", stderr="unknown error"
        )
        with (
            patch.object(gs, "_run", new_callable=AsyncMock, return_value=bad_result),
            caplog.at_level(logging.WARNING, logger="backend.services.git_service"),
        ):
            result = await gs.head_commit()

        assert result is None
        assert "Unexpected git rev-parse exit code 1" in caplog.text

    async def test_head_commit_does_not_log_for_exit_128(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Exit 128 (no commits) is expected and should not produce a warning."""
        gs = GitService(tmp_path)

        no_commits_result = subprocess.CompletedProcess(
            ["git", "rev-parse", "HEAD"],
            returncode=128,
            stdout="",
            stderr="fatal: bad default revision 'HEAD'",
        )
        with (
            patch.object(gs, "_run", new_callable=AsyncMock, return_value=no_commits_result),
            caplog.at_level(logging.WARNING, logger="backend.services.git_service"),
        ):
            result = await gs.head_commit()

        assert result is None
        assert "Unexpected" not in caplog.text


class TestCommitExistsLogging:
    """commit_exists logs unexpected git exit codes."""

    async def test_commit_exists_logs_unexpected_exit_code(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        await gs.init_repo()

        bad_result = subprocess.CompletedProcess(
            ["git", "cat-file", "-t", "abcd1234"], returncode=1, stdout="", stderr="unknown error"
        )
        with (
            patch.object(gs, "_run", new_callable=AsyncMock, return_value=bad_result),
            caplog.at_level(logging.WARNING, logger="backend.services.git_service"),
        ):
            result = await gs.commit_exists("abcd1234")

        assert result is False
        assert "Unexpected git cat-file exit code 1" in caplog.text

    async def test_commit_exists_does_not_log_for_exit_128(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Exit 128 (object not found) is expected and should not produce a warning."""
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        await gs.init_repo()

        not_found_result = subprocess.CompletedProcess(
            ["git", "cat-file", "-t", "abcd1234"],
            returncode=128,
            stdout="",
            stderr="fatal: could not get object info",
        )
        with (
            patch.object(gs, "_run", new_callable=AsyncMock, return_value=not_found_result),
            caplog.at_level(logging.WARNING, logger="backend.services.git_service"),
        ):
            result = await gs.commit_exists("abcd1234")

        assert result is False
        assert "Unexpected" not in caplog.text


class TestCreateSubprocessExecOSErrorLogging:
    """OSError from create_subprocess_exec is logged at ERROR level and propagated."""

    async def test_os_error_from_create_subprocess_exec_is_logged_at_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """PermissionError from create_subprocess_exec is logged at ERROR and re-raised."""
        gs = GitService(tmp_path)

        with (
            patch(
                "backend.services.git_service.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                side_effect=PermissionError("permission denied: git"),
            ),
            caplog.at_level(logging.ERROR, logger="backend.services.git_service"),
            pytest.raises(PermissionError, match="permission denied"),
        ):
            await gs._run("status")

        assert "Failed to launch subprocess" in caplog.text


class TestKillAndWaitOSErrorLogging:
    """process.kill() raising OSError is logged at WARNING, not DEBUG."""

    async def test_kill_oserror_is_logged_at_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A plain OSError (e.g. PermissionError) from kill() is logged at WARNING level."""
        gs = GitService(tmp_path)
        proc = AsyncMock()
        proc.returncode = None
        proc.kill = MagicMock(side_effect=PermissionError("operation not permitted"))
        call_count = 0

        async def raise_timeout_then_complete(awaitable: object, *, timeout: float) -> object:
            nonlocal call_count
            call_count += 1
            if hasattr(awaitable, "close"):
                awaitable.close()
            if call_count == 1:
                raise TimeoutError()
            # Second call: process.wait() — return normally
            return -9

        with (
            patch(
                "backend.services.git_service.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=proc,
            ),
            patch(
                "backend.services.git_service.asyncio.wait_for",
                side_effect=raise_timeout_then_complete,
            ),
            caplog.at_level(logging.WARNING, logger="backend.services.git_service"),
            pytest.raises(subprocess.TimeoutExpired),
        ):
            await gs._run("status")

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        kill_warnings = [
            r
            for r in warning_records
            if "kill" in r.message.lower() or "sigkill" in r.message.lower()
        ]
        assert kill_warnings, f"Expected WARNING log about kill failure; got: {caplog.text}"


class TestWriteMergeInputsErrorLogging:
    """OSError from _write_merge_inputs is logged with specific context before propagating."""

    async def test_write_inputs_oserror_triggers_error_log(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When _write_merge_inputs raises OSError, an ERROR log about file writing is emitted."""
        gs = GitService(tmp_path)
        await gs.init_repo()

        with (
            patch.object(
                GitService,
                "_write_merge_inputs",
                side_effect=OSError("No space left on device"),
            ),
            caplog.at_level(logging.ERROR, logger="backend.services.git_service"),
            pytest.raises(OSError, match="No space left"),
        ):
            await gs.merge_file_content("base\n", "ours\n", "theirs\n")

        assert "Failed to write merge input files" in caplog.text


class TestCommitAllHeadCommitNoneLogging:
    """commit_all logs an error when head_commit() returns None after a successful commit."""

    async def test_logs_error_when_head_commit_returns_none_after_commit(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """If head_commit() returns None after a successful git commit, an ERROR is logged."""
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        await gs.init_repo()
        (tmp_path / "new.txt").write_text("content")

        with (
            patch.object(gs, "head_commit", new_callable=AsyncMock, return_value=None),
            caplog.at_level(logging.ERROR, logger="backend.services.git_service"),
        ):
            result = await gs.commit_all("test commit")

        assert result is None
        assert "HEAD could not be resolved" in caplog.text


class TestTryCommitOSErrorErrno:
    """try_commit logs errno and traceback for OSError."""

    async def test_try_commit_os_error_logs_errno(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """OSError in try_commit is logged using an explicit errno format string."""
        import errno as errno_mod

        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        await gs.init_repo()

        exc = PermissionError(errno_mod.EACCES, "permission denied")
        with (
            patch.object(gs, "commit_all", new_callable=AsyncMock, side_effect=exc),
            caplog.at_level(logging.ERROR, logger="backend.services.git_service"),
        ):
            result = await gs.try_commit("test commit")

        assert result is None
        # The log message must use an explicit "(errno N)" format, not just str(exc)
        assert "(errno" in caplog.text

    async def test_try_commit_os_error_logs_traceback(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """OSError in try_commit is logged with exc_info so the traceback is preserved."""
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        await gs.init_repo()

        with (
            patch.object(
                gs,
                "commit_all",
                new_callable=AsyncMock,
                side_effect=OSError("disk error"),
            ),
            caplog.at_level(logging.ERROR, logger="backend.services.git_service"),
        ):
            await gs.try_commit("test commit")

        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert any(r.exc_info is not None and r.exc_info[0] is not None for r in error_records)
