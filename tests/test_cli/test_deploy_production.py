"""Tests for production deployment CLI workflow."""

from __future__ import annotations

import argparse
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from cli.deploy_production import (
    CADDY_STATIC_IP,
    COMPOSE_SUBNET,
    DEFAULT_BUNDLE_DIR,
    DEFAULT_CADDY_PUBLIC_COMPOSE_FILE,
    DEFAULT_IMAGE_COMPOSE_FILE,
    DEFAULT_IMAGE_NO_CADDY_COMPOSE_FILE,
    DEFAULT_IMAGE_TARBALL,
    DEFAULT_NO_CADDY_COMPOSE_FILE,
    DEPLOY_MODE_LOCAL,
    DEPLOY_MODE_REGISTRY,
    DEPLOY_MODE_TARBALL,
    LOCAL_IMAGE_TAG,
    LOCALHOST_BIND_IP,
    MIN_SECRET_KEY_LENGTH,
    PUBLIC_BIND_IP,
    CaddyConfig,
    DeployConfig,
    DeployError,
    backup_existing_configs,
    backup_file,
    build_caddy_public_compose_override_content,
    build_caddyfile_content,
    build_direct_compose_content,
    build_env_content,
    build_image_compose_content,
    build_image_direct_compose_content,
    build_lifecycle_commands,
    check_prerequisites,
    config_from_args,
    deploy,
    dry_run,
    parse_csv_list,
    write_config_files,
)

if TYPE_CHECKING:
    from pathlib import Path


def _make_config(
    *,
    caddy_config: CaddyConfig | None = None,
    caddy_public: bool = False,
    host_bind_ip: str = PUBLIC_BIND_IP,
    expose_docs: bool = False,
    deployment_mode: str = DEPLOY_MODE_LOCAL,
    image_ref: str | None = None,
) -> DeployConfig:
    """Build a valid DeployConfig with sensible defaults for tests."""
    return DeployConfig(
        secret_key="x" * 64,
        admin_username="admin",
        admin_password="very-strong-password",
        trusted_hosts=["example.com"],
        trusted_proxy_ips=[],
        host_port=8000,
        host_bind_ip=host_bind_ip,
        caddy_config=caddy_config,
        caddy_public=caddy_public,
        expose_docs=expose_docs,
        deployment_mode=deployment_mode,
        image_ref=image_ref,
        bundle_dir=DEFAULT_BUNDLE_DIR,
        tarball_filename=DEFAULT_IMAGE_TARBALL,
    )


def _stub_subprocess(monkeypatch: pytest.MonkeyPatch) -> list[tuple[list[str], Path, bool]]:
    """Stub subprocess.run and return a list that captures all calls."""
    commands: list[tuple[list[str], Path, bool]] = []

    def fake_run(command: list[str], cwd: Path, check: bool) -> SimpleNamespace:
        commands.append((command, cwd, check))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("cli.deploy_production.subprocess.run", fake_run)
    return commands


def _stub_no_trivy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub shutil.which to report Trivy unavailable."""
    monkeypatch.setattr(
        "cli.deploy_production.shutil.which",
        lambda name: None if name == "trivy" else "/usr/bin/docker",
    )


def _stub_with_trivy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub shutil.which to report Trivy available."""
    monkeypatch.setattr(
        "cli.deploy_production.shutil.which",
        lambda name: "/usr/bin/trivy" if name == "trivy" else "/usr/bin/docker",
    )


# ── parse_csv_list ───────────────────────────────────────────────────


def test_parse_csv_list_trims_and_deduplicates() -> None:
    values = parse_csv_list("example.com, blog.example.com ,example.com,,")
    assert values == ["example.com", "blog.example.com"]


# ── build_env_content ────────────────────────────────────────────────


def test_build_env_content_includes_required_production_values() -> None:
    config = DeployConfig(
        secret_key="x" * 64,
        admin_username="admin",
        admin_password="very-strong-password",
        trusted_hosts=["example.com", "www.example.com"],
        trusted_proxy_ips=["172.16.0.1"],
        host_port=8000,
        host_bind_ip=PUBLIC_BIND_IP,
        caddy_config=None,
        caddy_public=False,
        expose_docs=False,
    )

    content = build_env_content(config)

    assert (
        'SECRET_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"' in content
    )
    assert 'ADMIN_USERNAME="admin"' in content
    assert 'ADMIN_PASSWORD="very-strong-password"' in content
    assert "DEBUG=false" in content
    assert "\nHOST=" not in content
    assert "\nPORT=" not in content
    assert f"HOST_BIND_IP={PUBLIC_BIND_IP}" in content
    assert 'TRUSTED_HOSTS=["example.com","www.example.com"]' in content
    assert 'TRUSTED_PROXY_IPS=["172.16.0.1"]' in content


