"""Tests for local Caddy-backed build orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cli.local_caddy import main

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


def test_main_start_starts_local_caddy_profile_when_unhealthy(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    localdir = tmp_path / ".local"
    calls: list[object] = []

    monkeypatch.setattr("cli.local_caddy.check_prerequisites", lambda _project_dir: None)
    monkeypatch.setattr(
        "cli.local_caddy.write_local_caddy_env",
        lambda given_localdir: given_localdir / "caddy-local.env",
    )
    monkeypatch.setattr("cli.local_caddy.local_caddy_profile_health", lambda _port: False)

    def fake_start(project_dir: Path, env_file: Path, caddy_port: int) -> None:
        calls.append((project_dir, env_file, caddy_port))

    monkeypatch.setattr("cli.local_caddy.start_local_caddy_profile", fake_start)
    monkeypatch.setattr(
        "cli.local_caddy.stop_local_caddy_profile",
        lambda *_args: pytest.fail("stop_local_caddy_profile should not be called"),
    )

    exit_code = main(
        [
            "start",
            "--project-dir",
            str(tmp_path),
            "--localdir",
            str(localdir),
            "--caddy-port",
            "8080",
        ]
    )

    assert exit_code == 0
    assert calls == [
        (
            tmp_path.resolve(),
            (localdir.resolve() / "caddy-local.env"),
            8080,
        )
    ]


def test_main_start_reuses_existing_healthy_profile(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("cli.local_caddy.check_prerequisites", lambda _project_dir: None)
    monkeypatch.setattr(
        "cli.local_caddy.write_local_caddy_env",
        lambda given_localdir: given_localdir / "caddy-local.env",
    )
    monkeypatch.setattr("cli.local_caddy.local_caddy_profile_health", lambda _port: True)
    monkeypatch.setattr(
        "cli.local_caddy.start_local_caddy_profile",
        lambda *_args: pytest.fail("start_local_caddy_profile should not be called"),
    )

    exit_code = main(
        [
            "start",
            "--project-dir",
            str(tmp_path),
            "--localdir",
            str(tmp_path / ".local"),
            "--caddy-port",
            "8080",
        ]
    )

    assert exit_code == 0


def test_main_health_returns_nonzero_when_profile_is_unhealthy(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr("cli.local_caddy.local_caddy_profile_health", lambda _port: False)

    exit_code = main(["health", "--caddy-port", "8080"])

    assert exit_code == 1


def test_main_stop_stops_local_caddy_profile(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    localdir = tmp_path / ".local"
    calls: list[tuple[Path, Path]] = []

    monkeypatch.setattr("cli.local_caddy.check_prerequisites", lambda _project_dir: None)
    monkeypatch.setattr(
        "cli.local_caddy.write_local_caddy_env",
        lambda given_localdir: given_localdir / "caddy-local.env",
    )

    def fake_stop(project_dir: Path, env_file: Path) -> None:
        calls.append((project_dir, env_file))

    monkeypatch.setattr("cli.local_caddy.stop_local_caddy_profile", fake_stop)

    exit_code = main(
        [
            "stop",
            "--project-dir",
            str(tmp_path),
            "--localdir",
            str(localdir),
        ]
    )

    assert exit_code == 0
    assert calls == [(tmp_path.resolve(), localdir.resolve() / "caddy-local.env")]
