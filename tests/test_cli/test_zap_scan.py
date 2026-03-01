"""Tests for OWASP ZAP scan orchestration."""

from __future__ import annotations

from pathlib import Path

import pytest

from cli.dev_server import DevServerState
from cli.zap_scan import (
    DEFAULT_ZAP_IMAGE,
    build_docker_command,
    run_zap_scan,
)


def test_justfile_zap_recipe_defaults_avoid_nested_template_literals() -> None:
    justfile = Path("justfile").read_text(encoding="utf-8")

    assert 'zap-baseline minutes="":' in justfile
    assert 'zap-full minutes="":' in justfile
    assert 'zap-baseline minutes="{{ zap_baseline_minutes }}":' not in justfile
    assert 'zap-full minutes="{{ zap_full_minutes }}":' not in justfile


def test_build_docker_command_for_baseline_scan_on_macos(tmp_path: Path) -> None:
    command = build_docker_command(
        scan_mode="baseline",
        project_dir=tmp_path,
        frontend_port=5173,
        minutes=None,
        system_name="Darwin",
    )

    assert command[:4] == ["/usr/bin/env", "docker", "run", "--rm"]
    assert "--add-host" not in command
    assert f"{tmp_path}:/zap/wrk:rw" in command
    assert DEFAULT_ZAP_IMAGE in command
    assert "zap-baseline.py" in command
    assert "-j" in command
    assert "-I" in command
    assert command[command.index("-t") + 1] == "http://host.docker.internal:5173/"
    assert "-m" not in command
    assert "reports/zap/baseline/report.html" in command
    assert "reports/zap/baseline/report.md" in command
    assert "reports/zap/baseline/report.json" in command
    assert "reports/zap/baseline/report.xml" in command


def test_build_docker_command_for_full_scan_on_linux_adds_host_gateway(
    tmp_path: Path,
) -> None:
    command = build_docker_command(
        scan_mode="full",
        project_dir=tmp_path,
        frontend_port=5173,
        minutes=4,
        system_name="Linux",
    )

    add_host_index = command.index("--add-host")
    assert command[add_host_index + 1] == "host.docker.internal:host-gateway"
    assert "zap-full-scan.py" in command
    assert command[command.index("-m") + 1] == "4"
    assert "reports/zap/full/report.html" in command
    assert "reports/zap/full/report.md" in command
    assert "reports/zap/full/report.json" in command
    assert "reports/zap/full/report.xml" in command


