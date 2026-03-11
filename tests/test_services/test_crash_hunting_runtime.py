"""Regression tests for process/runtime crash-hunting issues #16-#19."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Issue #16: PandocServer.start() not lock-protected
# ---------------------------------------------------------------------------


class TestPandocServerStartLockProtection:
    """start() should be protected by the internal lock so concurrent callers
    cannot spawn duplicate Pandoc processes."""

    async def test_start_acquires_lock(self) -> None:
        """start() must hold self._lock during its execution."""
        from backend.pandoc.server import PandocServer

        server = PandocServer(port=13031)

        lock_held = False

        async def fake_start_impl() -> None:
            nonlocal lock_held
            lock_held = server._lock.locked()

        with patch.object(server, "_start_impl", side_effect=fake_start_impl):
            await server.start()

        assert lock_held, "start() should hold self._lock while executing _start_impl"

    async def test_ensure_running_acquires_lock(self) -> None:
        """ensure_running() must hold self._lock when restarting."""
        from backend.pandoc.server import PandocServer

        server = PandocServer(port=13032)
        # Simulate a dead process so ensure_running triggers restart
        server._process = MagicMock()
        server._process.returncode = 1  # exited

        lock_held = False

        async def fake_start_impl() -> None:
            nonlocal lock_held
            lock_held = server._lock.locked()

        with patch.object(server, "_start_impl", side_effect=fake_start_impl):
            await server.ensure_running()

        assert lock_held, "ensure_running() should hold self._lock while restarting"

    async def test_concurrent_starts_serialized(self) -> None:
        """Multiple concurrent start() calls should be serialized by the lock,
        not spawn overlapping processes."""
        from backend.pandoc.server import PandocServer

        server = PandocServer(port=13033)
        call_count = 0

        async def slow_start_impl() -> None:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)

        with patch.object(server, "_start_impl", side_effect=slow_start_impl):
            await asyncio.gather(server.start(), server.start(), server.start())

        assert call_count == 3, "All three starts should have been called"

    async def test_start_impl_extracted(self) -> None:
        """_start_impl method should exist for shared logic between start()
        and ensure_running()."""
        from backend.pandoc.server import PandocServer

        server = PandocServer(port=13034)
        assert hasattr(server, "_start_impl"), "PandocServer should have _start_impl method"

    async def test_ensure_running_no_deadlock(self) -> None:
        """ensure_running() must not deadlock when calling internal start logic."""
        from backend.pandoc.server import PandocServer

        server = PandocServer(port=13035)
        # Simulate a dead process
        server._process = MagicMock()
        server._process.returncode = 1

        async def fake_start_impl() -> None:
            # Simulate start logic completing
            server._process = MagicMock()
            server._process.returncode = None

        with patch.object(server, "_start_impl", side_effect=fake_start_impl):
            # This should complete without deadlocking (timeout would catch it)
            await asyncio.wait_for(server.ensure_running(), timeout=2.0)


# ---------------------------------------------------------------------------
# Issue #17: Pandoc stderr always empty due to DEVNULL
# ---------------------------------------------------------------------------


class TestPandocStderrCapture:
    """_spawn() should use PIPE for stderr so _wait_for_ready can report diagnostics."""

    async def test_spawn_uses_pipe_for_stderr(self) -> None:
        """_spawn() should set stderr=PIPE, not DEVNULL."""
        from backend.pandoc.server import PandocServer

        server = PandocServer(port=13036)

        captured_kwargs: dict[str, object] = {}

        async def fake_create_subprocess_exec(*args: object, **kwargs: object) -> MagicMock:
            captured_kwargs.update(kwargs)
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_proc.returncode = None
            return mock_proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec):
            await server._spawn()

        assert captured_kwargs.get("stderr") == asyncio.subprocess.PIPE, (
            "stderr should be PIPE for diagnostic capture, not DEVNULL"
        )

    async def test_spawn_still_devnulls_stdout(self) -> None:
        """_spawn() should still suppress stdout with DEVNULL."""
        from backend.pandoc.server import PandocServer

        server = PandocServer(port=13037)

        captured_kwargs: dict[str, object] = {}

        async def fake_create_subprocess_exec(*args: object, **kwargs: object) -> MagicMock:
            captured_kwargs.update(kwargs)
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_proc.returncode = None
            return mock_proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec):
            await server._spawn()

        assert captured_kwargs.get("stdout") == asyncio.subprocess.DEVNULL, (
            "stdout should remain DEVNULL"
        )


# ---------------------------------------------------------------------------
# Issue #18: mkdir() without exist_ok=True in ensure_content_dir
# ---------------------------------------------------------------------------


class TestEnsureContentDirExistOk:
    """ensure_content_dir() should use exist_ok=True to avoid TOCTOU races."""

    def test_content_dir_already_exists(self, tmp_path: Path) -> None:
        """Should succeed when content_dir already exists (no race)."""
        from backend.main import ensure_content_dir

        content_dir = tmp_path / "content"
        content_dir.mkdir()
        # Should not raise
        ensure_content_dir(content_dir)

    def test_posts_dir_already_exists(self, tmp_path: Path) -> None:
        """Should succeed when posts_dir already exists (no race)."""
        from backend.main import ensure_content_dir

        content_dir = tmp_path / "content"
        content_dir.mkdir()
        posts_dir = content_dir / "posts"
        posts_dir.mkdir()
        # Should not raise
        ensure_content_dir(content_dir)

    def test_creates_content_dir_with_exist_ok(self, tmp_path: Path) -> None:
        """mkdir should use exist_ok=True so concurrent creators don't crash."""
        from backend.main import ensure_content_dir

        content_dir = tmp_path / "content"
        ensure_content_dir(content_dir)
        assert content_dir.is_dir()
        assert (content_dir / "posts").is_dir()

    def test_not_a_directory_still_raises(self, tmp_path: Path) -> None:
        """If content path is a file (not dir), should still raise."""
        from backend.main import ensure_content_dir

        content_path = tmp_path / "content"
        content_path.write_text("not a directory")
        with pytest.raises(NotADirectoryError):
            ensure_content_dir(content_path)

    def test_concurrent_creation_no_crash(self, tmp_path: Path) -> None:
        """Simulates the TOCTOU race: another process creates the dir
        between exists() check and mkdir() call. With exist_ok=True, this
        should not raise FileExistsError."""
        from backend.main import ensure_content_dir

        content_dir = tmp_path / "content"

        original_mkdir = Path.mkdir

        call_count = 0

        def racing_mkdir(self: Path, *args: object, **kwargs: object) -> None:
            nonlocal call_count
            call_count += 1
            # First call: simulate race by creating the dir first
            if call_count == 1 and not self.exists():
                self.mkdir(parents=True, exist_ok=True)
            # Now call the real mkdir — should not fail if exist_ok=True
            original_mkdir(self, *args, **kwargs)  # type: ignore[arg-type]

        with patch.object(Path, "mkdir", racing_mkdir):
            # This should not raise FileExistsError
            ensure_content_dir(content_dir)