def test_build_env_content_quotes_special_characters() -> None:
    config = DeployConfig(
        secret_key='abc"def#ghi',
        admin_username="admin user",
        admin_password="pass\\word",
        trusted_hosts=["example.com"],
        trusted_proxy_ips=[],
        host_port=8000,
        host_bind_ip=LOCALHOST_BIND_IP,
        caddy_config=None,
        caddy_public=False,
        expose_docs=False,
    )

    content = build_env_content(config)
    assert 'SECRET_KEY="abc\\"def#ghi"' in content
    assert 'ADMIN_USERNAME="admin user"' in content
    assert 'ADMIN_PASSWORD="pass\\\\word"' in content


def test_build_env_content_includes_auth_hardening_settings() -> None:
    config = _make_config()
    content = build_env_content(config)

    assert "AUTH_ENFORCE_LOGIN_ORIGIN=true" in content
    assert "AUTH_SELF_REGISTRATION=false" in content
    assert "AUTH_INVITES_ENABLED=true" in content
    assert "AUTH_LOGIN_MAX_FAILURES=5" in content
    assert "AUTH_RATE_LIMIT_WINDOW_SECONDS=300" in content


def test_build_env_content_includes_image_reference_for_remote_deployments() -> None:
    config = _make_config(
        deployment_mode=DEPLOY_MODE_REGISTRY,
        image_ref="ghcr.io/example/agblogger:1.2.3",
    )

    content = build_env_content(config)

    assert 'AGBLOGGER_IMAGE="ghcr.io/example/agblogger:1.2.3"' in content


def test_build_env_content_expose_docs_false_by_default() -> None:
    config = _make_config(expose_docs=False)
    content = build_env_content(config)
    assert "EXPOSE_DOCS=false" in content


def test_build_env_content_expose_docs_true_when_enabled() -> None:
    config = _make_config(expose_docs=True)
    content = build_env_content(config)
    assert "EXPOSE_DOCS=true" in content


# ── build_caddyfile_content ──────────────────────────────────────────


def test_build_caddyfile_content_includes_domain_and_optional_email() -> None:
    caddy = CaddyConfig(domain="blog.example.com", email="ops@example.com")
    content = build_caddyfile_content(caddy)
    assert "email ops@example.com" in content
    assert "blog.example.com {" in content
    assert "reverse_proxy agblogger:8000" in content


def test_build_caddyfile_content_includes_request_body_limits() -> None:
    caddy = CaddyConfig(domain="blog.example.com", email=None)
    content = build_caddyfile_content(caddy)

    assert "@postUpload path /api/posts/upload" in content
    assert "max_size 55MB" in content
    assert "@postAssets path_regexp post_assets ^/api/posts/.+/assets$" in content
    assert "@syncCommit path /api/sync/commit" in content
    assert "max_size 100MB" in content


# ── build_direct_compose_content ─────────────────────────────────────


def test_build_direct_compose_content_uses_host_bind_and_port() -> None:
    content = build_direct_compose_content()
    assert "${HOST_BIND_IP:-127.0.0.1}:${HOST_PORT:-8000}:8000" in content
    assert f"image: {LOCAL_IMAGE_TAG}" in content
    assert "caddy:" not in content


def test_build_direct_compose_content_passes_all_env_vars() -> None:
    content = build_direct_compose_content()
    assert "EXPOSE_DOCS=${EXPOSE_DOCS:-false}" in content
    assert "DEBUG=${DEBUG:-false}" in content
    assert "AUTH_ENFORCE_LOGIN_ORIGIN=${AUTH_ENFORCE_LOGIN_ORIGIN:-true}" in content
    assert "AUTH_SELF_REGISTRATION=${AUTH_SELF_REGISTRATION:-false}" in content
    assert "AUTH_LOGIN_MAX_FAILURES=${AUTH_LOGIN_MAX_FAILURES:-5}" in content


def test_build_image_compose_content_uses_required_image_reference() -> None:
    content = build_image_compose_content()
    assert "${AGBLOGGER_IMAGE?Set AGBLOGGER_IMAGE}" in content
    assert "build:" not in content


