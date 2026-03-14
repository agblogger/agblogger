"""Tests for production deployment CLI workflow."""

from __future__ import annotations

import argparse
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from cli.deploy_production import (
    AGBLOGGER_STATIC_IP,
    CADDY_MODE_BUNDLED,
    CADDY_MODE_EXTERNAL,
    CADDY_MODE_NONE,
    CADDY_STATIC_IP,
    COMPOSE_SUBNET,
    DEFAULT_BUNDLE_DIR,
    DEFAULT_CADDY_PUBLIC_COMPOSE_FILE,
    DEFAULT_ENV_FILE,
    DEFAULT_IMAGE_COMPOSE_FILE,
    DEFAULT_IMAGE_NO_CADDY_COMPOSE_FILE,
    DEFAULT_IMAGE_TARBALL,
    DEFAULT_NO_CADDY_COMPOSE_FILE,
    DEFAULT_REMOTE_PLATFORM,
    DEFAULT_SHARED_CADDY_DIR,
    DEPLOY_MODE_LOCAL,
    DEPLOY_MODE_REGISTRY,
    DEPLOY_MODE_TARBALL,
    EXTERNAL_CADDY_NETWORK_NAME,
    LOCAL_IMAGE_TAG,
    LOCALHOST_BIND_IP,
    MIN_SECRET_KEY_LENGTH,
    PUBLIC_BIND_IP,
    CaddyConfig,
    DeployConfig,
    DeployError,
    SharedCaddyConfig,
    _build_remote_readme_content,
    _is_valid_caddy_domain,
    _read_version,
    _unquote_env_value,
    backup_existing_configs,
    backup_file,
    build_caddy_public_compose_override_content,
    build_caddyfile_content,
    build_direct_compose_content,
    build_env_content,
    build_image,
    build_image_compose_content,
    build_image_direct_compose_content,
    build_lifecycle_commands,
    check_prerequisites,
    config_from_args,
    deploy,
    dry_run,
    parse_csv_list,
    parse_existing_env,
    print_config_summary,
    write_bundle_files,
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
    platform: str | None = None,
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
        platform=platform,
    )


def _stub_subprocess(monkeypatch: pytest.MonkeyPatch) -> list[tuple[list[str], Path, bool]]:
    """Stub subprocess.run and return a list that captures all calls.

    Also stubs ``_wait_for_healthy`` to a no-op so deploy tests do not
    need to account for health-poll subprocess calls.
    """
    commands: list[tuple[list[str], Path, bool]] = []

    def fake_run(command: list[str], cwd: Path, check: bool, **kwargs: object) -> SimpleNamespace:
        commands.append((command, cwd, check))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("cli.deploy_production.subprocess.run", fake_run)
    monkeypatch.setattr("cli.deploy_production._wait_for_healthy", lambda *_a, **_kw: None)
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


def test_build_caddyfile_content_enables_hsts_for_https_deployments() -> None:
    caddy = CaddyConfig(domain="blog.example.com", email=None)
    content = build_caddyfile_content(caddy)

    assert "Strict-Transport-Security" in content
    assert "max-age=31536000" in content


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
    assert f"ipv4_address: {AGBLOGGER_STATIC_IP}" in content
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
    assert (
        commands["start"] == "docker compose --env-file .env.production -f docker-compose.yml up -d"
    )
    assert (
        commands["stop"] == "docker compose --env-file .env.production -f docker-compose.yml down"
    )
    assert (
        commands["status"] == "docker compose --env-file .env.production -f docker-compose.yml ps"
    )


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
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
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

    assert (
        result.commands["start"]
        == "docker compose --env-file .env.production -f docker-compose.yml up -d"
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
                "up",
                "-d",
                "--build",
            ],
            tmp_path,
            True,
        )
    ]


def test_check_prerequisites_requires_docker_compose_file_for_local_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    monkeypatch.setattr("cli.deploy_production.shutil.which", lambda _name: "/usr/bin/docker")
    with pytest.raises(DeployError, match=r"docker compose file"):
        check_prerequisites(tmp_path, DEPLOY_MODE_LOCAL)


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
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
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
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
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
        admin_display_name=None,
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
        platform=None,
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
        admin_display_name=None,
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
        platform=None,
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
        admin_display_name=None,
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
        platform=None,
    )

    config = config_from_args(args)
    assert len(config.secret_key) >= MIN_SECRET_KEY_LENGTH


def test_config_from_args_auto_appends_caddy_domain_to_trusted_hosts() -> None:
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password="strong-password!",
        admin_display_name=None,
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
        platform=None,
    )

    config = config_from_args(args)
    assert "blog.example.com" in config.trusted_hosts


def test_config_from_args_raises_on_missing_admin_username() -> None:
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username=None,
        admin_password="strong-password!",
        admin_display_name=None,
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
        platform=None,
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
        admin_display_name=None,
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
        platform=None,
    )

    with pytest.raises(DeployError, match="--admin-password"):
        config_from_args(args)


def test_config_from_args_raises_on_missing_trusted_hosts() -> None:
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password="strong-password!",
        admin_display_name=None,
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
        platform=None,
    )

    with pytest.raises(DeployError, match="--trusted-hosts"):
        config_from_args(args)


def test_config_from_args_requires_image_ref_for_registry_mode() -> None:
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password="strong-password!",
        admin_display_name=None,
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
        platform=None,
    )

    with pytest.raises(DeployError, match="--image-ref"):
        config_from_args(args)


def test_config_from_args_builds_registry_mode() -> None:
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password="strong-password!",
        admin_display_name=None,
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
        platform=None,
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
    assert "WARNING" in captured.err
    assert ".env.production" in captured.err
    assert "sensitive secrets" in captured.err


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
        admin_display_name=None,
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
        platform=None,
    )

    config = config_from_args(args)
    assert COMPOSE_SUBNET in config.trusted_proxy_ips


def test_config_from_args_no_caddy_does_not_add_proxy_subnet() -> None:
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password="strong-password!",
        admin_display_name=None,
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
        platform=None,
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
        admin_display_name=None,
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
        platform=None,
    )

    config = config_from_args(args)
    assert config.admin_password == "env-password-123"


# ── caddy depends_on with health condition ────────────────────────────


def test_caddy_service_section_uses_service_healthy_condition() -> None:
    content = build_image_compose_content()
    assert "condition: service_healthy" in content


def test_docker_compose_yml_caddy_depends_on_healthy() -> None:
    from cli.deploy_production import _caddy_service_section

    section = _caddy_service_section()
    assert "condition: service_healthy" in section
    assert "- agblogger" not in section


# ── caddyfile HTML matcher ────────────────────────────────────────────


def test_build_caddyfile_content_html_cache_matches_all_depths() -> None:
    caddy = CaddyConfig(domain="blog.example.com", email=None)
    content = build_caddyfile_content(caddy)
    assert r"@html path_regexp \.html$" in content
    assert "header @html" in content


# ── error message includes command ────────────────────────────────────