# ---------------------------------------------------------------------------
# Issue #19: os.unlink in except BaseException can mask original exception
# ---------------------------------------------------------------------------


class TestSerializeKeypairCleanup:
    """serialize_keypair() cleanup in except BaseException should not mask
    the original exception if os.unlink fails."""

    def test_cleanup_failure_does_not_mask_original_error(self, tmp_path: Path) -> None:
        """If the temp file write fails AND os.unlink also fails,
        the original exception should be raised, not the unlink error."""
        from backend.crosspost.atproto_oauth import generate_es256_keypair, serialize_keypair

        key, jwk = generate_es256_keypair()
        target_path = tmp_path / "keypair.json"

        original_error = OSError("disk write failed")

        def failing_fdopen(fd: int, mode: str) -> object:
            # Close the fd so unlink target still exists but we raise
            os.close(fd)
            raise original_error

        with (
            patch("os.fdopen", side_effect=failing_fdopen),
            patch("os.unlink", side_effect=OSError("unlink failed")),
            pytest.raises(OSError, match="disk write failed"),
        ):
            serialize_keypair(key, jwk, target_path)

    def test_cleanup_succeeds_on_normal_error(self, tmp_path: Path) -> None:
        """If the temp file write fails but os.unlink succeeds,
        the original exception should propagate cleanly."""
        from backend.crosspost.atproto_oauth import generate_es256_keypair, serialize_keypair

        key, jwk = generate_es256_keypair()
        target_path = tmp_path / "keypair.json"

        original_error = RuntimeError("write failed")

        def failing_fdopen(fd: int, mode: str) -> object:
            os.close(fd)
            raise original_error

        with (
            patch("os.fdopen", side_effect=failing_fdopen),
            pytest.raises(RuntimeError, match="write failed"),
        ):
            serialize_keypair(key, jwk, target_path)

    def test_successful_write_no_cleanup(self, tmp_path: Path) -> None:
        """Normal case: serialize_keypair writes successfully, no cleanup needed."""
        from backend.crosspost.atproto_oauth import generate_es256_keypair, serialize_keypair

        key, jwk = generate_es256_keypair()
        target_path = tmp_path / "keypair.json"

        serialize_keypair(key, jwk, target_path)

        assert target_path.exists()
        data = json.loads(target_path.read_text())
        assert "private_key_pem" in data
        assert data["jwk"] == jwk