def test_build_image_compose_content_includes_caddy_network() -> None:
    content = build_image_compose_content()
    assert f"ipv4_address: {CADDY_STATIC_IP}" in content
    assert "subnet: 172.30.0.0/24" in content


def test_build_image_compose_content_passes_all_env_vars() -> None:
    content = build_image_compose_content()
    assert "EXPOSE_DOCS=${EXPOSE_DOCS:-false}" in content
    assert "AUTH_ENFORCE_LOGIN_ORIGIN=${AUTH_ENFORCE_LOGIN_ORIGIN:-true}" in content


def test_build_image_direct_compose_content_uses_required_image_reference() -> None:
    content = build_image_direct_compose_content()
    assert "${AGBLOGGER_IMAGE?Set AGBLOGGER_IMAGE}" in content
    assert "build:" not in content
    assert "${HOST_BIND_IP:-127.0.0.1}:${HOST_PORT:-8000}:8000" in content
    assert "ipv4_address" not in content


# ── build_caddy_public_compose_override_content ──────────────────────


def test_build_caddy_public_override_exposes_ports() -> None:
    content = build_caddy_public_compose_override_content()
    assert '"80:80"' in content
    assert '"443:443"' in content


# ── build_lifecycle_commands ─────────────────────────────────────────


def test_build_lifecycle_commands_for_default_caddy() -> None:
    commands = build_lifecycle_commands(
        deployment_mode=DEPLOY_MODE_LOCAL,
        use_caddy=True,
        caddy_public=False,
    )
    assert commands["start"] == "docker compose --env-file .env.production up -d"
    assert commands["stop"] == "docker compose --env-file .env.production down"
    assert commands["status"] == "docker compose --env-file .env.production ps"


def test_build_lifecycle_commands_for_public_caddy_override() -> None:
    commands = build_lifecycle_commands(
        deployment_mode=DEPLOY_MODE_LOCAL,
        use_caddy=True,
        caddy_public=True,
    )
    assert (
        commands["start"] == "docker compose --env-file .env.production -f docker-compose.yml "
        "-f docker-compose.caddy-public.yml up -d"
    )


def test_build_lifecycle_commands_for_no_caddy_file() -> None:
    commands = build_lifecycle_commands(
        deployment_mode=DEPLOY_MODE_LOCAL,
        use_caddy=False,
        caddy_public=False,
    )
    assert (
        commands["start"]
        == "docker compose --env-file .env.production -f docker-compose.nocaddy.yml up -d"
    )


def test_build_lifecycle_commands_for_registry_bundle() -> None:
    commands = build_lifecycle_commands(
        deployment_mode=DEPLOY_MODE_REGISTRY,
        use_caddy=True,
        caddy_public=False,
    )

    assert (
        commands["pull"]
        == "docker compose --env-file .env.production -f docker-compose.image.yml pull"
    )
    assert (
        commands["start"]
        == "docker compose --env-file .env.production -f docker-compose.image.yml up -d"
    )


def test_build_lifecycle_commands_for_tarball_bundle() -> None:
    commands = build_lifecycle_commands(
        deployment_mode=DEPLOY_MODE_TARBALL,
        use_caddy=False,
        caddy_public=False,
        tarball_filename="custom-image.tar",
    )

    assert commands["load"] == "docker load -i custom-image.tar"
    assert (
        commands["start"]
        == "docker compose --env-file .env.production -f docker-compose.image.nocaddy.yml up -d"
    )


# ── check_prerequisites ─────────────────────────────────────────────