def test_main_checks_docker_before_config_collection(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Issue 2: Docker check should run before interactive config collection."""
    from cli.deploy_production import main

    monkeypatch.setattr(
        "sys.argv",
        [
            "deploy",
            "--non-interactive",
            "--project-dir",
            str(tmp_path),
            "--admin-username",
            "admin",
            "--admin-password",
            "strong-password!",
            "--trusted-hosts",
            "example.com",
        ],
    )
    monkeypatch.setattr("cli.deploy_production.shutil.which", lambda _name: None)

    def _must_not_be_called(_args: object) -> None:
        raise AssertionError("config_from_args should not be called when Docker is missing")

    monkeypatch.setattr("cli.deploy_production.config_from_args", _must_not_be_called)

    with pytest.raises(SystemExit, match="1"):
        main()

    captured = capsys.readouterr()
    assert "Docker is not installed" in captured.out


def test_main_subprocess_error_includes_command(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import subprocess as sp

    from cli.deploy_production import main

    monkeypatch.setattr(
        "sys.argv",
        [
            "deploy",
            "--non-interactive",
            "--project-dir",
            str(tmp_path),
            "--admin-username",
            "admin",
            "--admin-password",
            "strong-password!",
            "--trusted-hosts",
            "example.com",
        ],
    )
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    monkeypatch.setattr("cli.deploy_production.shutil.which", lambda _name: "/usr/bin/docker")

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        # Let the daemon check pass, fail on subsequent commands
        if command == ["docker", "info"]:
            return SimpleNamespace(returncode=0)
        raise sp.CalledProcessError(returncode=1, cmd=command)

    monkeypatch.setattr("cli.deploy_production.subprocess.run", fake_run)

    with pytest.raises(SystemExit, match="1"):
        main()

    captured = capsys.readouterr()
    assert "docker" in captured.out
    assert "exit code 1" in captured.out


# ── Issue 1: $ escaping in env values ─────────────────────────────────


def test_quote_env_value_escapes_dollar_signs() -> None:
    """Dollar signs must be escaped to prevent Docker Compose variable expansion."""
    from cli.deploy_production import _quote_env_value

    assert _quote_env_value("my$ecret") == '"my\\$ecret"'


def test_quote_env_value_escapes_backslash_dollar_combination() -> None:
    from cli.deploy_production import _quote_env_value

    assert _quote_env_value("a\\$b") == '"a\\\\\\$b"'


def test_build_env_content_escapes_dollar_in_password() -> None:
    config = DeployConfig(
        secret_key="x" * 64,
        admin_username="admin",
        admin_password="pass$word",
        trusted_hosts=["example.com"],
        trusted_proxy_ips=[],
        host_port=8000,
        host_bind_ip=PUBLIC_BIND_IP,
        caddy_config=None,
        caddy_public=False,
        expose_docs=False,
    )

    content = build_env_content(config)
    assert 'ADMIN_PASSWORD="pass\\$word"' in content


# ── Issue 3: logs lifecycle command ──────────────────────────────────


def test_build_lifecycle_commands_includes_logs() -> None:
    commands = build_lifecycle_commands(
        deployment_mode=DEPLOY_MODE_LOCAL,
        use_caddy=True,
        caddy_public=False,
    )
    assert "logs" in commands
    assert "logs -f" in commands["logs"]


# ── Issue 4: Caddy domain rejects IP addresses ──────────────────────


def test_validate_config_rejects_ipv4_as_caddy_domain() -> None:
    from cli.deploy_production import _validate_config

    config = _make_config(
        caddy_config=CaddyConfig(domain="127.0.0.1", email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
    )

    with pytest.raises(DeployError, match="valid public hostname"):
        _validate_config(config)


def test_validate_config_rejects_public_ipv4_as_caddy_domain() -> None:
    from cli.deploy_production import _validate_config

    config = _make_config(
        caddy_config=CaddyConfig(domain="93.184.216.34", email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
    )

    with pytest.raises(DeployError, match="valid public hostname"):
        _validate_config(config)


# ── Tighter domain validation ────────────────────────────────────────


@pytest.mark.parametrize(
    "domain",
    [
        "foo..bar",
        ".leading-dot.com",
        "trailing-dot.com.",
        "-hyphen-start.com",
        "hyphen-end-.com",
        "single",
        "has space.com",
        "",
    ],
)
def test_validate_config_rejects_invalid_caddy_domains(domain: str) -> None:
    from cli.deploy_production import _validate_config

    config = _make_config(
        caddy_config=CaddyConfig(domain=domain, email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
    )

    with pytest.raises(DeployError, match="valid public hostname"):
        _validate_config(config)


@pytest.mark.parametrize(
    "domain",
    [
        "blog.example.com",
        "my-blog.example.com",
        "a.b.c.d.example.com",
        "example.co.uk",
    ],
)
def test_validate_config_accepts_valid_caddy_domains(domain: str) -> None:
    from cli.deploy_production import _validate_config

    config = _make_config(
        caddy_config=CaddyConfig(domain=domain, email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
    )
    _validate_config(config)


# ── DEPLOY-REMOTE.md includes logs command ───────────────────────────


def test_remote_readme_includes_logs_command() -> None:
    from cli.deploy_production import _build_remote_readme_content

    config = _make_config(
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
        deployment_mode=DEPLOY_MODE_REGISTRY,
        image_ref="ghcr.io/example/agblogger:latest",
    )
    commands = build_lifecycle_commands(
        deployment_mode=DEPLOY_MODE_REGISTRY,
        use_caddy=True,
        caddy_public=False,
    )

    content = _build_remote_readme_content(config, commands)

    assert "Logs:" in content
    assert "logs -f" in content


# ── Health poll ──────────────────────────────────────────────────────


def test_wait_for_healthy_returns_when_service_healthy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from cli.deploy_production import _wait_for_healthy

    call_count = 0

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        nonlocal call_count
        call_count += 1
        return SimpleNamespace(returncode=0, stdout="agblogger: Up 10 seconds (healthy)\n")

    monkeypatch.setattr("cli.deploy_production.subprocess.run", fake_run)
    monkeypatch.setattr("cli.deploy_production.time.sleep", lambda _s: None)

    config = _make_config()
    _wait_for_healthy(config, tmp_path, timeout=30, interval=1)

    assert call_count >= 1


def test_wait_for_healthy_warns_on_timeout(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from cli.deploy_production import _wait_for_healthy

    # Simulate time passing quickly so the poll times out
    call_counter = 0

    def fake_monotonic() -> float:
        nonlocal call_counter
        call_counter += 1
        return float(call_counter * 100)

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout="agblogger: Up 3 seconds (starting)\n")

    monkeypatch.setattr("cli.deploy_production.subprocess.run", fake_run)
    monkeypatch.setattr("cli.deploy_production.time.sleep", lambda _s: None)
    monkeypatch.setattr("cli.deploy_production.time.monotonic", fake_monotonic)

    config = _make_config()
    with pytest.raises(DeployError, match="timed out"):
        _wait_for_healthy(config, tmp_path, timeout=10, interval=1)


# ── Config summary ───────────────────────────────────────────────────


def test_print_config_summary_shows_key_fields(capsys: pytest.CaptureFixture[str]) -> None:
    config = _make_config(
        caddy_config=CaddyConfig(domain="blog.example.com", email="ops@example.com"),
        caddy_public=True,
        host_bind_ip=LOCALHOST_BIND_IP,
    )

    print_config_summary(config)

    captured = capsys.readouterr().out
    assert "local" in captured
    assert "blog.example.com" in captured
    assert "ops@example.com" in captured
    assert "admin" in captured
    assert "yes" in captured


def test_print_config_summary_shows_no_caddy(capsys: pytest.CaptureFixture[str]) -> None:
    config = _make_config()

    print_config_summary(config)

    captured = capsys.readouterr().out
    assert "disabled" in captured
    assert f"{PUBLIC_BIND_IP}:8000" in captured


# ── Deploy progress messages ─────────────────────────────────────────


def test_deploy_prints_progress_messages(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    _stub_subprocess(monkeypatch)
    _stub_no_trivy(monkeypatch)

    config = _make_config()
    deploy(config=config, project_dir=tmp_path)

    captured = capsys.readouterr().out
    assert "Starting containers" in captured


# ── Review 4 fixes ──────────────────────────────────────────────────


class TestWaitForHealthyVacuousTruth:
    """Issue 1: _wait_for_healthy should not report success when agblogger is absent."""

    def test_raises_deploy_error_when_health_check_times_out(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.deploy_production import _wait_for_healthy

        def fake_monotonic() -> float:
            fake_monotonic.counter += 1  # type: ignore[attr-defined]
            return float(fake_monotonic.counter * 100)  # type: ignore[attr-defined]

        fake_monotonic.counter = 0  # type: ignore[attr-defined]

        def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(returncode=0, stdout="caddy: Up 10 seconds\n")

        monkeypatch.setattr("cli.deploy_production.subprocess.run", fake_run)
        monkeypatch.setattr("cli.deploy_production.time.sleep", lambda _s: None)
        monkeypatch.setattr("cli.deploy_production.time.monotonic", fake_monotonic)

        config = _make_config()
        with pytest.raises(DeployError, match="timed out"):
            _wait_for_healthy(config, tmp_path, timeout=10, interval=1)

    def test_reports_healthy_when_agblogger_present_and_healthy(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from cli.deploy_production import _wait_for_healthy

        def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(
                returncode=0,
                stdout="agblogger: Up 10 seconds (healthy)\ncaddy: Up 10 seconds\n",
            )

        monkeypatch.setattr("cli.deploy_production.subprocess.run", fake_run)
        monkeypatch.setattr("cli.deploy_production.time.sleep", lambda _s: None)

        config = _make_config()
        _wait_for_healthy(config, tmp_path, timeout=30, interval=1)

        captured = capsys.readouterr()
        assert "All services healthy" in captured.out


class TestInlineDomainValidation:
    """Issue 2: Inline validation for Caddy domain prompts."""

    @pytest.mark.parametrize(
        "domain",
        ["127.0.0.1", "93.184.216.34", "single", "foo..bar", "-bad.com", ""],
    )
    def test_is_valid_caddy_domain_rejects_invalid(self, domain: str) -> None:
        assert not _is_valid_caddy_domain(domain)

    @pytest.mark.parametrize(
        "domain",
        ["blog.example.com", "my-blog.io", "a.b.c.d.example.com", "example.co.uk"],
    )
    def test_is_valid_caddy_domain_accepts_valid(self, domain: str) -> None:
        assert _is_valid_caddy_domain(domain)


class TestEnvContentCaddyComments:
    """Issue 5: HOST_PORT/HOST_BIND_IP have clarifying comments in Caddy mode."""

    def test_caddy_mode_adds_comment_to_host_port(self) -> None:
        config = _make_config(
            caddy_config=CaddyConfig(domain="blog.example.com", email=None),
            host_bind_ip=LOCALHOST_BIND_IP,
        )
        content = build_env_content(config)
        assert "HOST_PORT=8000  # Only used in no-Caddy mode" in content
        assert "HOST_BIND_IP=127.0.0.1  # Only used in no-Caddy mode" in content

    def test_no_caddy_mode_omits_comment(self) -> None:
        config = _make_config()
        content = build_env_content(config)
        assert "HOST_PORT=8000\n" in content
        assert "# Only used in no-Caddy mode" not in content


class TestEnvContentBlueskyComment:
    """Issue 7: Commented BLUESKY_CLIENT_URL in env file."""

    def test_env_content_includes_bluesky_comment(self) -> None:
        config = _make_config()
        content = build_env_content(config)
        assert "# BLUESKY_CLIENT_URL=" in content
        assert "Uncomment to enable Bluesky cross-posting" in content


class TestRemoteReadmeFormatting:
    """Issue 6: DEPLOY-REMOTE.md steps use code blocks."""

    def test_registry_readme_uses_code_blocks(self) -> None:
        config = _make_config(
            caddy_config=CaddyConfig(domain="blog.example.com", email=None),
            host_bind_ip=LOCALHOST_BIND_IP,
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:v1",
        )
        commands = build_lifecycle_commands(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            use_caddy=True,
            caddy_public=False,
        )
        content = _build_remote_readme_content(config, commands)
        assert "```" in content
        assert "Pull the image:" in content
        assert "Start the services:" in content
        assert "Verify the services are running:" in content
        assert "## Management commands" in content

    def test_tarball_readme_uses_code_blocks(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1",
        )
        commands = build_lifecycle_commands(
            deployment_mode=DEPLOY_MODE_TARBALL,
            use_caddy=False,
            caddy_public=False,
        )
        content = _build_remote_readme_content(config, commands)
        assert "```" in content
        assert "Load the image:" in content


class TestCommandTimeout:
    """Issue 4: subprocess calls have a timeout."""

    def test_run_command_passes_timeout(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.deploy_production import COMMAND_TIMEOUT_SECONDS, _run_command

        captured_kwargs: dict[str, object] = {}

        def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
            captured_kwargs.update(kwargs)
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr("cli.deploy_production.subprocess.run", fake_run)
        _run_command(["echo", "hello"], tmp_path)
        assert captured_kwargs["timeout"] == COMMAND_TIMEOUT_SECONDS

    def test_run_command_accepts_custom_timeout(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.deploy_production import _run_command

        captured_kwargs: dict[str, object] = {}

        def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
            captured_kwargs.update(kwargs)
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr("cli.deploy_production.subprocess.run", fake_run)
        _run_command(["echo", "hello"], tmp_path, timeout=42)
        assert captured_kwargs["timeout"] == 42


class TestWaitForHealthyWithCaddy:
    """Health poll should also check Caddy container status when Caddy is enabled."""

    def test_waits_for_caddy_when_caddy_enabled(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from cli.deploy_production import _wait_for_healthy

        call_count = 0

        def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Caddy hasn't started yet (depends_on waits for agblogger healthy)
                return SimpleNamespace(
                    returncode=0,
                    stdout="agblogger: Up 10 seconds (healthy)\n",
                )
            return SimpleNamespace(
                returncode=0,
                stdout="agblogger: Up 15 seconds (healthy)\ncaddy: Up 8 seconds\n",
            )

        monkeypatch.setattr("cli.deploy_production.subprocess.run", fake_run)
        monkeypatch.setattr("cli.deploy_production.time.sleep", lambda _s: None)

        config = _make_config(
            caddy_config=CaddyConfig(domain="blog.example.com", email=None),
            host_bind_ip=LOCALHOST_BIND_IP,
        )
        _wait_for_healthy(config, tmp_path, timeout=30, interval=1)

        captured = capsys.readouterr()
        assert "All services healthy" in captured.out
        assert call_count == 2

    def test_times_out_when_caddy_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from cli.deploy_production import _wait_for_healthy

        call_counter = 0

        def fake_monotonic() -> float:
            nonlocal call_counter
            call_counter += 1
            return float(call_counter * 100)

        def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(
                returncode=0,
                stdout="agblogger: Up 10 seconds (healthy)\n",
            )

        monkeypatch.setattr("cli.deploy_production.subprocess.run", fake_run)
        monkeypatch.setattr("cli.deploy_production.time.sleep", lambda _s: None)
        monkeypatch.setattr("cli.deploy_production.time.monotonic", fake_monotonic)

        config = _make_config(
            caddy_config=CaddyConfig(domain="blog.example.com", email=None),
            host_bind_ip=LOCALHOST_BIND_IP,
        )
        with pytest.raises(DeployError, match="timed out"):
            _wait_for_healthy(config, tmp_path, timeout=10, interval=1)

    def test_skips_caddy_check_when_caddy_disabled(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from cli.deploy_production import _wait_for_healthy

        def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(
                returncode=0,
                stdout="agblogger: Up 10 seconds (healthy)\n",
            )

        monkeypatch.setattr("cli.deploy_production.subprocess.run", fake_run)
        monkeypatch.setattr("cli.deploy_production.time.sleep", lambda _s: None)

        config = _make_config()
        _wait_for_healthy(config, tmp_path, timeout=30, interval=1)

        captured = capsys.readouterr()
        assert "All services healthy" in captured.out


class TestDryRunLocalCaddyNonPublic:
    """Dry run should note existing docker-compose.yml for local+caddy (non-public) mode."""

    def test_dry_run_local_caddy_non_public_notes_existing_compose(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = _make_config(
            caddy_config=CaddyConfig(domain="blog.example.com", email=None),
            caddy_public=False,
            host_bind_ip=LOCALHOST_BIND_IP,
        )
        dry_run(config)

        captured = capsys.readouterr().out
        assert "Using existing docker-compose.yml" in captured
        assert "=== Caddyfile.production ===" in captured
        assert f"=== {DEFAULT_CADDY_PUBLIC_COMPOSE_FILE} ===" not in captured

    def test_dry_run_local_caddy_public_does_not_note_existing_compose(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = _make_config(
            caddy_config=CaddyConfig(domain="blog.example.com", email=None),
            caddy_public=True,
            host_bind_ip=LOCALHOST_BIND_IP,
        )
        dry_run(config)

        captured = capsys.readouterr().out
        assert "Using existing docker-compose.yml" in captured
        assert "=== Caddyfile.production ===" in captured
        assert f"=== {DEFAULT_CADDY_PUBLIC_COMPOSE_FILE} ===" in captured


class TestDeployRemoteModeWithoutComposeYml:
    """Registry/tarball modes only need Dockerfile, not docker-compose.yml."""

    def test_registry_mode_succeeds_without_docker_compose_yml(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Only Dockerfile exists, no docker-compose.yml
        (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
        _stub_subprocess(monkeypatch)
        _stub_no_trivy(monkeypatch)

        config = _make_config(
            caddy_config=CaddyConfig(domain="blog.example.com", email=None),
            host_bind_ip=LOCALHOST_BIND_IP,
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:1.0",
        )

        result = deploy(config=config, project_dir=tmp_path)

        assert result.bundle_path == tmp_path / DEFAULT_BUNDLE_DIR

    def test_tarball_mode_succeeds_without_docker_compose_yml(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
        _stub_subprocess(monkeypatch)
        _stub_no_trivy(monkeypatch)

        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="agblogger:portable",
        )

        result = deploy(config=config, project_dir=tmp_path)

        assert result.bundle_path == tmp_path / DEFAULT_BUNDLE_DIR

    def test_local_mode_still_requires_docker_compose_yml(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
        monkeypatch.setattr("cli.deploy_production.shutil.which", lambda _name: "/usr/bin/docker")

        with pytest.raises(DeployError, match=r"docker compose file"):
            check_prerequisites(tmp_path, DEPLOY_MODE_LOCAL)


class TestHealthPollProgress:
    """Health poll should print intermediate status updates."""

    def test_prints_elapsed_time_during_poll(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from cli.deploy_production import _wait_for_healthy

        call_count = 0
        timestamps = [0.0, 5.0, 10.0, 200.0]  # last one triggers timeout

        def fake_monotonic() -> float:
            nonlocal call_count
            idx = min(call_count, len(timestamps) - 1)
            call_count += 1
            return timestamps[idx]

        def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(
                returncode=0,
                stdout="agblogger: Up 5 seconds\n",
            )

        monkeypatch.setattr("cli.deploy_production.subprocess.run", fake_run)
        monkeypatch.setattr("cli.deploy_production.time.sleep", lambda _s: None)
        monkeypatch.setattr("cli.deploy_production.time.monotonic", fake_monotonic)

        config = _make_config()
        with pytest.raises(DeployError, match="timed out"):
            _wait_for_healthy(config, tmp_path, timeout=60, interval=5)

        captured = capsys.readouterr()
        # Should show elapsed time in intermediate output
        assert "5s" in captured.out or "10s" in captured.out


class TestIpv4DetectionSharedHelper:
    """IPv4 detection should use a single shared helper."""

    def test_is_ipv4_like_detects_ipv4(self) -> None:
        from cli.deploy_production import _is_ipv4_like

        assert _is_ipv4_like("127.0.0.1")
        assert _is_ipv4_like("93.184.216.34")

    def test_is_ipv4_like_rejects_non_ipv4(self) -> None:
        from cli.deploy_production import _is_ipv4_like

        assert not _is_ipv4_like("blog.example.com")
        assert not _is_ipv4_like("single")
        assert not _is_ipv4_like("")


class TestReadVersion:
    """--version flag reads from VERSION file."""

    def test_reads_version_from_file(self) -> None:
        version = _read_version()
        assert version != ""
        assert version != "unknown"


# ── Issue #3: Remove duplicate prerequisite checks from deploy() ─────


class TestDeployDoesNotDuplicatePrerequisiteChecks:
    """deploy() should not re-check file existence since check_prerequisites() handles it."""

    def test_deploy_does_not_check_compose_file_when_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """deploy() should trust that check_prerequisites() was called before it."""
        _stub_subprocess(monkeypatch)
        _stub_no_trivy(monkeypatch)

        config = _make_config()
        # No docker-compose.yml present — deploy() should not raise on its own
        # because the caller (main) calls check_prerequisites() first.
        # Instead, docker compose will fail naturally when invoked.
        deploy(config=config, project_dir=tmp_path)

    def test_deploy_does_not_check_dockerfile_when_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _stub_subprocess(monkeypatch)
        _stub_no_trivy(monkeypatch)

        config = _make_config(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:1.0",
        )
        # No Dockerfile present — deploy() should not raise on its own
        deploy(config=config, project_dir=tmp_path)


# ── Issue #4: _wait_for_healthy handles docker compose ps failures ───


class TestWaitForHealthyHandlesSubprocessErrors:
    """_wait_for_healthy should handle docker compose ps returning non-zero."""

    def test_prints_error_status_on_compose_ps_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from cli.deploy_production import _wait_for_healthy

        call_counter = 0
        # First two calls within timeout, third exceeds it to break the loop
        timestamps = [0.0, 1.0, 2.0, 200.0]

        def fake_monotonic() -> float:
            nonlocal call_counter
            idx = min(call_counter, len(timestamps) - 1)
            call_counter += 1
            return timestamps[idx]

        def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(returncode=1, stdout="", stderr="daemon error")

        monkeypatch.setattr("cli.deploy_production.subprocess.run", fake_run)
        monkeypatch.setattr("cli.deploy_production.time.sleep", lambda _s: None)
        monkeypatch.setattr("cli.deploy_production.time.monotonic", fake_monotonic)

        config = _make_config()
        with pytest.raises(DeployError, match="timed out"):
            _wait_for_healthy(config, tmp_path, timeout=60, interval=1)

        captured = capsys.readouterr()
        # Should indicate the status query failed rather than silently showing "no services found"
        assert "failed to query" in captured.out.lower()


# ── Issue #10: validate image ref format ─────────────────────────────


class TestValidateImageRef:
    """Image references should be validated beyond whitespace checks."""

    def test_rejects_empty_tag_after_colon(self) -> None:
        from cli.deploy_production import _validate_config

        config = _make_config(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:",
        )
        with pytest.raises(DeployError, match="IMAGE_REF"):
            _validate_config(config)

    def test_rejects_bare_colon(self) -> None:
        from cli.deploy_production import _validate_config

        config = _make_config(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref=":",
        )
        with pytest.raises(DeployError, match="IMAGE_REF"):
            _validate_config(config)

    def test_rejects_empty_image_ref(self) -> None:
        from cli.deploy_production import _validate_config

        config = _make_config(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="",
        )
        with pytest.raises(DeployError):
            _validate_config(config)

    def test_accepts_valid_registry_image_ref(self) -> None:
        from cli.deploy_production import _validate_config

        config = _make_config(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:v1.0.0",
        )
        _validate_config(config)

    def test_accepts_valid_local_image_ref(self) -> None:
        from cli.deploy_production import _validate_config

        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="agblogger:latest",
        )
        _validate_config(config)


# ── Issue #7: Trusted hosts prompt mentions auto-append ──────────────


class TestTrustedHostsPromptMentionsCaddyDomain:
    """Interactive prompt should inform users that the Caddy domain is auto-included."""

    def test_prompt_mentions_auto_include(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cli.deploy_production import _prompt_trusted_hosts

        inputs = iter(["api.example.com"])
        monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

        result = _prompt_trusted_hosts("blog.example.com")
        assert "blog.example.com" in result
        assert "api.example.com" in result


# ── Issue #14: Firewall guidance for public deployments ──────────────


class TestRemoteReadmeFirewallGuidance:
    """Remote deployment readme should include firewall guidance for public Caddy."""

    def test_public_caddy_readme_includes_firewall_note(self) -> None:
        config = _make_config(
            caddy_config=CaddyConfig(domain="blog.example.com", email=None),
            caddy_public=True,
            host_bind_ip=LOCALHOST_BIND_IP,
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:v1",
        )
        commands = build_lifecycle_commands(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            use_caddy=True,
            caddy_public=True,
        )
        content = _build_remote_readme_content(config, commands)
        assert "firewall" in content.lower()

    def test_non_public_caddy_readme_omits_firewall_note(self) -> None:
        config = _make_config(
            caddy_config=CaddyConfig(domain="blog.example.com", email=None),
            caddy_public=False,
            host_bind_ip=LOCALHOST_BIND_IP,
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:v1",
        )
        commands = build_lifecycle_commands(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            use_caddy=True,
            caddy_public=False,
        )
        content = _build_remote_readme_content(config, commands)
        assert "firewall" not in content.lower()


# ── Issue #16: Upgrade guidance in remote readme ─────────────────────


class TestRemoteReadmeUpgradeGuidance:
    """Remote deployment readme should include upgrade instructions."""

    def test_registry_readme_includes_upgrade_section(self) -> None:
        config = _make_config(
            caddy_config=CaddyConfig(domain="blog.example.com", email=None),
            host_bind_ip=LOCALHOST_BIND_IP,
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:v1",
        )
        commands = build_lifecycle_commands(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            use_caddy=True,
            caddy_public=False,
        )
        content = _build_remote_readme_content(config, commands)
        assert "## Upgrading" in content or "## Upgrade" in content
        assert "pull" in content.lower()

    def test_tarball_readme_includes_upgrade_section(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="agblogger:v1",
        )
        commands = build_lifecycle_commands(
            deployment_mode=DEPLOY_MODE_TARBALL,
            use_caddy=False,
            caddy_public=False,
        )
        content = _build_remote_readme_content(config, commands)
        assert "## Upgrading" in content or "## Upgrade" in content
        assert "load" in content.lower()


# ── parse_existing_env / _unquote_env_value ──────────────────────────


class TestUnquoteEnvValue:
    """Reverse of _quote_env_value for parsing existing .env files."""

    def test_unquotes_simple_json_string(self) -> None:
        assert _unquote_env_value('"hello"') == "hello"

    def test_unquotes_escaped_backslash(self) -> None:
        assert _unquote_env_value('"pass\\\\word"') == "pass\\word"

    def test_unquotes_escaped_dollar_sign(self) -> None:
        assert _unquote_env_value('"my\\$ecret"') == "my$ecret"

    def test_returns_unquoted_value_as_is(self) -> None:
        assert _unquote_env_value("8000") == "8000"

    def test_strips_inline_comments_from_unquoted_values(self) -> None:
        assert _unquote_env_value("8000  # Only used in no-Caddy mode") == "8000"


class TestParseExistingEnv:
    """Parse key-value pairs from a generated .env.production file."""

    def test_parses_generated_env_file(self, tmp_path: Path) -> None:
        config = _make_config()
        env_content = build_env_content(config)
        env_path = tmp_path / DEFAULT_ENV_FILE
        env_path.write_text(env_content, encoding="utf-8")

        parsed = parse_existing_env(env_path)

        assert parsed["SECRET_KEY"] == config.secret_key
        assert parsed["ADMIN_USERNAME"] == config.admin_username
        assert parsed["ADMIN_PASSWORD"] == config.admin_password
        assert parsed["DEBUG"] == "false"

    def test_roundtrips_special_characters(self, tmp_path: Path) -> None:
        config = DeployConfig(
            secret_key='key$with"special\\chars',
            admin_username="admin",
            admin_password="pass$word",
            trusted_hosts=["example.com"],
            trusted_proxy_ips=[],
            host_port=8000,
            host_bind_ip=PUBLIC_BIND_IP,
            caddy_config=None,
            caddy_public=False,
            expose_docs=False,
        )
        env_content = build_env_content(config)
        env_path = tmp_path / DEFAULT_ENV_FILE
        env_path.write_text(env_content, encoding="utf-8")

        parsed = parse_existing_env(env_path)

        assert parsed["SECRET_KEY"] == 'key$with"special\\chars'
        assert parsed["ADMIN_PASSWORD"] == "pass$word"

    def test_returns_empty_dict_for_missing_file(self, tmp_path: Path) -> None:
        assert parse_existing_env(tmp_path / "nonexistent") == {}

    def test_skips_comments_and_blank_lines(self, tmp_path: Path) -> None:
        env_path = tmp_path / ".env"
        env_path.write_text("# comment\n\nKEY=value\n", encoding="utf-8")

        parsed = parse_existing_env(env_path)

        assert parsed == {"KEY": "value"}


# ── Upgrade lifecycle command ────────────────────────────────────────


class TestUpgradeLifecycleCommand:
    """build_lifecycle_commands should include an upgrade command."""

    def test_local_mode_upgrade_uses_build_flag(self) -> None:
        commands = build_lifecycle_commands(
            deployment_mode=DEPLOY_MODE_LOCAL,
            use_caddy=True,
            caddy_public=False,
        )
        assert "upgrade" in commands
        assert "--build" in commands["upgrade"]

    def test_registry_mode_upgrade_pulls_then_starts(self) -> None:
        commands = build_lifecycle_commands(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            use_caddy=True,
            caddy_public=False,
        )
        assert "upgrade" in commands
        assert "pull" in commands["upgrade"]
        assert "up -d" in commands["upgrade"]

    def test_tarball_mode_upgrade_loads_then_starts(self) -> None:
        commands = build_lifecycle_commands(
            deployment_mode=DEPLOY_MODE_TARBALL,
            use_caddy=False,
            caddy_public=False,
        )
        assert "upgrade" in commands
        assert "load" in commands["upgrade"]
        assert "up -d" in commands["upgrade"]


# ── DEPLOY-REMOTE.md improvements ────────────────────────────────────


class TestRemoteReadmePrerequisites:
    """Remote readme should list Docker prerequisites."""

    def test_includes_docker_prerequisite(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:v1",
        )
        commands = build_lifecycle_commands(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            use_caddy=False,
            caddy_public=False,
        )
        content = _build_remote_readme_content(config, commands)
        assert "## Prerequisites" in content
        assert "Docker" in content
        assert "Docker Compose" in content


class TestRemoteReadmeDataPreservation:
    """Remote readme should accurately describe data preservation requirements."""

    def test_does_not_say_database_is_only_a_cache(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:v1",
        )
        commands = build_lifecycle_commands(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            use_caddy=False,
            caddy_public=False,
        )
        content = _build_remote_readme_content(config, commands)
        # The old misleading phrase said the database was *only* a regenerable cache
        assert "the database is a regenerable cache" not in content.lower()
        assert "only `./content/` needs to be preserved" not in content.lower()

    def test_mentions_database_volume_preservation(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:v1",
        )
        commands = build_lifecycle_commands(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            use_caddy=False,
            caddy_public=False,
        )
        content = _build_remote_readme_content(config, commands)
        assert "agblogger-db" in content
        assert "user accounts" in content.lower()

    def test_tarball_mode_mentions_image_tag_update(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="agblogger:v1",
        )
        commands = build_lifecycle_commands(
            deployment_mode=DEPLOY_MODE_TARBALL,
            use_caddy=False,
            caddy_public=False,
        )
        content = _build_remote_readme_content(config, commands)
        assert "AGBLOGGER_IMAGE" in content


class TestRemoteReadmeRollback:
    """Remote readme should include rollback guidance."""

    def test_includes_rollback_section(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:v1",
        )
        commands = build_lifecycle_commands(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            use_caddy=False,
            caddy_public=False,
        )
        content = _build_remote_readme_content(config, commands)
        assert "## Rollback" in content
        assert ".bak" in content


# ── Trusted hosts prompt simplification ──────────────────────────────


class TestTrustedHostsPromptWithCaddy:
    """Trusted hosts prompt should be simpler when Caddy domain is set."""

    def test_caddy_domain_only_when_input_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cli.deploy_production import _prompt_trusted_hosts

        monkeypatch.setattr("builtins.input", lambda _prompt: "")
        result = _prompt_trusted_hosts("blog.example.com")
        assert result == ["blog.example.com"]

    def test_caddy_domain_plus_extras(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cli.deploy_production import _prompt_trusted_hosts

        monkeypatch.setattr("builtins.input", lambda _prompt: "api.example.com")
        result = _prompt_trusted_hosts("blog.example.com")
        assert "blog.example.com" in result
        assert "api.example.com" in result


# ── Collect config with existing env ─────────────────────────────────


class TestCollectConfigReusesExistingSecrets:
    """collect_config should detect and offer to reuse existing .env.production secrets."""

    def test_reuses_secrets_when_user_accepts(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.deploy_production import collect_config

        # Write an existing .env.production
        existing_config = _make_config()
        env_content = build_env_content(existing_config)
        (tmp_path / DEFAULT_ENV_FILE).write_text(env_content, encoding="utf-8")

        # Simulate interactive answers: reuse=yes, mode=local, caddy=no, public=no,
        # port=8000, trusted hosts=example.com, proxy ips=(none), expose docs=no
        inputs = iter(["y", "", "n", "n", "", "example.com", "", "n"])
        monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))
        monkeypatch.setattr("cli.deploy_production.getpass.getpass", lambda _prompt: "")

        config = collect_config(tmp_path)

        assert config.secret_key == existing_config.secret_key
        assert config.admin_username == existing_config.admin_username
        assert config.admin_password == existing_config.admin_password

    def test_prompts_new_secrets_when_no_existing_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.deploy_production import collect_config

        # Simulate: secret_key=auto, username=admin, display_name=admin,
        # password+confirm, mode=local,
        # caddy=no, public=no, port=8000, trusted hosts=example.com, proxy ips, docs=no
        inputs = iter(["admin", "", "", "n", "n", "", "example.com", "", "n"])
        passwords = iter(["", "strongpass123", "strongpass123"])
        monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))
        monkeypatch.setattr(
            "cli.deploy_production.getpass.getpass", lambda _prompt: next(passwords)
        )

        config = collect_config(tmp_path)

        # Should have generated a new secret key
        assert len(config.secret_key) >= 32
        assert config.admin_username == "admin"

    def test_dry_run_shows_upgrade_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = _make_config()
        dry_run(config)
        captured = capsys.readouterr().out
        assert "Upgrade:" in captured


# ── BLUESKY_CLIENT_URL forwarding to container ───────────────────────


class TestBlueskyClientUrlForwarding:
    """BLUESKY_CLIENT_URL must be in compose environment so the container receives it."""

    def test_compose_env_section_includes_bluesky_client_url(self) -> None:
        from cli.deploy_production import _agblogger_env_section

        section = _agblogger_env_section()
        assert "BLUESKY_CLIENT_URL=${BLUESKY_CLIENT_URL:-}" in section

    def test_direct_compose_includes_bluesky_client_url(self) -> None:
        content = build_direct_compose_content()
        assert "BLUESKY_CLIENT_URL=${BLUESKY_CLIENT_URL:-}" in content

    def test_image_compose_includes_bluesky_client_url(self) -> None:
        content = build_image_compose_content()
        assert "BLUESKY_CLIENT_URL=${BLUESKY_CLIENT_URL:-}" in content


# ── BLUESKY_CLIENT_URL uses actual Caddy domain ──────────────────────


class TestBlueskyPlaceholderDomain:
    """The commented BLUESKY_CLIENT_URL should use the actual Caddy domain when available."""

    def test_uses_caddy_domain_when_configured(self) -> None:
        config = _make_config(
            caddy_config=CaddyConfig(domain="myblog.example.com", email=None),
            host_bind_ip=LOCALHOST_BIND_IP,
        )
        content = build_env_content(config)
        assert "# BLUESKY_CLIENT_URL=https://myblog.example.com" in content

    def test_uses_generic_domain_without_caddy(self) -> None:
        config = _make_config()
        content = build_env_content(config)
        assert "# BLUESKY_CLIENT_URL=https://blog.example.com" in content


# ── Cross-architecture Docker build for remote deployments ───────────


class TestCrossArchitectureBuild:
    """Remote deployments should support cross-architecture Docker builds."""

    def test_build_image_passes_platform_flag(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        commands = _stub_subprocess(monkeypatch)
        build_image(tmp_path, "test:latest", platform="linux/amd64")
        assert commands[0][0] == [
            "docker",
            "build",
            "--platform",
            "linux/amd64",
            "--tag",
            "test:latest",
            ".",
        ]

    def test_build_image_omits_platform_when_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        commands = _stub_subprocess(monkeypatch)
        build_image(tmp_path, "test:latest")
        assert "--platform" not in commands[0][0]

    def test_config_from_args_defaults_platform_for_registry(self) -> None:
        args = argparse.Namespace(
            secret_key="s" * 64,
            admin_username="admin",
            admin_password="strong-password!",
            admin_display_name=None,
            caddy_domain=None,
            caddy_email=None,
            caddy_public=False,
            trusted_hosts="example.com",
            trusted_proxy_ips=None,
            host_port=8000,
            bind_public=False,
            expose_docs=False,
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:v1",
            bundle_dir=DEFAULT_BUNDLE_DIR,
            tarball_filename=DEFAULT_IMAGE_TARBALL,
            platform=None,
        )
        config = config_from_args(args)
        assert config.platform == DEFAULT_REMOTE_PLATFORM

    def test_config_from_args_defaults_platform_for_tarball(self) -> None:
        args = argparse.Namespace(
            secret_key="s" * 64,
            admin_username="admin",
            admin_password="strong-password!",
            admin_display_name=None,
            caddy_domain=None,
            caddy_email=None,
            caddy_public=False,
            trusted_hosts="example.com",
            trusted_proxy_ips=None,
            host_port=8000,
            bind_public=False,
            expose_docs=False,
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="agblogger:v1",
            bundle_dir=DEFAULT_BUNDLE_DIR,
            tarball_filename=DEFAULT_IMAGE_TARBALL,
            platform=None,
        )
        config = config_from_args(args)
        assert config.platform == DEFAULT_REMOTE_PLATFORM

    def test_config_from_args_no_platform_for_local(self) -> None:
        args = argparse.Namespace(
            secret_key="s" * 64,
            admin_username="admin",
            admin_password="strong-password!",
            admin_display_name=None,
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
            platform=None,
        )
        config = config_from_args(args)
        assert config.platform is None

    def test_config_from_args_respects_explicit_platform(self) -> None:
        args = argparse.Namespace(
            secret_key="s" * 64,
            admin_username="admin",
            admin_password="strong-password!",
            admin_display_name=None,
            caddy_domain=None,
            caddy_email=None,
            caddy_public=False,
            trusted_hosts="example.com",
            trusted_proxy_ips=None,
            host_port=8000,
            bind_public=False,
            expose_docs=False,
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:v1",
            bundle_dir=DEFAULT_BUNDLE_DIR,
            tarball_filename=DEFAULT_IMAGE_TARBALL,
            platform="linux/arm64",
        )
        config = config_from_args(args)
        assert config.platform == "linux/arm64"

    def test_deploy_registry_passes_platform_to_build(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
        commands = _stub_subprocess(monkeypatch)
        _stub_no_trivy(monkeypatch)

        config = _make_config(
            caddy_config=CaddyConfig(domain="blog.example.com", email=None),
            host_bind_ip=LOCALHOST_BIND_IP,
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:v1",
            platform="linux/amd64",
        )

        deploy(config=config, project_dir=tmp_path)

        build_cmd = commands[0][0]
        assert build_cmd == [
            "docker",
            "build",
            "--platform",
            "linux/amd64",
            "--tag",
            "ghcr.io/example/agblogger:v1",
            ".",
        ]

    def test_deploy_tarball_passes_platform_to_build(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
        commands = _stub_subprocess(monkeypatch)
        _stub_no_trivy(monkeypatch)

        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="agblogger:v1",
            platform="linux/arm64",
        )

        deploy(config=config, project_dir=tmp_path)

        build_cmd = commands[0][0]
        assert build_cmd == [
            "docker",
            "build",
            "--platform",
            "linux/arm64",
            "--tag",
            "agblogger:v1",
            ".",
        ]

    def test_print_config_summary_shows_platform(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:v1",
            platform="linux/amd64",
        )
        print_config_summary(config)
        captured = capsys.readouterr().out
        assert "linux/amd64" in captured


# ── Issue #1: Content directory seeding in bundle ─────────────────────


class TestBundleContentDirectory:
    """Remote bundle should include an empty content/ directory."""

    def test_write_bundle_files_creates_content_directory(self, tmp_path: Path) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:v1",
        )
        bundle_dir = tmp_path / "bundle"
        write_bundle_files(config, bundle_dir)
        assert (bundle_dir / "content").is_dir()

    def test_write_bundle_files_preserves_existing_content(self, tmp_path: Path) -> None:
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir(parents=True)
        content_dir = bundle_dir / "content"
        content_dir.mkdir()
        (content_dir / "existing-post.md").write_text("# Hello", encoding="utf-8")

        config = _make_config(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:v1",
        )
        write_bundle_files(config, bundle_dir)
        assert (content_dir / "existing-post.md").exists()


# ── Issue #2: Version marker in bundle ────────────────────────────────


class TestBundleVersionMarker:
    """Remote bundle should contain a version file for upgrade tracking."""

    def test_write_bundle_files_writes_version_file(self, tmp_path: Path) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:v1",
        )
        bundle_dir = tmp_path / "bundle"
        write_bundle_files(config, bundle_dir)
        version_file = bundle_dir / "VERSION"
        assert version_file.exists()
        version = version_file.read_text(encoding="utf-8").strip()
        assert version != ""
        assert version != "unknown"

    def test_remote_readme_mentions_version(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:v1",
        )
        commands = build_lifecycle_commands(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            use_caddy=False,
            caddy_public=False,
        )
        content = _build_remote_readme_content(config, commands)
        assert "VERSION" in content


# ── Issue #3: Tarball upgrade instructions ────────────────────────────


class TestTarballUpgradeInstructions:
    """Tarball upgrade numbered steps should include replacing bundle files."""

    def test_tarball_upgrade_has_replace_as_numbered_step(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="agblogger:v1",
        )
        commands = build_lifecycle_commands(
            deployment_mode=DEPLOY_MODE_TARBALL,
            use_caddy=False,
            caddy_public=False,
        )
        content = _build_remote_readme_content(config, commands)
        upgrade_section = content[content.index("## Upgrading") :]
        # "Replace" or "replace" should appear in a numbered step, not just prose
        import re

        numbered_steps = re.findall(r"^\d+\..+", upgrade_section, re.MULTILINE)
        assert any("replace" in step.lower() or "Replace" in step for step in numbered_steps)

    def test_registry_upgrade_has_replace_as_numbered_step(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:v1",
        )
        commands = build_lifecycle_commands(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            use_caddy=False,
            caddy_public=False,
        )
        content = _build_remote_readme_content(config, commands)
        upgrade_section = content[content.index("## Upgrading") :]
        import re

        numbered_steps = re.findall(r"^\d+\..+", upgrade_section, re.MULTILINE)
        assert any("replace" in step.lower() or "Replace" in step for step in numbered_steps)


# ── Issue #4: Health timeout includes logs command ────────────────────


class TestHealthTimeoutLogsCommand:
    """Health timeout error should include the actual logs command."""

    def test_health_timeout_error_includes_logs_command(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.deploy_production import _wait_for_healthy

        call_counter = 0

        def fake_monotonic() -> float:
            nonlocal call_counter
            call_counter += 1
            return float(call_counter * 100)

        def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(returncode=0, stdout="agblogger: Up 3 seconds (starting)\n")

        monkeypatch.setattr("cli.deploy_production.subprocess.run", fake_run)
        monkeypatch.setattr("cli.deploy_production.time.sleep", lambda _s: None)
        monkeypatch.setattr("cli.deploy_production.time.monotonic", fake_monotonic)

        config = _make_config()
        with pytest.raises(DeployError, match=r"docker compose.*logs"):
            _wait_for_healthy(config, tmp_path, timeout=10, interval=1)


# ── Issue #6: check_prerequisites validates Dockerfile for local mode ─


class TestCheckPrerequisitesDockerfile:
    """Local mode should verify Dockerfile exists alongside docker-compose.yml."""

    def test_local_mode_requires_dockerfile(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
        # No Dockerfile present
        monkeypatch.setattr("cli.deploy_production.shutil.which", lambda _name: "/usr/bin/docker")
        _stub_subprocess(monkeypatch)

        with pytest.raises(DeployError, match="Dockerfile"):
            check_prerequisites(tmp_path, DEPLOY_MODE_LOCAL)

    def test_local_mode_passes_when_both_exist(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
        (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
        monkeypatch.setattr("cli.deploy_production.shutil.which", lambda _name: "/usr/bin/docker")
        commands = _stub_subprocess(monkeypatch)

        check_prerequisites(tmp_path, DEPLOY_MODE_LOCAL)

        assert commands == [
            (["docker", "--version"], tmp_path, True),
            (["docker", "compose", "version"], tmp_path, True),
        ]


# ── Issue #7: DNS confirmation prompt ─────────────────────────────────


class TestDnsConfirmationPrompt:
    """Interactive Caddy setup should confirm DNS is configured."""

    def test_caddy_setup_asks_dns_confirmation(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.deploy_production import collect_config

        # Track all prompts shown to the user to verify DNS prompt presence
        prompts_shown: list[str] = []
        # Simulate: no existing env, secret_key=auto, username=admin,
        # display_name=admin, password+confirm,
        # mode=local, caddy=yes, domain, email, caddy_public=yes,
        # dns_confirmed=yes, trusted hosts, proxy ips, expose docs=no
        inputs = iter(
            [
                "admin",  # admin username
                "",  # admin display name (default=admin)
                "",  # deployment mode (local)
                "y",  # use caddy
                "blog.example.com",  # caddy domain
                "",  # caddy email
                "y",  # caddy public
                "y",  # DNS confirmed
                "",  # additional trusted hosts
                "",  # additional proxy ips
                "n",  # expose docs
            ]
        )
        passwords = iter(["", "strongpass123", "strongpass123"])

        def tracking_input(prompt: str) -> str:
            prompts_shown.append(prompt)
            return next(inputs)

        monkeypatch.setattr("builtins.input", tracking_input)
        monkeypatch.setattr(
            "cli.deploy_production.getpass.getpass", lambda _prompt: next(passwords)
        )

        config = collect_config(tmp_path)

        assert config.caddy_config is not None
        assert config.caddy_config.domain == "blog.example.com"
        # Verify a DNS confirmation prompt was shown
        dns_prompts = [p for p in prompts_shown if "dns" in p.lower() or "DNS" in p]
        assert dns_prompts, f"No DNS confirmation prompt found. Prompts shown: {prompts_shown}"

    def test_print_config_summary_hides_platform_when_none(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = _make_config()
        print_config_summary(config)
        captured = capsys.readouterr().out
        assert "Platform" not in captured


# ── Docker daemon check before config collection ─────────────────────


class TestDockerDaemonCheck:
    """main() should verify the Docker daemon is running before collecting config."""

    def test_daemon_not_running_fails_before_config_collection(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        import subprocess as sp

        from cli.deploy_production import main

        monkeypatch.setattr(
            "sys.argv",
            [
                "deploy",
                "--non-interactive",
                "--project-dir",
                str(tmp_path),
                "--admin-username",
                "admin",
                "--admin-password",
                "strong-password!",
                "--trusted-hosts",
                "example.com",
            ],
        )
        monkeypatch.setattr("cli.deploy_production.shutil.which", lambda _name: "/usr/bin/docker")

        def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
            if command == ["docker", "info"]:
                raise sp.CalledProcessError(1, command)
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr("cli.deploy_production.subprocess.run", fake_run)

        def _must_not_be_called(_args: object) -> None:
            raise AssertionError("config_from_args should not be called when daemon is down")

        monkeypatch.setattr("cli.deploy_production.config_from_args", _must_not_be_called)

        with pytest.raises(SystemExit, match="1"):
            main()

        captured = capsys.readouterr()
        assert "Docker daemon is not running" in captured.out

    def test_daemon_check_skipped_for_dry_run(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """dry-run should not check Docker daemon since it only prints config."""
        from cli.deploy_production import main

        monkeypatch.setattr(
            "sys.argv",
            [
                "deploy",
                "--dry-run",
                "--non-interactive",
                "--project-dir",
                str(tmp_path),
                "--admin-username",
                "admin",
                "--admin-password",
                "strong-password!",
                "--trusted-hosts",
                "example.com",
            ],
        )
        # Docker binary not even present — should still succeed for dry-run
        monkeypatch.setattr("cli.deploy_production.shutil.which", lambda _name: None)

        # Should not raise
        main()


# ── Bundle dir credential reuse ──────────────────────────────────────


class TestCollectConfigBundleDirReuse:
    """collect_config should fall back to bundle dir when no project-root env exists."""

    def test_reuses_secrets_from_bundle_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.deploy_production import collect_config

        # Write .env.production only in the bundle dir, not project root
        existing_config = _make_config()
        env_content = build_env_content(existing_config)
        bundle_dir = tmp_path / DEFAULT_BUNDLE_DIR
        bundle_dir.mkdir(parents=True)
        (bundle_dir / DEFAULT_ENV_FILE).write_text(env_content, encoding="utf-8")

        # Simulate: reuse=yes, mode=local, caddy=no, public=no,
        # port=8000, trusted hosts, proxy ips, docs=no
        inputs = iter(["y", "", "n", "n", "", "example.com", "", "n"])
        monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))
        monkeypatch.setattr("cli.deploy_production.getpass.getpass", lambda _prompt: "")

        config = collect_config(tmp_path)

        assert config.secret_key == existing_config.secret_key
        assert config.admin_username == existing_config.admin_username
        assert config.admin_password == existing_config.admin_password

    def test_prefers_project_root_over_bundle_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.deploy_production import collect_config

        # Write different configs in both locations
        root_config = _make_config()
        root_content = build_env_content(root_config)
        (tmp_path / DEFAULT_ENV_FILE).write_text(root_content, encoding="utf-8")

        bundle_dir = tmp_path / DEFAULT_BUNDLE_DIR
        bundle_dir.mkdir(parents=True)
        bundle_config = DeployConfig(
            secret_key="bundle_" + "x" * 60,
            admin_username="bundle_admin",
            admin_password="bundle-strong-password",
            trusted_hosts=["example.com"],
            trusted_proxy_ips=[],
            host_port=8000,
            host_bind_ip=PUBLIC_BIND_IP,
            caddy_config=None,
            caddy_public=False,
            expose_docs=False,
        )
        (bundle_dir / DEFAULT_ENV_FILE).write_text(
            build_env_content(bundle_config), encoding="utf-8"
        )

        # Simulate: reuse=yes, mode=local, caddy=no, public=no,
        # port=8000, trusted hosts, proxy ips, docs=no
        inputs = iter(["y", "", "n", "n", "", "example.com", "", "n"])
        monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))
        monkeypatch.setattr("cli.deploy_production.getpass.getpass", lambda _prompt: "")

        config = collect_config(tmp_path)

        # Should use the project-root config, not the bundle one
        assert config.secret_key == root_config.secret_key
        assert config.admin_username == root_config.admin_username


# ── Health timeout message ───────────────────────────────────────────


class TestHealthTimeoutMessage:
    """Health check timeout should suggest checking logs."""

    def test_timeout_message_mentions_logs(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.deploy_production import _wait_for_healthy

        config = _make_config()

        # Stub subprocess.run to always return unhealthy status
        def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(returncode=1, stdout="", stderr="")

        monkeypatch.setattr("cli.deploy_production.subprocess.run", fake_run)
        monkeypatch.setattr("cli.deploy_production.time.sleep", lambda _: None)

        with pytest.raises(DeployError, match=r"docker compose.*logs"):
            _wait_for_healthy(config, tmp_path, timeout=1, interval=0)


# ── Remote README bundle upgrade note ────────────────────────────────


class TestRemoteReadmeBundleUpgradeNote:
    """Remote deployment README should advise replacing the full bundle on upgrade."""

    def test_registry_readme_mentions_full_bundle_replacement(self) -> None:
        config = _make_config(
            caddy_config=CaddyConfig(domain="blog.example.com", email=None),
            host_bind_ip=LOCALHOST_BIND_IP,
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:v1",
        )
        commands = build_lifecycle_commands(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            use_caddy=True,
            caddy_public=False,
        )
        content = _build_remote_readme_content(config, commands)
        assert "Regenerate the bundle locally and replace all files" in content
        assert "compose files and config may change" in content

    def test_tarball_readme_mentions_full_bundle_replacement(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="agblogger:v1",
        )
        commands = build_lifecycle_commands(
            deployment_mode=DEPLOY_MODE_TARBALL,
            use_caddy=False,
            caddy_public=False,
        )
        content = _build_remote_readme_content(config, commands)
        assert "Regenerate the bundle locally and replace all files" in content


# ── Version banner ───────────────────────────────────────────────────


class TestVersionBanner:
    """Interactive mode should show the AgBlogger version at startup."""

    def test_interactive_mode_prints_version(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        from cli.deploy_production import main

        monkeypatch.setattr(
            "sys.argv",
            ["deploy", "--project-dir", str(tmp_path)],
        )
        monkeypatch.setattr("cli.deploy_production.shutil.which", lambda _name: "/usr/bin/docker")

        # Stub docker info to succeed
        def fake_subprocess_run(command: list[str], **kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr("cli.deploy_production.subprocess.run", fake_subprocess_run)

        # Stub collect_config to return a config, then cancel at confirmation
        config = _make_config()
        monkeypatch.setattr("cli.deploy_production.collect_config", lambda _dir: config)
        monkeypatch.setattr("cli.deploy_production._prompt_yes_no", lambda _prompt, default: False)

        main()

        captured = capsys.readouterr().out
        assert "AgBlogger deployment helper v" in captured


# ── CaddyMode constants and SharedCaddyConfig ────────────────────────


def test_shared_caddy_config_has_required_fields() -> None:
    from pathlib import Path

    config = SharedCaddyConfig(
        caddy_dir=Path("/opt/caddy"),
        acme_email="ops@example.com",
    )
    assert config.caddy_dir == Path("/opt/caddy")
    assert config.acme_email == "ops@example.com"


def test_shared_caddy_config_optional_email() -> None:
    from pathlib import Path

    config = SharedCaddyConfig(caddy_dir=Path("/opt/caddy"), acme_email=None)
    assert config.acme_email is None


def test_caddy_mode_constants_are_strings() -> None:
    assert CADDY_MODE_BUNDLED == "bundled"
    assert CADDY_MODE_EXTERNAL == "external"
    assert CADDY_MODE_NONE == "none"


def test_default_shared_caddy_dir_constant() -> None:
    assert DEFAULT_SHARED_CADDY_DIR == "/opt/caddy"


def test_external_caddy_network_name_constant() -> None:
    assert EXTERNAL_CADDY_NETWORK_NAME == "caddy"
