"""Pandoc server lifecycle manager.

Manages a long-lived ``pandoc server`` child process for high-throughput
rendering via the Pandoc HTTP API instead of per-render subprocess calls.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from backend.exceptions import InternalServerError

logger = logging.getLogger(__name__)

_HEALTH_CHECK_RETRIES = 5
_HEALTH_CHECK_INTERVAL = 0.5
_STOP_TIMEOUT = 5.0


class PandocServer:
    """Manages the lifecycle of a ``pandoc server`` child process.

    Args:
        port: TCP port the pandoc server listens on.
        timeout: Per-request timeout (seconds) passed to ``pandoc server --timeout``.
    """

    def __init__(self, port: int = 3031, timeout: int = 10) -> None:
        if not (1 <= port <= 65535):
            msg = f"port must be between 1 and 65535, got {port}"
            raise InternalServerError(msg)
        if timeout < 1:
            msg = f"timeout must be >= 1, got {timeout}"
            raise InternalServerError(msg)
        self._port = port
        self._timeout = timeout
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        """HTTP base URL of the pandoc server."""
        return f"http://127.0.0.1:{self._port}"

    @property
    def is_running(self) -> bool:
        """Whether the subprocess is alive."""
        return self._process is not None and self._process.returncode is None

    async def _check_server_support(self) -> None:
        """Verify that the installed pandoc binary supports server mode.

        Raises:
            RuntimeError: If pandoc is missing, version check fails, or
                ``+server`` is absent from the feature flags.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "pandoc",
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
        except FileNotFoundError:
            raise RuntimeError(
                "Pandoc is not installed. Install pandoc to enable markdown rendering. "
                "See https://pandoc.org/installing.html"
            ) from None
        except OSError as exc:
            raise RuntimeError(f"Failed to check pandoc version: {exc}") from None

        if proc.returncode != 0:
            raise RuntimeError(
                f"Failed to check pandoc version (exit code {proc.returncode}): "
                f"{stderr.decode(errors='replace')[:200]}"
            )

        version_output = stdout.decode(errors="replace")
        if "+server" not in version_output:
            raise RuntimeError(
                "Installed pandoc does not support server mode (+server feature flag missing). "
                "Install a pandoc build with server support."
            )

        logger.info("Pandoc server support confirmed")

    async def _spawn(self) -> None:
        """Spawn the ``pandoc server`` subprocess."""
        self._process = await asyncio.create_subprocess_exec(
            "pandoc",
            "server",
            "--port",
            str(self._port),
            "--timeout",
            str(self._timeout),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        logger.info(
            "Spawned pandoc server process (pid=%s, port=%d)",
            self._process.pid,
            self._port,
        )

    async def _wait_for_ready(self) -> None:
        """Wait until the pandoc server responds to HTTP requests.

        Retries up to ``_HEALTH_CHECK_RETRIES`` times with
        ``_HEALTH_CHECK_INTERVAL`` between attempts. If the process exits
        during startup, reads stderr and raises ``RuntimeError``.

        Raises:
            RuntimeError: If the server exits prematurely or fails to respond
                within the retry budget.
        """
        async with httpx.AsyncClient() as client:
            for attempt in range(_HEALTH_CHECK_RETRIES):
                # Check if process exited during startup
                if self._process is not None and self._process.returncode is not None:
                    stderr_bytes = b""
                    if self._process.stderr is not None:
                        stderr_bytes = await self._process.stderr.read()
                    stderr_text = stderr_bytes.decode(errors="replace").strip()
                    raise RuntimeError(
                        f"Pandoc server exited during startup "
                        f"(exit code {self._process.returncode}): {stderr_text[:500]}"
                    )

                try:
                    response = await client.get(self.base_url)
                    logger.info(
                        "Pandoc server ready on port %d (attempt %d, status %d)",
                        self._port,
                        attempt + 1,
                        response.status_code,
                    )
                    return
                except httpx.ConnectError:
                    if attempt < _HEALTH_CHECK_RETRIES - 1:
                        await asyncio.sleep(_HEALTH_CHECK_INTERVAL)
                except httpx.HTTPError:
                    # Any non-connection error (e.g. ReadError) means the
                    # server is listening but doesn't support GET — that's fine.
                    logger.info(
                        "Pandoc server responding on port %d (attempt %d)",
                        self._port,
                        attempt + 1,
                    )
                    return

        raise RuntimeError(
            f"Pandoc server failed to start after {_HEALTH_CHECK_RETRIES} attempts "
            f"on port {self._port}"
        )

    async def _start_impl(self) -> None:
        """Internal start logic. Caller must hold ``self._lock``."""
        if self.is_running:
            await self.stop()
        await self._check_server_support()
        await self._spawn()
        await self._wait_for_ready()
        logger.info("Pandoc server started on %s", self.base_url)

    async def start(self) -> None:
        """Start (or restart) the pandoc server.

        Checks server support, stops any existing process, spawns a new one,
        and waits for it to become ready.  Protected by ``self._lock`` to
        prevent concurrent callers from spawning multiple processes.

        Raises:
            RuntimeError: If pandoc is missing, lacks server support, or
                the server fails to start.
        """
        async with self._lock:
            await self._start_impl()

    async def stop(self) -> None:
        """Stop the pandoc server process. Idempotent.

        Sends SIGTERM and waits up to ``_STOP_TIMEOUT`` seconds. If the
        process does not exit in time, sends SIGKILL.
        """
        if self._process is None:
            return

        if self._process.returncode is not None:
            # Already exited
            self._process = None
            return

        logger.info("Stopping pandoc server (pid=%s)", self._process.pid)
        self._process.terminate()
        try:
            await asyncio.wait_for(self._process.wait(), timeout=_STOP_TIMEOUT)
        except TimeoutError:
            logger.warning("Pandoc server did not exit after %.1fs, killing", _STOP_TIMEOUT)
            self._process.kill()
            await self._process.wait()

        self._process = None

    async def ensure_running(self) -> None:
        """Ensure the pandoc server is running, restarting if needed.

        Uses an asyncio lock to prevent concurrent restart attempts.
        Calls ``_start_impl`` directly to avoid deadlocking on re-entrant
        lock acquisition (``start()`` also acquires the lock).
        """
        if self.is_running:
            return

        async with self._lock:
            # Double-check after acquiring the lock — another coroutine
            # may have restarted the server while we waited for the lock.
            if self._process is not None and self._process.returncode is None:
                return

            logger.warning("Pandoc server not running, restarting")
            await self._start_impl()