def test_check_prerequisites_checks_docker_and_compose(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr("cli.deploy_production.shutil.which", lambda _name: "/usr/bin/docker")
    commands = _stub_subprocess(monkeypatch)

    check_prerequisites(tmp_path)

    assert commands == [
        (["docker", "--version"], tmp_path, True),
        (["docker", "compose", "version"], tmp_path, True),
    ]


# ── backup_file / backup_existing_configs ────────────────────────────


def test_backup_file_returns_none_for_missing_file(tmp_path: Path) -> None:
    assert backup_file(tmp_path / "missing.txt") is None


def test_backup_file_creates_bak_copy(tmp_path: Path) -> None:
    original = tmp_path / "config.env"
    original.write_text("SECRET=abc", encoding="utf-8")

    result = backup_file(original)

    assert result is not None
    assert result.name == "config.env.bak"
    assert result.read_text(encoding="utf-8") == "SECRET=abc"


def test_backup_existing_configs_backs_up_present_files(tmp_path: Path) -> None:
    (tmp_path / ".env.production").write_text("old", encoding="utf-8")
    (tmp_path / "Caddyfile.production").write_text("old", encoding="utf-8")

    messages = backup_existing_configs(tmp_path)

    assert len(messages) == 2
    assert (tmp_path / ".env.production.bak").exists()
    assert (tmp_path / "Caddyfile.production.bak").exists()


def test_backup_existing_configs_skips_absent_files(tmp_path: Path) -> None:
    messages = backup_existing_configs(tmp_path)
    assert messages == []


# ── write_config_files ───────────────────────────────────────────────


def test_write_config_files_without_caddy(tmp_path: Path) -> None:
    config = _make_config()
    write_config_files(config, tmp_path)

    assert (tmp_path / ".env.production").exists()
    assert (tmp_path / "docker-compose.nocaddy.yml").exists()
    assert not (tmp_path / "Caddyfile.production").exists()
    assert not (tmp_path / "docker-compose.caddy-public.yml").exists()


def test_write_config_files_with_caddy_local(tmp_path: Path) -> None:
    config = _make_config(
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
    )
    write_config_files(config, tmp_path)

    assert (tmp_path / ".env.production").exists()
    assert (tmp_path / "Caddyfile.production").exists()
    assert not (tmp_path / "docker-compose.nocaddy.yml").exists()
    assert not (tmp_path / "docker-compose.caddy-public.yml").exists()


def test_write_config_files_with_caddy_public(tmp_path: Path) -> None:
    config = _make_config(
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        caddy_public=True,
        host_bind_ip=LOCALHOST_BIND_IP,
    )
    write_config_files(config, tmp_path)

    assert (tmp_path / ".env.production").exists()
    assert (tmp_path / "Caddyfile.production").exists()
    assert (tmp_path / "docker-compose.caddy-public.yml").exists()
    assert not (tmp_path / "docker-compose.nocaddy.yml").exists()


def test_write_config_files_cleans_up_stale_files(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.caddy-public.yml").write_text("old", encoding="utf-8")
    (tmp_path / "docker-compose.nocaddy.yml").write_text("old", encoding="utf-8")

    config = _make_config()
    write_config_files(config, tmp_path)

    assert not (tmp_path / "docker-compose.caddy-public.yml").exists()
    assert (tmp_path / "docker-compose.nocaddy.yml").exists()


# ── deploy ───────────────────────────────────────────────────────────


def test_deploy_writes_env_file_and_runs_docker_compose_without_caddy(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    commands = _stub_subprocess(monkeypatch)
    _stub_no_trivy(monkeypatch)

    config = _make_config()
    result = deploy(config=config, project_dir=tmp_path)

    captured = capsys.readouterr()
    assert (
        "Warning: Trivy is not installed or not available on PATH; skipping Docker image scan."
        in captured.err
    )
    assert result.env_path == tmp_path / ".env.production"
    assert (
        result.commands["start"]
        == "docker compose --env-file .env.production -f docker-compose.nocaddy.yml up -d"
    )
    assert result.bundle_path is None
    assert (tmp_path / DEFAULT_NO_CADDY_COMPOSE_FILE).exists()
    assert not (tmp_path / "Caddyfile.production").exists()
    assert not (tmp_path / DEFAULT_CADDY_PUBLIC_COMPOSE_FILE).exists()
    assert commands == [
        (
            [
                "docker",
                "compose",
                "--env-file",
                ".env.production",
                "-f",
                "docker-compose.nocaddy.yml",
                "up",
                "-d",
                "--build",
            ],
            tmp_path,
            True,
        )
    ]


def test_deploy_with_public_caddy_writes_override_and_runs_multi_file_compose(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    commands = _stub_subprocess(monkeypatch)
    _stub_no_trivy(monkeypatch)

    config = DeployConfig(
        secret_key="x" * 64,
        admin_username="admin",
        admin_password="very-strong-password",
        trusted_hosts=["blog.example.com"],
        trusted_proxy_ips=[],
        host_port=8000,
        host_bind_ip=LOCALHOST_BIND_IP,
        caddy_config=CaddyConfig(domain="blog.example.com", email="ops@example.com"),
        caddy_public=True,
        expose_docs=False,
        deployment_mode=DEPLOY_MODE_LOCAL,
        image_ref=None,
        bundle_dir=DEFAULT_BUNDLE_DIR,
        tarball_filename=DEFAULT_IMAGE_TARBALL,
    )

    result = deploy(config=config, project_dir=tmp_path)

    assert not (tmp_path / DEFAULT_NO_CADDY_COMPOSE_FILE).exists()
    assert (tmp_path / "Caddyfile.production").exists()
    assert (tmp_path / DEFAULT_CADDY_PUBLIC_COMPOSE_FILE).exists()
    assert (
        result.commands["start"]
        == "docker compose --env-file .env.production -f docker-compose.yml "
        "-f docker-compose.caddy-public.yml up -d"
    )
    assert commands == [
        (
            [
                "docker",
                "compose",
                "--env-file",
                ".env.production",
                "-f",
                "docker-compose.yml",
                "-f",
                "docker-compose.caddy-public.yml",
                "up",
                "-d",
                "--build",
            ],
            tmp_path,
            True,
        )
    ]


def test_deploy_with_local_caddy_runs_base_compose(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    commands = _stub_subprocess(monkeypatch)
    _stub_no_trivy(monkeypatch)

    config = DeployConfig(
        secret_key="x" * 64,
        admin_username="admin",
        admin_password="very-strong-password",
        trusted_hosts=["blog.example.com"],
        trusted_proxy_ips=[],
        host_port=8000,
        host_bind_ip=LOCALHOST_BIND_IP,
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        caddy_public=False,
        expose_docs=False,
        deployment_mode=DEPLOY_MODE_LOCAL,
        image_ref=None,
        bundle_dir=DEFAULT_BUNDLE_DIR,
        tarball_filename=DEFAULT_IMAGE_TARBALL,
    )

    result = deploy(config=config, project_dir=tmp_path)

    assert result.commands["start"] == "docker compose --env-file .env.production up -d"
    assert commands == [
        (
            [
                "docker",
                "compose",
                "--env-file",
                ".env.production",
                "up",
                "-d",
                "--build",
            ],
            tmp_path,
            True,
        )
    ]


def test_deploy_requires_docker_compose_file(tmp_path: Path) -> None:
    config = _make_config()

    with pytest.raises(FileNotFoundError, match=r"docker-compose\.yml"):
        deploy(config=config, project_dir=tmp_path)


def test_deploy_runs_trivy_scan_before_compose_up(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    commands = _stub_subprocess(monkeypatch)
    _stub_with_trivy(monkeypatch)

    config = _make_config()
    deploy(config=config, project_dir=tmp_path)

    assert commands == [
        (["trivy", "--version"], tmp_path, True),
        (
            [
                "docker",
                "compose",
                "--env-file",
                ".env.production",
                "-f",
                "docker-compose.nocaddy.yml",
                "build",
            ],
            tmp_path,
            True,
        ),
        (
            [
                "trivy",
                "image",
                "--scanners",
                "vuln",
                "--exit-code",
                "1",
                "--severity",
                "MEDIUM,HIGH,CRITICAL",
                LOCAL_IMAGE_TAG,
            ],
            tmp_path,
            True,
        ),
        (
            [
                "docker",
                "compose",
                "--env-file",
                ".env.production",
                "-f",
                "docker-compose.nocaddy.yml",
                "up",
                "-d",
            ],
            tmp_path,
            True,
        ),
    ]


def test_deploy_registry_mode_builds_pushes_and_writes_bundle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    commands = _stub_subprocess(monkeypatch)
    _stub_no_trivy(monkeypatch)

    config = _make_config(
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
        deployment_mode=DEPLOY_MODE_REGISTRY,
        image_ref="ghcr.io/example/agblogger:1.2.3",
    )

    result = deploy(config=config, project_dir=tmp_path)

    assert result.bundle_path == tmp_path / DEFAULT_BUNDLE_DIR
    assert result.env_path == tmp_path / DEFAULT_BUNDLE_DIR / ".env.production"
    assert (tmp_path / DEFAULT_BUNDLE_DIR / DEFAULT_IMAGE_COMPOSE_FILE).exists()
    assert not (tmp_path / DEFAULT_BUNDLE_DIR / DEFAULT_IMAGE_NO_CADDY_COMPOSE_FILE).exists()
    assert commands == [
        (
            [
                "docker",
                "build",
                "--tag",
                "ghcr.io/example/agblogger:1.2.3",
                ".",
            ],
            tmp_path,
            True,
        ),
        (
            ["docker", "push", "ghcr.io/example/agblogger:1.2.3"],
            tmp_path,
            True,
        ),
    ]


def test_deploy_tarball_mode_builds_saves_and_writes_bundle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    commands = _stub_subprocess(monkeypatch)
    _stub_no_trivy(monkeypatch)

    config = _make_config(
        deployment_mode=DEPLOY_MODE_TARBALL,
        image_ref="agblogger:portable",
    )

    result = deploy(config=config, project_dir=tmp_path)

    assert result.bundle_path == tmp_path / DEFAULT_BUNDLE_DIR
    assert result.env_path == tmp_path / DEFAULT_BUNDLE_DIR / ".env.production"
    assert (tmp_path / DEFAULT_BUNDLE_DIR / DEFAULT_IMAGE_NO_CADDY_COMPOSE_FILE).exists()
    assert commands == [
        (
            ["docker", "build", "--tag", "agblogger:portable", "."],
            tmp_path,
            True,
        ),
        (
            [
                "docker",
                "save",
                "--output",
                str(tmp_path / DEFAULT_BUNDLE_DIR / DEFAULT_IMAGE_TARBALL),
                "agblogger:portable",
            ],
            tmp_path,
            True,
        ),
    ]


def test_deploy_backs_up_existing_env_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (tmp_path / ".env.production").write_text("OLD_SECRET=123\n", encoding="utf-8")
    _stub_subprocess(monkeypatch)
    _stub_no_trivy(monkeypatch)

    config = _make_config()
    deploy(config=config, project_dir=tmp_path)

    backup = tmp_path / ".env.production.bak"
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == "OLD_SECRET=123\n"
    assert "OLD_SECRET" not in (tmp_path / ".env.production").read_text(encoding="utf-8")


# ── dry_run ──────────────────────────────────────────────────────────


def test_dry_run_prints_masked_env_and_lifecycle_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _make_config()
    dry_run(config)

    captured = capsys.readouterr().out
    assert "=== .env.production ===" in captured
    assert "********" in captured
    assert "x" * 64 not in captured
    assert "very-strong-password" not in captured
    assert "=== docker-compose.nocaddy.yml ===" in captured
    assert "=== Lifecycle commands ===" in captured


def test_dry_run_with_caddy_shows_caddyfile(capsys: pytest.CaptureFixture[str]) -> None:
    config = _make_config(
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        caddy_public=True,
        host_bind_ip=LOCALHOST_BIND_IP,
    )
    dry_run(config)

    captured = capsys.readouterr().out
    assert "=== Caddyfile.production ===" in captured
    assert "blog.example.com" in captured
    assert f"=== {DEFAULT_CADDY_PUBLIC_COMPOSE_FILE} ===" in captured


# ── config_from_args ─────────────────────────────────────────────────


def test_config_from_args_builds_config_without_caddy() -> None:
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password="strong-password!",
        caddy_domain=None,
        caddy_email=None,
        caddy_public=False,
        trusted_hosts="example.com,www.example.com",
        trusted_proxy_ips=None,
        host_port=9000,
        bind_public=True,
        expose_docs=False,
        deployment_mode=DEPLOY_MODE_LOCAL,
        image_ref=None,
        bundle_dir=DEFAULT_BUNDLE_DIR,
        tarball_filename=DEFAULT_IMAGE_TARBALL,
    )

    config = config_from_args(args)

    assert config.admin_username == "admin"
    assert config.host_port == 9000
    assert config.host_bind_ip == PUBLIC_BIND_IP
    assert config.caddy_config is None
    assert config.trusted_hosts == ["example.com", "www.example.com"]
    assert config.deployment_mode == DEPLOY_MODE_LOCAL


def test_config_from_args_builds_config_with_caddy() -> None:
    args = argparse.Namespace(
        secret_key=None,
        admin_username="admin",
        admin_password="strong-password!",
        caddy_domain="blog.example.com",
        caddy_email="ops@example.com",
        caddy_public=True,
        trusted_hosts="blog.example.com",
        trusted_proxy_ips="10.0.0.1",
        host_port=8000,
        bind_public=False,
        expose_docs=True,
        deployment_mode=DEPLOY_MODE_LOCAL,
        image_ref=None,
        bundle_dir=DEFAULT_BUNDLE_DIR,
        tarball_filename=DEFAULT_IMAGE_TARBALL,
    )

    config = config_from_args(args)

    assert config.caddy_config is not None
    assert config.caddy_config.domain == "blog.example.com"
    assert config.caddy_public is True
    assert config.host_bind_ip == LOCALHOST_BIND_IP
    assert config.expose_docs is True
    assert config.trusted_proxy_ips == [COMPOSE_SUBNET, "10.0.0.1"]


def test_config_from_args_auto_generates_secret_key() -> None:
    args = argparse.Namespace(
        secret_key=None,
        admin_username="admin",
        admin_password="strong-password!",
        caddy_domain=None,
        caddy_email=None,
        caddy_public=False,
        trusted_hosts="example.com",
        trusted_proxy_ips=None,
        host_port=8000,
        bind_public=False,
        expose_docs=False,
        deployment_mode=DEPLOY_MODE_LOCAL,
        image_ref=None,
        bundle_dir=DEFAULT_BUNDLE_DIR,
        tarball_filename=DEFAULT_IMAGE_TARBALL,
    )

    config = config_from_args(args)
    assert len(config.secret_key) >= MIN_SECRET_KEY_LENGTH


def test_config_from_args_auto_appends_caddy_domain_to_trusted_hosts() -> None:
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password="strong-password!",
        caddy_domain="blog.example.com",
        caddy_email=None,
        caddy_public=False,
        trusted_hosts="other.example.com",
        trusted_proxy_ips=None,
        host_port=8000,
        bind_public=False,
        expose_docs=False,
        deployment_mode=DEPLOY_MODE_LOCAL,
        image_ref=None,
        bundle_dir=DEFAULT_BUNDLE_DIR,
        tarball_filename=DEFAULT_IMAGE_TARBALL,
    )

    config = config_from_args(args)
    assert "blog.example.com" in config.trusted_hosts


def test_config_from_args_raises_on_missing_admin_username() -> None:
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username=None,
        admin_password="strong-password!",
        caddy_domain=None,
        caddy_email=None,
        caddy_public=False,
        trusted_hosts="example.com",
        trusted_proxy_ips=None,
        host_port=8000,
        bind_public=False,
        expose_docs=False,
        deployment_mode=DEPLOY_MODE_LOCAL,
        image_ref=None,
        bundle_dir=DEFAULT_BUNDLE_DIR,
        tarball_filename=DEFAULT_IMAGE_TARBALL,
    )

    with pytest.raises(DeployError, match="--admin-username"):
        config_from_args(args)


def test_config_from_args_raises_on_missing_admin_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password=None,
        caddy_domain=None,
        caddy_email=None,
        caddy_public=False,
        trusted_hosts="example.com",
        trusted_proxy_ips=None,
        host_port=8000,
        bind_public=False,
        expose_docs=False,
        deployment_mode=DEPLOY_MODE_LOCAL,
        image_ref=None,
        bundle_dir=DEFAULT_BUNDLE_DIR,
        tarball_filename=DEFAULT_IMAGE_TARBALL,
    )

    with pytest.raises(DeployError, match="--admin-password"):
        config_from_args(args)


def test_config_from_args_raises_on_missing_trusted_hosts() -> None:
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password="strong-password!",
        caddy_domain=None,
        caddy_email=None,
        caddy_public=False,
        trusted_hosts=None,
        trusted_proxy_ips=None,
        host_port=8000,
        bind_public=False,
        expose_docs=False,
        deployment_mode=DEPLOY_MODE_LOCAL,
        image_ref=None,
        bundle_dir=DEFAULT_BUNDLE_DIR,
        tarball_filename=DEFAULT_IMAGE_TARBALL,
    )

    with pytest.raises(DeployError, match="--trusted-hosts"):
        config_from_args(args)


def test_config_from_args_requires_image_ref_for_registry_mode() -> None:
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password="strong-password!",
        caddy_domain=None,
        caddy_email=None,
        caddy_public=False,
        trusted_hosts="example.com",
        trusted_proxy_ips=None,
        host_port=8000,
        bind_public=False,
        expose_docs=False,
        deployment_mode=DEPLOY_MODE_REGISTRY,
        image_ref=None,
        bundle_dir=DEFAULT_BUNDLE_DIR,
        tarball_filename=DEFAULT_IMAGE_TARBALL,
    )

    with pytest.raises(DeployError, match="--image-ref"):
        config_from_args(args)


