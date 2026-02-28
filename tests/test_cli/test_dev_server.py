"""Tests for the development server process manager."""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING

import pytest

from cli.dev_server import (
    DevServerState,
    find_free_port,
    is_process_alive,
    load_state,
    start_dev_server,
    stop_dev_server,
)

if TYPE_CHECKING:
    from pathlib import Path


def _http_server_command(port: int) -> list[str]:
    return [
        sys.executable,
        "-m",
        "http.server",
        str(port),
        "--bind",
        "127.0.0.1",
    ]


def _failing_command(message: str) -> list[str]:
    return [sys.executable, "-c", f"print({message!r}); raise SystemExit(1)"]


class TestStartDevServer:
    def test_start_dev_server_persists_state_only_after_services_are_healthy(
        self, tmp_path: Path
    ) -> None:
        backend_port = find_free_port(18000)
        frontend_port = find_free_port(18001, backend_port)

        state = start_dev_server(
            tmp_path,
            backend_port,
            frontend_port,
            startup_timeout_seconds=5.0,
            backend_command=_http_server_command(backend_port),
            frontend_command=_http_server_command(frontend_port),
        )

        try:
            persisted = load_state(tmp_path)
            assert isinstance(persisted, DevServerState)
            assert persisted == state
            assert persisted.backend_port == backend_port
            assert persisted.frontend_port == frontend_port
        finally:
            stopped, _message = stop_dev_server(tmp_path)
            assert stopped

    def test_start_dev_server_fails_when_service_exits_before_health(self, tmp_path: Path) -> None:
        backend_port = find_free_port(18100)
        frontend_port = find_free_port(18101, backend_port)

        with pytest.raises(RuntimeError, match="frontend exited before becoming healthy"):
            start_dev_server(
                tmp_path,
                backend_port,
                frontend_port,
                startup_timeout_seconds=2.0,
                backend_command=_http_server_command(backend_port),
                frontend_command=_failing_command("frontend failed to boot"),
            )

        assert load_state(tmp_path) is None
        frontend_log = (tmp_path / "frontend.log").read_text(encoding="utf-8")
        assert "frontend failed to boot" in frontend_log


class TestStopDevServer:
    def test_stop_dev_server_reports_stale_state_after_process_exit(self, tmp_path: Path) -> None:
        backend_port = find_free_port(18200)
        frontend_port = find_free_port(18201, backend_port)

        start_dev_server(
            tmp_path,
            backend_port,
            frontend_port,
            startup_timeout_seconds=5.0,
            backend_command=_http_server_command(backend_port),
            frontend_command=_http_server_command(frontend_port),
        )
        stopped, _message = stop_dev_server(tmp_path)
        assert stopped

        stale_stopped, stale_message = stop_dev_server(tmp_path)
        assert not stale_stopped
        assert stale_message == "No dev server pidfile found"

    def test_stop_dev_server_terminates_processes(self, tmp_path: Path) -> None:
        backend_port = find_free_port(18300)
        frontend_port = find_free_port(18301, backend_port)
        state = start_dev_server(
            tmp_path,
            backend_port,
            frontend_port,
            startup_timeout_seconds=5.0,
            backend_command=_http_server_command(backend_port),
            frontend_command=_http_server_command(frontend_port),
        )

        stopped, _message = stop_dev_server(tmp_path)

        assert stopped
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if not is_process_alive(state.backend_pid) and not is_process_alive(state.frontend_pid):
                break
            time.sleep(0.05)
        assert load_state(tmp_path) is None
        assert not is_process_alive(state.backend_pid)
        assert not is_process_alive(state.frontend_pid)
