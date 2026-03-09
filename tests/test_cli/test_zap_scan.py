"""Tests for OWASP ZAP scan orchestration."""

from __future__ import annotations

from pathlib import Path

import pytest

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
        caddy_port=8080,
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
    assert command[command.index("-t") + 1] == "http://host.docker.internal:8080/"
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
        caddy_port=8080,
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
    @pytest.fixture(autouse=True)
    def _stub_prerequisites(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("cli.zap_scan.check_prerequisites", lambda _project_dir: None)
        monkeypatch.setattr(
            "cli.zap_scan.write_local_caddy_env",
            lambda localdir: localdir / "zap-caddy.env",
        )

    def test_run_zap_scan_starts_and_stops_local_caddy_profile_when_needed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        localdir = tmp_path / ".local"
        run_calls: list[tuple[list[str], Path]] = []
        lifecycle_calls: list[str] = []

        monkeypatch.setattr(
            "cli.zap_scan.local_caddy_profile_health",
            lambda _caddy_port: False,
        )

        def fake_start_local_caddy_profile(
            _project_dir: Path,
            _env_file: Path,
            _caddy_port: int,
        ) -> None:
            lifecycle_calls.append("start")

        def fake_run_command(command: list[str], cwd: Path) -> int:
            run_calls.append((command, cwd))
            return 0

        def fake_stop_local_caddy_profile(_project_dir: Path, _env_file: Path) -> None:
            lifecycle_calls.append("stop")

        monkeypatch.setattr(
            "cli.zap_scan.start_local_caddy_profile",
            fake_start_local_caddy_profile,
        )
        monkeypatch.setattr("cli.zap_scan.run_command", fake_run_command)
        monkeypatch.setattr(
            "cli.zap_scan.stop_local_caddy_profile",
            fake_stop_local_caddy_profile,
        )

        exit_code = run_zap_scan(
            scan_mode="baseline",
            project_dir=tmp_path,
            localdir=localdir,
            caddy_port=8080,
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
        calls: list[str] = []

        monkeypatch.setattr(
            "cli.zap_scan.local_caddy_profile_health",
            lambda _caddy_port: True,
        )
        monkeypatch.setattr(
            "cli.zap_scan.start_local_caddy_profile",
            lambda *_args, **_kwargs: pytest.fail("start_local_caddy_profile should not be called"),
        )
        monkeypatch.setattr(
            "cli.zap_scan.stop_local_caddy_profile",
            lambda *_args, **_kwargs: pytest.fail("stop_local_caddy_profile should not be called"),
        )

        def fake_run_command(command: list[str], cwd: Path) -> int:
            calls.append("run")
            assert "http://host.docker.internal:8080/" in command
            assert cwd == tmp_path
            return 2

        monkeypatch.setattr("cli.zap_scan.run_command", fake_run_command)

        exit_code = run_zap_scan(
            scan_mode="full",
            project_dir=tmp_path,
            localdir=tmp_path / ".local",
            caddy_port=8080,
            minutes=None,
        )

        assert exit_code == 2
        assert calls == ["run"]

    def test_run_zap_scan_stops_started_local_caddy_profile_on_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        localdir = tmp_path / ".local"
        lifecycle_calls: list[str] = []

        monkeypatch.setattr(
            "cli.zap_scan.local_caddy_profile_health",
            lambda _caddy_port: False,
        )
        monkeypatch.setattr(
            "cli.zap_scan.start_local_caddy_profile",
            lambda _project_dir, _env_file, _caddy_port: lifecycle_calls.append("start"),
        )
        monkeypatch.setattr(
            "cli.zap_scan.stop_local_caddy_profile",
            lambda _project_dir, _env_file: lifecycle_calls.append("stop"),
        )

        def fake_run_command(_command: list[str], _cwd: Path) -> int:
            raise RuntimeError("zap failed")

        monkeypatch.setattr("cli.zap_scan.run_command", fake_run_command)

        with pytest.raises(RuntimeError, match="zap failed"):
            run_zap_scan(
                scan_mode="baseline",
                project_dir=tmp_path,
                localdir=localdir,
                caddy_port=8080,
                minutes=None,
            )

        assert lifecycle_calls == ["start", "stop"]