def test_config_from_args_builds_registry_mode() -> None:
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password="strong-password!",
        caddy_domain=None,
        caddy_email=None,
        caddy_public=False,
        trusted_hosts="example.com",
        trusted_proxy_ips=None,
        host_port=8000,
        bind_public=False,
        expose_docs=False,
        deployment_mode=DEPLOY_MODE_REGISTRY,
        image_ref="ghcr.io/example/agblogger:1.2.3",
        bundle_dir=DEFAULT_BUNDLE_DIR,
        tarball_filename=DEFAULT_IMAGE_TARBALL,
    )

    config = config_from_args(args)

    assert config.deployment_mode == DEPLOY_MODE_REGISTRY
    assert config.image_ref == "ghcr.io/example/agblogger:1.2.3"


# ── chmod warning on write_config_files ───────────────────────────────


def test_write_config_files_warns_on_chmod_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _make_config()
    with patch("pathlib.Path.chmod", side_effect=OSError("permission denied")):
        write_config_files(config, tmp_path)
    captured = capsys.readouterr()
    assert "Warning" in captured.err
    assert ".env.production" in captured.err


# ── trusted host validation ──────────────────────────────────────────


def test_validate_config_rejects_wildcard_trusted_host() -> None:
    config = DeployConfig(
        secret_key="x" * 64,
        admin_username="admin",
        admin_password="very-strong-password",
        trusted_hosts=["*"],
        trusted_proxy_ips=[],
        host_port=8000,
        host_bind_ip=PUBLIC_BIND_IP,
        caddy_config=None,
        caddy_public=False,
        expose_docs=False,
    )

    with pytest.raises(DeployError, match="Invalid trusted host"):
        from cli.deploy_production import _validate_config

        _validate_config(config)