class TestRunZapScan:
    def test_run_zap_scan_starts_and_stops_dev_server_when_needed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        localdir = tmp_path / ".local"
        state = DevServerState(
            backend_pid=123,
            frontend_pid=456,
            backend_port=8000,
            frontend_port=5173,
            backend_log=str(localdir / "backend.log"),
            frontend_log=str(localdir / "frontend.log"),
        )
        run_calls: list[tuple[list[str], Path]] = []
        lifecycle_calls: list[str] = []

        monkeypatch.setattr("cli.zap_scan.check_prerequisites", lambda _project_dir: None)
        monkeypatch.setattr(
            "cli.zap_scan.health_dev_server",
            lambda _localdir, _backend_port, _frontend_port: (False, 8000, 5173),
        )

        def fake_start_dev_server(
            _localdir: Path,
            _requested_backend_port: int,
            _requested_frontend_port: int,
        ) -> DevServerState:
            lifecycle_calls.append("start")
            return state

        def fake_run_command(command: list[str], cwd: Path) -> int:
            run_calls.append((command, cwd))
            return 0

        def fake_stop_dev_server(_localdir: Path) -> tuple[bool, str]:
            lifecycle_calls.append("stop")
            return True, "stopped"

        monkeypatch.setattr("cli.zap_scan.start_dev_server", fake_start_dev_server)
        monkeypatch.setattr("cli.zap_scan.run_command", fake_run_command)
        monkeypatch.setattr("cli.zap_scan.stop_dev_server", fake_stop_dev_server)

        exit_code = run_zap_scan(
            scan_mode="baseline",
            project_dir=tmp_path,
            localdir=localdir,
            backend_port=8000,
            frontend_port=5173,
            minutes=None,
        )

        assert exit_code == 0
        assert lifecycle_calls == ["start", "stop"]
        assert len(run_calls) == 1
        _command, cwd = run_calls[0]
        assert cwd == tmp_path
        assert (tmp_path / "reports" / "zap" / "baseline").is_dir()

    def test_run_zap_scan_reuses_healthy_dev_server(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        localdir = tmp_path / ".local"
        calls: list[str] = []

        monkeypatch.setattr("cli.zap_scan.check_prerequisites", lambda _project_dir: None)
        monkeypatch.setattr(
            "cli.zap_scan.health_dev_server",
            lambda _localdir, _backend_port, _frontend_port: (True, 8000, 5173),
        )
        monkeypatch.setattr(
            "cli.zap_scan.start_dev_server",
            lambda *_args, **_kwargs: pytest.fail("start_dev_server should not be called"),
        )
        monkeypatch.setattr(
            "cli.zap_scan.stop_dev_server",
            lambda *_args, **_kwargs: pytest.fail("stop_dev_server should not be called"),
        )

        def fake_run_command(command: list[str], cwd: Path) -> int:
            calls.append("run")
            assert "http://host.docker.internal:5173/" in command
            assert cwd == tmp_path
            return 2

        monkeypatch.setattr("cli.zap_scan.run_command", fake_run_command)

        exit_code = run_zap_scan(
            scan_mode="full",
            project_dir=tmp_path,
            localdir=localdir,
            backend_port=8000,
            frontend_port=5173,
            minutes=None,
        )

        assert exit_code == 2
        assert calls == ["run"]

    def test_run_zap_scan_recovers_from_stale_dev_server_state(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        localdir = tmp_path / ".local"
        first_state = DevServerState(
            backend_pid=123,
            frontend_pid=456,
            backend_port=8000,
            frontend_port=5173,
            backend_log=str(localdir / "backend.log"),
            frontend_log=str(localdir / "frontend.log"),
        )
        lifecycle_calls: list[str] = []

        monkeypatch.setattr("cli.zap_scan.check_prerequisites", lambda _project_dir: None)
        monkeypatch.setattr(
            "cli.zap_scan.health_dev_server",
            lambda _localdir, _backend_port, _frontend_port: (False, 8000, 5173),
        )

        start_attempts = 0

        def fake_start_dev_server(
            _localdir: Path,
            _requested_backend_port: int,
            _requested_frontend_port: int,
        ) -> DevServerState:
            nonlocal start_attempts
            start_attempts += 1
            lifecycle_calls.append(f"start-{start_attempts}")
            if start_attempts == 1:
                msg = "Dev server is already running (backend PID 123, frontend PID 456)"
                raise RuntimeError(msg)
            return first_state

        def fake_stop_dev_server(_localdir: Path) -> tuple[bool, str]:
            lifecycle_calls.append("stop")
            return True, "stopped"

        monkeypatch.setattr("cli.zap_scan.start_dev_server", fake_start_dev_server)
        monkeypatch.setattr("cli.zap_scan.stop_dev_server", fake_stop_dev_server)
        monkeypatch.setattr("cli.zap_scan.run_command", lambda _command, _cwd: 0)

        exit_code = run_zap_scan(
            scan_mode="baseline",
            project_dir=tmp_path,
            localdir=localdir,
            backend_port=8000,
            frontend_port=5173,
            minutes=None,
        )

        assert exit_code == 0
        assert lifecycle_calls == ["start-1", "stop", "start-2", "stop"]

    def test_run_zap_scan_clears_state_when_stop_permission_is_denied(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        localdir = tmp_path / ".local"
        state = DevServerState(
            backend_pid=123,
            frontend_pid=456,
            backend_port=8000,
            frontend_port=5173,
            backend_log=str(localdir / "backend.log"),
            frontend_log=str(localdir / "frontend.log"),
        )
        lifecycle_calls: list[str] = []

        monkeypatch.setattr("cli.zap_scan.check_prerequisites", lambda _project_dir: None)
        monkeypatch.setattr(
            "cli.zap_scan.health_dev_server",
            lambda _localdir, _backend_port, _frontend_port: (False, 8000, 5173),
        )

        start_attempts = 0

        def fake_start_dev_server(
            _localdir: Path,
            _requested_backend_port: int,
            _requested_frontend_port: int,
        ) -> DevServerState:
            nonlocal start_attempts
            start_attempts += 1
            lifecycle_calls.append(f"start-{start_attempts}")
            if start_attempts == 1:
                msg = "Dev server is already running (backend PID 123, frontend PID 456)"
                raise RuntimeError(msg)
            return state

        def fake_stop_dev_server(_localdir: Path) -> tuple[bool, str]:
            lifecycle_calls.append("stop")
            raise PermissionError("not permitted")

        monkeypatch.setattr("cli.zap_scan.start_dev_server", fake_start_dev_server)
        monkeypatch.setattr("cli.zap_scan.stop_dev_server", fake_stop_dev_server)
        monkeypatch.setattr(
            "cli.zap_scan.remove_state",
            lambda _localdir: lifecycle_calls.append("clear"),
        )
        monkeypatch.setattr("cli.zap_scan.run_command", lambda _command, _cwd: 0)

        exit_code = run_zap_scan(
            scan_mode="baseline",
            project_dir=tmp_path,
            localdir=localdir,
            backend_port=8000,
            frontend_port=5173,
            minutes=None,
        )

        assert exit_code == 0
        assert lifecycle_calls == ["start-1", "stop", "clear", "start-2", "stop", "clear"]