def test_validate_config_accepts_subdomain_wildcard() -> None:
    config = DeployConfig(
        secret_key="x" * 64,
        admin_username="admin",
        admin_password="very-strong-password",
        trusted_hosts=["*.example.com"],
        trusted_proxy_ips=[],
        host_port=8000,
        host_bind_ip=PUBLIC_BIND_IP,
        caddy_config=None,
        caddy_public=False,
        expose_docs=False,
    )

    from cli.deploy_production import _validate_config

    _validate_config(config)


# ── caddy proxy auto-config ──────────────────────────────────────────


def test_config_from_args_auto_adds_caddy_proxy_subnet() -> None:
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password="strong-password!",
        caddy_domain="blog.example.com",
        caddy_email=None,
        caddy_public=False,
        trusted_hosts="blog.example.com",
        trusted_proxy_ips=None,
        host_port=8000,
        bind_public=False,
        expose_docs=False,
        deployment_mode=DEPLOY_MODE_LOCAL,
        image_ref=None,
        bundle_dir=DEFAULT_BUNDLE_DIR,
        tarball_filename=DEFAULT_IMAGE_TARBALL,
    )

    config = config_from_args(args)
    assert COMPOSE_SUBNET in config.trusted_proxy_ips


def test_config_from_args_no_caddy_does_not_add_proxy_subnet() -> None:
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password="strong-password!",
        caddy_domain=None,
        caddy_email=None,
        caddy_public=False,
        trusted_hosts="example.com",
        trusted_proxy_ips=None,
        host_port=8000,
        bind_public=False,
        expose_docs=False,
        deployment_mode=DEPLOY_MODE_LOCAL,
        image_ref=None,
        bundle_dir=DEFAULT_BUNDLE_DIR,
        tarball_filename=DEFAULT_IMAGE_TARBALL,
    )

    config = config_from_args(args)
    assert config.trusted_proxy_ips == []


# ── admin password env var fallback ──────────────────────────────────


def test_config_from_args_reads_admin_password_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "env-password-123")
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password=None,
        caddy_domain=None,
        caddy_email=None,
        caddy_public=False,
        trusted_hosts="example.com",
        trusted_proxy_ips=None,
        host_port=8000,
        bind_public=False,
        expose_docs=False,
        deployment_mode=DEPLOY_MODE_LOCAL,
        image_ref=None,
        bundle_dir=DEFAULT_BUNDLE_DIR,
        tarball_filename=DEFAULT_IMAGE_TARBALL,
    )

    config = config_from_args(args)
    assert config.admin_password == "env-password-123"
