"""Tests for production deployment CLI workflow."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

if TYPE_CHECKING:
    from collections.abc import Callable

from cli.deploy_production import (
    AGBLOGGER_STATIC_IP,
    CADDY_MODE_BUNDLED,
    CADDY_MODE_EXTERNAL,
    CADDY_MODE_NONE,
    CADDY_MODES,
    CADDY_NETWORK_SUBNET_PLACEHOLDER,
    CADDY_STATIC_IP,
    COMPOSE_SUBNET,
    DEFAULT_BUNDLE_DIR,
    DEFAULT_BUNDLED_CADDY_COMPOSE_FILE,
    DEFAULT_CADDY_PUBLIC_COMPOSE_FILE,
    DEFAULT_CADDYFILE,
    DEFAULT_ENV_FILE,
    DEFAULT_ENV_GENERATED_FILE,
    DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE,
    DEFAULT_IMAGE_COMPOSE_FILE,
    DEFAULT_IMAGE_EXTERNAL_CADDY_COMPOSE_FILE,
    DEFAULT_IMAGE_NO_CADDY_COMPOSE_FILE,
    DEFAULT_IMAGE_REF,
    DEFAULT_IMAGE_TARBALL,
    DEFAULT_NO_CADDY_COMPOSE_FILE,
    DEFAULT_REMOTE_PLATFORM,
    DEFAULT_REMOTE_README,
    DEFAULT_SETUP_SCRIPT,
    DEFAULT_SHARED_CADDY_DIR,
    DEPLOY_MODE_LOCAL,
    DEPLOY_MODE_REGISTRY,
    DEPLOY_MODE_TARBALL,
    EXTERNAL_CADDY_NETWORK_NAME,
    GOATCOUNTER_STATIC_IP,
    LOCAL_IMAGE_TAG,
    LOCALHOST_BIND_IP,
    MIN_SECRET_KEY_LENGTH,
    PUBLIC_BIND_IP,
    SHARED_CADDY_CONTAINER_NAME,
    CaddyConfig,
    CaddyMode,
    DeployConfig,
    DeployError,
    SharedCaddyConfig,
    _bash_quote,
    _build_remote_readme_content,
    _goatcounter_site_host,
    _is_valid_caddy_domain,
    _read_version,
    _shared_caddy_runtime_dir,
    _unquote_env_value,
    _validate_config,
    backup_existing_configs,
    backup_file,
    build_caddy_public_compose_override_content,
    build_caddy_site_snippet,
    build_caddyfile_content,
    build_direct_compose_content,
    build_env_content,
    build_external_caddy_compose_content,
    build_image,
    build_image_compose_content,
    build_image_direct_compose_content,
    build_image_external_caddy_compose_content,
    build_lifecycle_commands,
    build_setup_script_content,
    build_shared_caddy_compose_content,
    build_shared_caddyfile_content,
    check_prerequisites,
    config_from_args,
    deploy,
    dry_run,
    ensure_shared_caddy,
    parse_csv_list,
    parse_existing_env,
    print_config_summary,
    reload_shared_caddy,
    scan_image,
    write_bundle_files,
    write_caddy_site_snippet,
    write_config_files,
)


def _make_config(
    *,
    caddy_config: CaddyConfig | None = None,
    caddy_public: bool = False,
    host_bind_ip: str = PUBLIC_BIND_IP,
    trusted_hosts: list[str] | None = None,
    expose_docs: bool = False,
    deployment_mode: str = DEPLOY_MODE_LOCAL,
    image_ref: str | None = None,
    platform: str | None = None,
    caddy_mode: CaddyMode = CADDY_MODE_NONE,
    shared_caddy_config: SharedCaddyConfig | None = None,
    trusted_proxy_ips: list[str] | None = None,
    scan_image: bool = True,
    max_content_size: str | None = None,
    disable_password_change: bool = False,
    deploy_goatcounter: bool = True,
) -> DeployConfig:
    """Build a valid DeployConfig with sensible defaults for tests."""
    return DeployConfig(
        secret_key="x" * 64,
        admin_username="admin",
        admin_password="very-strong-password",
        trusted_hosts=trusted_hosts or ["example.com"],
        trusted_proxy_ips=trusted_proxy_ips or [],
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
        caddy_mode=caddy_mode,
        shared_caddy_config=shared_caddy_config,
        scan_image=scan_image,
        max_content_size=max_content_size,
        disable_password_change=disable_password_change,
        deploy_goatcounter=deploy_goatcounter,
    )


def _stub_subprocess(monkeypatch: pytest.MonkeyPatch) -> list[tuple[list[str], Path, bool]]:
    """Stub subprocess.run and return a list that captures all calls.

    Also stubs ``_wait_for_healthy`` to a no-op so deploy tests do not
    need to account for health-poll subprocess calls.
    """
    commands: list[tuple[list[str], Path, bool]] = []

    def fake_run(
        command: list[str], *, cwd: Path, check: bool = False, **kwargs: object
    ) -> SimpleNamespace:
        commands.append((command, cwd, check))
        ns = SimpleNamespace(returncode=0)
        if kwargs.get("capture_output"):
            ns.stdout = b'{"Results":[]}'
            ns.stderr = b""
        # Create a dummy file for docker save so the gzip step has something to read
        if len(command) >= 4 and command[1] == "save" and command[2] == "--output":
            output_path = Path(command[3])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"fake-image-data")
        return ns

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


def _stub_docker_inspect_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub _is_container_running to return False."""
    monkeypatch.setattr("cli.deploy_production._is_container_running", lambda _name: False)
    monkeypatch.setattr("cli.deploy_production._container_exists", lambda _name: False)


def _stub_docker_inspect_running(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub _is_container_running to return True."""
    monkeypatch.setattr("cli.deploy_production._is_container_running", lambda _name: True)
    monkeypatch.setattr("cli.deploy_production._container_exists", lambda _name: True)


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
    assert 'GOATCOUNTER_SITE_HOST="example.com"' in content
    assert "ANALYTICS_ENABLED_DEFAULT=true" in content


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
    assert "AUTH_LOGIN_MAX_FAILURES=5" in content
    assert "AUTH_RATE_LIMIT_WINDOW_SECONDS=300" in content


def test_build_env_content_disables_analytics_default_when_goatcounter_disabled() -> None:
    config = _make_config(deploy_goatcounter=False)

    content = build_env_content(config)

    assert "ANALYTICS_ENABLED_DEFAULT=false" in content


def test_goatcounter_site_host_prefers_caddy_domain() -> None:
    config = _make_config(
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        trusted_hosts=["example.com:8443"],
    )

    assert _goatcounter_site_host(config) == "blog.example.com"


def test_goatcounter_site_host_sanitizes_trusted_host_port() -> None:
    config = _make_config(trusted_hosts=["example.com:8443"])

    assert _goatcounter_site_host(config) == "example.com"


def test_goatcounter_site_host_falls_back_for_non_domain_trusted_hosts() -> None:
    config = _make_config(trusted_hosts=["127.0.0.1:8000", "*.example.com"])

    assert _goatcounter_site_host(config) == "stats.internal"


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
    assert "protocols h1 h2 h3" in content
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
    assert "AUTH_LOGIN_MAX_FAILURES=${AUTH_LOGIN_MAX_FAILURES:-5}" in content


def test_build_direct_compose_content_includes_tz_utc() -> None:
    """TZ=UTC must be present in agblogger environment to ensure consistent timestamps."""
    content = build_direct_compose_content()
    assert "TZ=UTC" in content


def test_build_image_compose_content_includes_tz_utc() -> None:
    """TZ=UTC must be present in image-based compose to ensure consistent timestamps."""
    content = build_image_compose_content()
    assert "TZ=UTC" in content


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


def test_build_image_compose_content_localhost_ports_by_default() -> None:
    content = build_image_compose_content()
    assert '"127.0.0.1:80:80"' in content
    assert '"127.0.0.1:443:443"' in content


def test_build_image_compose_content_public_ports_when_caddy_public() -> None:
    content = build_image_compose_content(caddy_public=True)
    assert '"80:80"' in content
    assert '"443:443"' in content
    # Must NOT have duplicate localhost ports — Docker Compose merges additively.
    assert '"127.0.0.1:80:80"' not in content
    assert '"127.0.0.1:443:443"' not in content


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
    assert '"443:443/udp"' in content


# ── build_lifecycle_commands ─────────────────────────────────────────


def test_build_lifecycle_commands_for_default_caddy() -> None:
    commands = build_lifecycle_commands(
        deployment_mode=DEPLOY_MODE_LOCAL,
        use_caddy=True,
        caddy_public=False,
    )
    assert (
        commands["start"]
        == "docker compose --env-file .env.production -f docker-compose.yml up -d --remove-orphans"
    )
    assert (
        commands["stop"] == "docker compose --env-file .env.production -f docker-compose.yml down"
    )
    assert (
        commands["status"] == "docker compose --env-file .env.production -f docker-compose.yml ps"
    )


def test_build_lifecycle_commands_for_default_caddy_without_goatcounter() -> None:
    commands = build_lifecycle_commands(
        deployment_mode=DEPLOY_MODE_LOCAL,
        use_caddy=True,
        caddy_public=False,
        deploy_goatcounter=False,
    )
    assert (
        commands["start"] == "docker compose --env-file .env.production "
        f"-f {DEFAULT_BUNDLED_CADDY_COMPOSE_FILE} up -d --remove-orphans"
    )


def test_build_lifecycle_commands_for_public_caddy_override() -> None:
    commands = build_lifecycle_commands(
        deployment_mode=DEPLOY_MODE_LOCAL,
        use_caddy=True,
        caddy_public=True,
    )
    assert (
        commands["start"] == "docker compose --env-file .env.production -f docker-compose.yml "
        "-f docker-compose.caddy-public.yml up -d --remove-orphans"
    )


def test_build_lifecycle_commands_for_no_caddy_file() -> None:
    commands = build_lifecycle_commands(
        deployment_mode=DEPLOY_MODE_LOCAL,
        use_caddy=False,
        caddy_public=False,
    )
    assert (
        commands["start"] == "docker compose --env-file .env.production "
        "-f docker-compose.nocaddy.yml up -d --remove-orphans"
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
        commands["start"] == "docker compose --env-file .env.production "
        "-f docker-compose.image.yml up -d --remove-orphans"
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
        commands["start"] == "docker compose --env-file .env.production "
        "-f docker-compose.image.nocaddy.yml up -d --remove-orphans"
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


def test_write_config_files_with_caddy_local_and_goatcounter_disabled(tmp_path: Path) -> None:
    config = _make_config(
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
        deploy_goatcounter=False,
    )
    write_config_files(config, tmp_path)

    assert (tmp_path / ".env.production").exists()
    assert (tmp_path / "Caddyfile.production").exists()
    compose_path = tmp_path / DEFAULT_BUNDLED_CADDY_COMPOSE_FILE
    assert compose_path.exists()
    compose_content = compose_path.read_text(encoding="utf-8")
    assert "goatcounter:" not in compose_content
    assert "goatcounter-db:/data/goatcounter" not in compose_content
    assert "goatcounter-token:/data/goatcounter-token:ro" not in compose_content


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
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    commands = _stub_subprocess(monkeypatch)
    _stub_no_trivy(monkeypatch)

    config = _make_config()
    result = deploy(config=config, project_dir=tmp_path)

    assert result.env_path == tmp_path / ".env.production"
    assert (
        result.commands["start"] == "docker compose --env-file .env.production "
        "-f docker-compose.nocaddy.yml up -d --remove-orphans"
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
                "--remove-orphans",
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
        "-f docker-compose.caddy-public.yml up -d --remove-orphans"
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
                "--remove-orphans",
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
        == "docker compose --env-file .env.production -f docker-compose.yml up -d --remove-orphans"
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
                "--remove-orphans",
                "--build",
            ],
            tmp_path,
            True,
        )
    ]


def test_deploy_with_local_caddy_and_disabled_goatcounter_runs_generated_compose(
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
        deploy_goatcounter=False,
    )

    result = deploy(config=config, project_dir=tmp_path)

    assert (
        result.commands["start"] == "docker compose --env-file .env.production "
        f"-f {DEFAULT_BUNDLED_CADDY_COMPOSE_FILE} up -d --remove-orphans"
    )
    compose_content = (tmp_path / DEFAULT_BUNDLED_CADDY_COMPOSE_FILE).read_text(encoding="utf-8")
    assert "goatcounter:" not in compose_content
    assert commands == [
        (
            [
                "docker",
                "compose",
                "--env-file",
                ".env.production",
                "-f",
                DEFAULT_BUNDLED_CADDY_COMPOSE_FILE,
                "up",
                "-d",
                "--remove-orphans",
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

    config = _make_config(scan_image=True)
    deploy(config=config, project_dir=tmp_path)

    assert commands == [
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
                "--format",
                "json",
                "--quiet",
                "--severity",
                "MEDIUM,HIGH,CRITICAL",
                LOCAL_IMAGE_TAG,
            ],
            tmp_path,
            False,
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
                "--remove-orphans",
            ],
            tmp_path,
            True,
        ),
    ]


def test_deploy_skips_scan_when_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    commands = _stub_subprocess(monkeypatch)
    _stub_with_trivy(monkeypatch)

    config = _make_config(scan_image=False)
    deploy(config=config, project_dir=tmp_path)

    # No trivy commands at all — just compose up (with build).
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
                "--remove-orphans",
                "--build",
            ],
            tmp_path,
            True,
        ),
    ]


def test_scan_image_reports_findings_as_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """scan_image prints a concise warning summary and returns findings."""
    trivy_output = {
        "Results": [
            {
                "Target": "usr/local/bin/uv (rustbinary)",
                "Type": "rustbinary",
                "Vulnerabilities": [
                    {
                        "VulnerabilityID": "CVE-2026-99999",
                        "PkgName": "somecrate",
                        "InstalledVersion": "1.0.0",
                        "FixedVersion": "2.0.0",
                        "Severity": "HIGH",
                        "Title": "A bad vulnerability",
                    },
                ],
            },
        ],
    }
    import json

    monkeypatch.setattr(
        "cli.deploy_production.subprocess.run",
        lambda *_a, **_kw: SimpleNamespace(
            returncode=1,
            stdout=json.dumps(trivy_output).encode(),
            stderr=b"",
        ),
    )

    findings = scan_image(tmp_path, "img:test")

    assert len(findings) == 1
    assert findings[0]["id"] == "CVE-2026-99999"
    assert findings[0]["severity"] == "HIGH"

    captured = capsys.readouterr()
    assert "1 vulnerability" in captured.err
    assert "1 HIGH" in captured.err
    assert "CVE-2026-99999" in captured.err

    # Full report file is written and the user is told where to find it.
    report_path = tmp_path / "trivy-report.json"
    assert report_path.exists()
    report_data = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_data == trivy_output
    assert str(report_path) in captured.err


def test_scan_image_no_findings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """scan_image prints a success message when no vulnerabilities are found."""
    monkeypatch.setattr(
        "cli.deploy_production.subprocess.run",
        lambda *_a, **_kw: SimpleNamespace(
            returncode=0,
            stdout=b'{"Results":[]}',
            stderr=b"",
        ),
    )

    findings = scan_image(tmp_path, "img:test")

    assert findings == []
    captured = capsys.readouterr()
    assert "no vulnerabilities found" in captured.out
    # No report file when there are no findings.
    assert not (tmp_path / "trivy-report.json").exists()


def test_scan_image_tolerates_trivy_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """scan_image returns empty list and warns when trivy fails."""
    import subprocess as _sp

    monkeypatch.setattr(
        "cli.deploy_production.subprocess.run",
        lambda *_a, **_kw: (_ for _ in ()).throw(_sp.TimeoutExpired(["trivy"], 30)),
    )

    findings = scan_image(tmp_path, "img:test")

    assert findings == []
    captured = capsys.readouterr()
    assert "security scan failed" in captured.err


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
    assert result.env_path == tmp_path / DEFAULT_BUNDLE_DIR / DEFAULT_ENV_GENERATED_FILE
    assert (tmp_path / DEFAULT_BUNDLE_DIR / (DEFAULT_IMAGE_COMPOSE_FILE + ".generated")).exists()
    assert not (
        tmp_path / DEFAULT_BUNDLE_DIR / (DEFAULT_IMAGE_NO_CADDY_COMPOSE_FILE + ".generated")
    ).exists()
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
    assert result.env_path == tmp_path / DEFAULT_BUNDLE_DIR / DEFAULT_ENV_GENERATED_FILE
    assert (
        tmp_path / DEFAULT_BUNDLE_DIR / (DEFAULT_IMAGE_NO_CADDY_COMPOSE_FILE + ".generated")
    ).exists()
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
                str((tmp_path / DEFAULT_BUNDLE_DIR / DEFAULT_IMAGE_TARBALL).with_suffix("")),
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
        caddy_external=False,
        shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
        shared_caddy_email=None,
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
        skip_scan=False,
        max_content_size=None,
        disable_password_change=False,
        disable_goatcounter=False,
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
        caddy_external=False,
        shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
        shared_caddy_email=None,
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
        skip_scan=False,
        max_content_size=None,
        disable_password_change=False,
        disable_goatcounter=False,
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
        caddy_external=False,
        shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
        shared_caddy_email=None,
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
        skip_scan=False,
        max_content_size=None,
        disable_password_change=False,
        disable_goatcounter=False,
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
        caddy_external=False,
        shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
        shared_caddy_email=None,
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
        skip_scan=False,
        max_content_size=None,
        disable_password_change=False,
        disable_goatcounter=False,
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
        caddy_external=False,
        shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
        shared_caddy_email=None,
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
        skip_scan=False,
        max_content_size=None,
        disable_password_change=False,
        disable_goatcounter=False,
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
        caddy_external=False,
        shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
        shared_caddy_email=None,
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
        skip_scan=False,
        max_content_size=None,
        disable_password_change=False,
        disable_goatcounter=False,
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
        caddy_external=False,
        shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
        shared_caddy_email=None,
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
        skip_scan=False,
        max_content_size=None,
        disable_password_change=False,
        disable_goatcounter=False,
    )

    with pytest.raises(DeployError, match="--trusted-hosts"):
        config_from_args(args)


def test_config_from_args_defaults_image_ref_for_registry_mode() -> None:
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password="strong-password!",
        admin_display_name=None,
        caddy_domain=None,
        caddy_email=None,
        caddy_public=False,
        caddy_external=False,
        shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
        shared_caddy_email=None,
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
        skip_scan=False,
        max_content_size=None,
        disable_password_change=False,
        disable_goatcounter=False,
    )

    config = config_from_args(args)
    assert config.image_ref == DEFAULT_IMAGE_REF


def test_config_from_args_defaults_image_ref_for_tarball_mode() -> None:
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password="strong-password!",
        admin_display_name=None,
        caddy_domain=None,
        caddy_email=None,
        caddy_public=False,
        caddy_external=False,
        shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
        shared_caddy_email=None,
        trusted_hosts="example.com",
        trusted_proxy_ips=None,
        host_port=8000,
        bind_public=False,
        expose_docs=False,
        deployment_mode=DEPLOY_MODE_TARBALL,
        image_ref=None,
        bundle_dir=DEFAULT_BUNDLE_DIR,
        tarball_filename=DEFAULT_IMAGE_TARBALL,
        platform=None,
        skip_scan=False,
        max_content_size=None,
        disable_password_change=False,
        disable_goatcounter=False,
    )

    config = config_from_args(args)
    assert config.image_ref == DEFAULT_IMAGE_REF


def test_config_from_args_builds_registry_mode() -> None:
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password="strong-password!",
        admin_display_name=None,
        caddy_domain=None,
        caddy_email=None,
        caddy_public=False,
        caddy_external=False,
        shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
        shared_caddy_email=None,
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
        skip_scan=False,
        max_content_size=None,
        disable_password_change=False,
        disable_goatcounter=False,
    )

    config = config_from_args(args)

    assert config.deployment_mode == DEPLOY_MODE_REGISTRY
    assert config.image_ref == "ghcr.io/example/agblogger:1.2.3"


def test_config_from_args_disables_goatcounter_when_requested() -> None:
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password="strong-password!",
        admin_display_name=None,
        caddy_domain="blog.example.com",
        caddy_email=None,
        caddy_public=False,
        caddy_external=False,
        shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
        shared_caddy_email=None,
        trusted_hosts="blog.example.com",
        trusted_proxy_ips=None,
        host_port=8000,
        bind_public=False,
        expose_docs=False,
        deployment_mode=DEPLOY_MODE_TARBALL,
        image_ref=None,
        bundle_dir=DEFAULT_BUNDLE_DIR,
        tarball_filename=DEFAULT_IMAGE_TARBALL,
        platform=None,
        skip_scan=False,
        max_content_size=None,
        disable_password_change=False,
        disable_goatcounter=True,
    )

    config = config_from_args(args)

    assert config.deploy_goatcounter is False


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
        deployment_mode=DEPLOY_MODE_LOCAL,
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
        caddy_external=False,
        shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
        shared_caddy_email=None,
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
        skip_scan=False,
        max_content_size=None,
        disable_password_change=False,
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
        caddy_external=False,
        shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
        shared_caddy_email=None,
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
        skip_scan=False,
        max_content_size=None,
        disable_password_change=False,
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
        caddy_external=False,
        shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
        shared_caddy_email=None,
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
        skip_scan=False,
        max_content_size=None,
        disable_password_change=False,
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
    assert '"127.0.0.1:443:443/udp"' in section
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
            "--deployment-mode",
            "local",
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
        assert "HOST_PORT=8000  # Not used in Caddy modes" in content
        assert "HOST_BIND_IP=127.0.0.1  # Not used in Caddy modes" in content

    def test_no_caddy_mode_omits_comment(self) -> None:
        config = _make_config()
        content = build_env_content(config)
        assert "HOST_PORT=8000\n" in content
        assert "# Not used in Caddy modes" not in content


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
        assert "setup.sh" in content
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
        assert "setup.sh" in content


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

    def test_dry_run_local_caddy_disabled_goatcounter_prints_generated_compose(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = _make_config(
            caddy_config=CaddyConfig(domain="blog.example.com", email=None),
            caddy_public=False,
            host_bind_ip=LOCALHOST_BIND_IP,
            deploy_goatcounter=False,
        )
        dry_run(config)

        captured = capsys.readouterr().out
        assert "Using existing docker-compose.yml" not in captured
        assert f"=== {DEFAULT_BUNDLED_CADDY_COMPOSE_FILE} ===" in captured
        assert "goatcounter:" not in captured


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
        assert "setup.sh" in content

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
        assert "setup.sh" in content


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
        assert "up -d --remove-orphans" in commands["upgrade"]

    def test_tarball_mode_upgrade_loads_then_starts(self) -> None:
        commands = build_lifecycle_commands(
            deployment_mode=DEPLOY_MODE_TARBALL,
            use_caddy=False,
            caddy_public=False,
        )
        assert "upgrade" in commands
        assert "load" in commands["upgrade"]
        assert "up -d --remove-orphans" in commands["upgrade"]


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


# ── Task 10: Validation for external Caddy mode ──────────────────────


def test_validate_config_external_caddy_requires_caddy_config() -> None:
    config = _make_config(caddy_mode=CADDY_MODE_EXTERNAL, caddy_config=None)
    with pytest.raises(DeployError, match="requires a domain"):
        _validate_config(config)


def test_validate_config_external_caddy_requires_shared_caddy_config() -> None:
    config = _make_config(
        caddy_mode=CADDY_MODE_EXTERNAL,
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
        shared_caddy_config=None,
    )
    with pytest.raises(DeployError, match="shared Caddy configuration"):
        _validate_config(config)


def test_validate_config_external_caddy_valid() -> None:
    from pathlib import Path

    config = _make_config(
        caddy_mode=CADDY_MODE_EXTERNAL,
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
        shared_caddy_config=SharedCaddyConfig(caddy_dir=Path("/opt/caddy"), acme_email=None),
    )
    _validate_config(config)  # Should not raise


def test_validate_config_rejects_invalid_shared_acme_email() -> None:
    config = _make_config(
        caddy_mode=CADDY_MODE_EXTERNAL,
        caddy_config=CaddyConfig(domain="blog.example.com", email="ops@example.com"),
        host_bind_ip=LOCALHOST_BIND_IP,
        shared_caddy_config=SharedCaddyConfig(
            caddy_dir=Path("/opt/caddy"), acme_email="notanemail"
        ),
    )
    with pytest.raises(DeployError, match="Shared Caddy ACME email must contain"):
        _validate_config(config)


def test_validate_config_rejects_invalid_caddy_mode() -> None:
    config = _make_config(caddy_mode=cast("CaddyMode", "invalid"))
    with pytest.raises(DeployError, match="caddy_mode"):
        _validate_config(config)


# ── Task 11: Compose filename helpers and lifecycle commands ─────────


def test_build_lifecycle_commands_for_external_caddy_local() -> None:
    commands = build_lifecycle_commands(
        deployment_mode=DEPLOY_MODE_LOCAL,
        use_caddy=False,
        caddy_public=False,
        caddy_mode=CADDY_MODE_EXTERNAL,
    )
    assert DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE in commands["start"]


def test_build_lifecycle_commands_for_external_caddy_registry() -> None:
    commands = build_lifecycle_commands(
        deployment_mode=DEPLOY_MODE_REGISTRY,
        use_caddy=False,
        caddy_public=False,
        caddy_mode=CADDY_MODE_EXTERNAL,
    )
    assert DEFAULT_IMAGE_EXTERNAL_CADDY_COMPOSE_FILE in commands["start"]
    assert "pull" in commands


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

        _stub_no_trivy(monkeypatch)

        # Write an existing .env.production
        existing_config = _make_config()
        env_content = build_env_content(existing_config)
        (tmp_path / DEFAULT_ENV_FILE).write_text(env_content, encoding="utf-8")

        # Simulate interactive answers: reuse=yes, mode=local, caddy=none, public=no,
        # port=8000, trusted hosts=example.com, proxy ips=(none), expose docs=no
        inputs = iter(["y", "local", "none", "n", "", "example.com", "", "n", "", "y"])
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

        _stub_no_trivy(monkeypatch)

        # Simulate: secret_key=auto, username=admin, display_name=admin,
        # password+confirm, mode=local,
        # caddy=none, public=no, port=8000, trusted hosts=example.com, proxy ips,
        # expose docs=no
        inputs = iter(["admin", "", "local", "none", "n", "", "example.com", "", "n", "", "y"])
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
            caddy_external=False,
            shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
            shared_caddy_email=None,
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
            skip_scan=False,
            max_content_size=None,
            disable_password_change=False,
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
            caddy_external=False,
            shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
            shared_caddy_email=None,
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
            skip_scan=False,
            max_content_size=None,
            disable_password_change=False,
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
            caddy_external=False,
            shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
            shared_caddy_email=None,
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
            skip_scan=False,
            max_content_size=None,
            disable_password_change=False,
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
            caddy_external=False,
            shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
            shared_caddy_email=None,
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
            skip_scan=False,
            max_content_size=None,
            disable_password_change=False,
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
    """Tarball upgrade numbered steps should include copying bundle files."""

    def test_tarball_upgrade_has_copy_as_numbered_step(self) -> None:
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
        # "copy" should appear in a numbered step, not just prose
        numbered_steps = re.findall(r"^\d+\..+", upgrade_section, re.MULTILINE)
        assert any("copy" in step.lower() for step in numbered_steps)

    def test_registry_upgrade_has_copy_as_numbered_step(self) -> None:
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
        numbered_steps = re.findall(r"^\d+\..+", upgrade_section, re.MULTILINE)
        assert any("copy" in step.lower() for step in numbered_steps)


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


class TestDnsInfoMessage:
    """Interactive Caddy setup should print a DNS info message."""

    def test_caddy_setup_prints_dns_info(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from cli.deploy_production import collect_config

        _stub_no_trivy(monkeypatch)

        # Simulate: no existing env, secret_key=auto, username=admin,
        # display_name=admin, password+confirm,
        # mode=local, caddy=bundled, domain, email, caddy_public=yes,
        # trusted hosts, proxy ips, expose docs=no
        inputs = iter(
            [
                "admin",  # admin username
                "",  # admin display name (default=admin)
                "local",  # deployment mode
                "bundled",  # caddy mode
                "blog.example.com",  # caddy domain
                "",  # caddy email
                "y",  # caddy public
                "",  # additional trusted hosts
                "",  # additional proxy ips
                "n",  # expose docs
                "",  # max content size (unlimited)
                "y",  # deploy GoatCounter
            ]
        )
        passwords = iter(["", "strongpass123", "strongpass123"])

        monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))
        monkeypatch.setattr(
            "cli.deploy_production.getpass.getpass", lambda _prompt: next(passwords)
        )

        config = collect_config(tmp_path)

        assert config.caddy_config is not None
        assert config.caddy_config.domain == "blog.example.com"
        # Verify a DNS info message was printed with remote-friendly wording
        output = capsys.readouterr().out
        assert "DNS" in output
        assert "blog.example.com" in output
        assert "your server" in output
        assert "this server" not in output

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
                "--deployment-mode",
                "local",
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


# ── Task 16: config_from_args external Caddy ─────────────────────────


def test_config_from_args_external_caddy() -> None:
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password="strong-password!",
        admin_display_name=None,
        caddy_domain="blog.example.com",
        caddy_email="ops@example.com",
        caddy_public=False,
        caddy_external=True,
        shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
        shared_caddy_email=None,
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
        skip_scan=False,
        max_content_size=None,
        disable_password_change=False,
    )
    config = config_from_args(args)
    assert config.caddy_mode == CADDY_MODE_EXTERNAL
    assert config.caddy_config is not None
    assert config.caddy_config.domain == "blog.example.com"
    assert config.shared_caddy_config is not None
    assert config.shared_caddy_config.caddy_dir == Path(DEFAULT_SHARED_CADDY_DIR).expanduser()
    assert config.shared_caddy_config.acme_email == "ops@example.com"


def test_config_from_args_external_caddy_with_explicit_shared_email() -> None:
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password="strong-password!",
        admin_display_name=None,
        caddy_domain="blog.example.com",
        caddy_email="site@example.com",
        caddy_public=False,
        caddy_external=True,
        shared_caddy_dir="/srv/caddy",
        shared_caddy_email="global@example.com",
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
        skip_scan=False,
        max_content_size=None,
        disable_password_change=False,
    )
    config = config_from_args(args)
    assert config.shared_caddy_config is not None
    assert config.shared_caddy_config.caddy_dir == Path("/srv/caddy")
    assert config.shared_caddy_config.acme_email == "global@example.com"


def test_config_from_args_external_caddy_remote_keeps_tilde() -> None:
    """For remote deploys, caddy_dir with ~ must not be expanded to local home."""
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password="strong-password!",
        admin_display_name=None,
        caddy_domain="blog.example.com",
        caddy_email="ops@example.com",
        caddy_public=False,
        caddy_external=True,
        shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
        shared_caddy_email=None,
        trusted_hosts="blog.example.com",
        trusted_proxy_ips=None,
        host_port=8000,
        bind_public=False,
        expose_docs=False,
        deployment_mode=DEPLOY_MODE_TARBALL,
        image_ref="ghcr.io/example/agblogger:v1.0",
        bundle_dir=DEFAULT_BUNDLE_DIR,
        tarball_filename=DEFAULT_IMAGE_TARBALL,
        platform=None,
        skip_scan=False,
        max_content_size=None,
        disable_password_change=False,
    )
    config = config_from_args(args)
    assert config.shared_caddy_config is not None
    # Path must not be expanded on the local machine
    assert config.shared_caddy_config.caddy_dir == Path(DEFAULT_SHARED_CADDY_DIR)


# ── Task 17: dry_run and print_config_summary for external Caddy ──────


def test_dry_run_external_caddy(capsys: pytest.CaptureFixture[str]) -> None:
    config = _make_config(
        caddy_mode=CADDY_MODE_EXTERNAL,
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
        shared_caddy_config=SharedCaddyConfig(caddy_dir=Path("/opt/caddy"), acme_email=None),
    )
    dry_run(config)
    captured = capsys.readouterr().out
    assert f"=== {DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE} ===" in captured
    assert "blog.example.com" in captured
    assert "=== Caddyfile.production ===" not in captured


def test_print_config_summary_external_caddy(capsys: pytest.CaptureFixture[str]) -> None:
    config = _make_config(
        caddy_mode=CADDY_MODE_EXTERNAL,
        caddy_config=CaddyConfig(domain="blog.example.com", email="ops@example.com"),
        host_bind_ip=LOCALHOST_BIND_IP,
        shared_caddy_config=SharedCaddyConfig(
            caddy_dir=Path(DEFAULT_SHARED_CADDY_DIR).expanduser(),
            acme_email="ops@example.com",
        ),
    )
    print_config_summary(config)
    captured = capsys.readouterr().out
    assert "external" in captured.lower()
    assert str(Path(DEFAULT_SHARED_CADDY_DIR).expanduser()) in captured
    assert "blog.example.com" in captured


# ── Task 18: _build_remote_readme_content for external Caddy ─────────


def test_remote_readme_external_caddy_mentions_shared_setup() -> None:
    config = _make_config(
        caddy_mode=CADDY_MODE_EXTERNAL,
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
        shared_caddy_config=SharedCaddyConfig(caddy_dir=Path("/opt/caddy"), acme_email=None),
        deployment_mode=DEPLOY_MODE_REGISTRY,
        image_ref="ghcr.io/example/agblogger:1.0",
    )
    commands = build_lifecycle_commands(
        deployment_mode=DEPLOY_MODE_REGISTRY,
        use_caddy=False,
        caddy_public=False,
        caddy_mode=CADDY_MODE_EXTERNAL,
    )
    content = _build_remote_readme_content(config, commands)
    assert "Shared Caddy Setup" not in content
    assert "deployment script will bootstrap" not in content


# ── Bundle dir credential reuse ──────────────────────────────────────


class TestCollectConfigBundleDirReuse:
    """collect_config should fall back to bundle dir when no project-root env exists."""

    def test_reuses_secrets_from_bundle_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.deploy_production import collect_config

        _stub_no_trivy(monkeypatch)

        # Write .env.production only in the bundle dir, not project root
        existing_config = _make_config()
        env_content = build_env_content(existing_config)
        bundle_dir = tmp_path / DEFAULT_BUNDLE_DIR
        bundle_dir.mkdir(parents=True)
        (bundle_dir / DEFAULT_ENV_FILE).write_text(env_content, encoding="utf-8")

        # Simulate: reuse=yes, mode=local, caddy=none, public=no,
        # port=8000, trusted hosts, proxy ips, docs=no
        inputs = iter(["y", "local", "none", "n", "", "example.com", "", "n", "", "y"])
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

        _stub_no_trivy(monkeypatch)

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

        # Simulate: reuse=yes, mode=local, caddy=none, public=no,
        # port=8000, trusted hosts, proxy ips, docs=no
        inputs = iter(["y", "local", "none", "n", "", "example.com", "", "n", "", "y"])
        monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))
        monkeypatch.setattr("cli.deploy_production.getpass.getpass", lambda _prompt: "")

        config = collect_config(tmp_path)

        # Should use the project-root config, not the bundle one
        assert config.secret_key == root_config.secret_key
        assert config.admin_username == root_config.admin_username


class TestCollectConfigExternalCaddy:
    """collect_config should handle external Caddy mode interactive flow."""

    def test_external_caddy_collects_shared_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.deploy_production import collect_config

        _stub_no_trivy(monkeypatch)

        # Simulate: no reuse, mode=local, caddy=external,
        # domain=blog.example.com, email=ops@example.com, public=no,
        # shared dir=default, acme email=(use default from caddy email),
        # trusted hosts=blog.example.com, extra proxy ips=(none), docs=no
        inputs = iter(
            [
                "admin",  # admin username
                "",  # admin display name (default=admin)
                "local",  # deployment mode
                "external",  # caddy mode
                "blog.example.com",  # caddy domain
                "ops@example.com",  # caddy email
                DEFAULT_SHARED_CADDY_DIR,  # shared caddy dir
                "",  # acme email (use default)
                "blog.example.com",  # trusted hosts
                "",  # extra proxy ips
                "n",  # expose docs
                "",  # max content size (unlimited)
                "y",  # deploy GoatCounter
            ]
        )
        getpass_inputs = iter(
            [
                "x" * 64,  # secret key (≥32 chars)
                "strong-password!",  # admin password
                "strong-password!",  # admin password confirmation
            ]
        )
        monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))
        monkeypatch.setattr(
            "cli.deploy_production.getpass.getpass",
            lambda _prompt: next(getpass_inputs),
        )

        config = collect_config(tmp_path)

        assert config.caddy_mode == CADDY_MODE_EXTERNAL
        assert config.caddy_config is not None
        assert config.caddy_config.domain == "blog.example.com"
        assert config.shared_caddy_config is not None
        assert config.shared_caddy_config.caddy_dir == Path(DEFAULT_SHARED_CADDY_DIR).expanduser()
        assert config.shared_caddy_config.acme_email == "ops@example.com"

    def test_remote_deploy_keeps_tilde_unexpanded(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """For remote deploy modes, caddy_dir with ~ must not be expanded to local home."""
        from cli.deploy_production import collect_config

        _stub_no_trivy(monkeypatch)

        inputs = iter(
            [
                "admin",  # admin username
                "",  # admin display name (default=admin)
                "tarball",  # deployment mode
                "ghcr.io/example/agblogger:v1.0",  # image ref
                DEFAULT_IMAGE_TARBALL,  # tarball filename
                "external",  # caddy mode
                "blog.example.com",  # caddy domain
                "ops@example.com",  # caddy email
                DEFAULT_SHARED_CADDY_DIR,  # shared caddy dir
                "",  # acme email (use default)
                "blog.example.com",  # trusted hosts
                "",  # extra proxy ips
                "n",  # expose docs
                "",  # max content size (unlimited)
                "y",  # deploy GoatCounter
            ]
        )
        getpass_inputs = iter(
            [
                "x" * 64,  # secret key (≥32 chars)
                "strong-password!",  # admin password
                "strong-password!",  # admin password confirmation
            ]
        )
        monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))
        monkeypatch.setattr(
            "cli.deploy_production.getpass.getpass",
            lambda _prompt: next(getpass_inputs),
        )

        config = collect_config(tmp_path)

        assert config.shared_caddy_config is not None
        # Path must not be expanded on the local machine for remote deploys
        assert config.shared_caddy_config.caddy_dir == Path(DEFAULT_SHARED_CADDY_DIR)


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
    """Remote deployment README should advise copying the full bundle on upgrade."""

    def test_registry_readme_mentions_copy_all_files(self) -> None:
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
        assert "copy all files" in content.lower()
        assert "compose files and config may change" in content
        assert ".env.production" in content

    def test_tarball_readme_mentions_copy_all_files(self) -> None:
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
        assert "copy all files" in content.lower()
        assert ".env.production" in content


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


def test_caddy_modes_set_matches_literal() -> None:
    """CADDY_MODES set is derived from CaddyMode Literal and stays in sync."""
    from typing import get_args

    assert set(get_args(CaddyMode)) == CADDY_MODES
    assert CADDY_MODE_BUNDLED in CADDY_MODES
    assert CADDY_MODE_EXTERNAL in CADDY_MODES
    assert CADDY_MODE_NONE in CADDY_MODES


def test_default_shared_caddy_dir_constant() -> None:
    assert DEFAULT_SHARED_CADDY_DIR == "~/.local/share/caddy"


def test_shared_caddy_runtime_dir_keeps_home_scoped_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_dir = Path("/home/deploy")
    monkeypatch.setattr("cli.deploy_production._docker_is_snap_install", lambda: True)
    runtime_dir = _shared_caddy_runtime_dir(
        Path(DEFAULT_SHARED_CADDY_DIR),
        home_dir=home_dir,
    )
    assert runtime_dir == home_dir / ".local/share/caddy"


def test_shared_caddy_runtime_dir_falls_back_from_opt_on_snap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_dir = Path("/home/deploy")
    monkeypatch.setattr("cli.deploy_production._docker_is_snap_install", lambda: True)
    runtime_dir = _shared_caddy_runtime_dir(
        Path("/opt/caddy"),
        home_dir=home_dir,
    )
    assert runtime_dir == home_dir / ".local/share/caddy"


def test_external_caddy_network_name_constant() -> None:
    assert EXTERNAL_CADDY_NETWORK_NAME == "caddy"


# ── DeployConfig external caddy fields ──────────────────────────────


def test_deploy_config_external_caddy_fields() -> None:
    from pathlib import Path

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
        caddy_mode=CADDY_MODE_EXTERNAL,
        shared_caddy_config=SharedCaddyConfig(
            caddy_dir=Path("/opt/caddy"), acme_email="ops@example.com"
        ),
    )
    assert config.caddy_mode == CADDY_MODE_EXTERNAL
    assert config.shared_caddy_config is not None
    assert config.shared_caddy_config.caddy_dir == Path("/opt/caddy")


def test_deploy_config_caddy_mode_defaults_to_none() -> None:
    config = DeployConfig(
        secret_key="x" * 64,
        admin_username="admin",
        admin_password="very-strong-password",
        trusted_hosts=["example.com"],
        trusted_proxy_ips=[],
        host_port=8000,
        host_bind_ip=PUBLIC_BIND_IP,
        caddy_config=None,
        caddy_public=False,
        expose_docs=False,
    )
    assert config.caddy_mode == CADDY_MODE_NONE
    assert config.shared_caddy_config is None


def test_make_config_bundled_caddy_has_bundled_mode() -> None:
    config = _make_config(
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
        caddy_mode=CADDY_MODE_BUNDLED,
    )
    assert config.caddy_mode == CADDY_MODE_BUNDLED


def test_make_config_no_caddy_has_none_mode() -> None:
    config = _make_config()
    assert config.caddy_mode == CADDY_MODE_NONE


# ── caddy_mode in config construction paths ──────────────────────────


def test_config_from_args_sets_bundled_mode_when_caddy_domain_given() -> None:
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password="strong-password!",
        admin_display_name=None,
        caddy_domain="blog.example.com",
        caddy_email=None,
        caddy_public=False,
        caddy_external=False,
        shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
        shared_caddy_email=None,
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
        skip_scan=False,
        max_content_size=None,
        disable_password_change=False,
    )

    config = config_from_args(args)
    assert config.caddy_mode == CADDY_MODE_BUNDLED


def test_config_from_args_sets_none_mode_when_no_caddy_domain() -> None:
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password="strong-password!",
        admin_display_name=None,
        caddy_domain=None,
        caddy_email=None,
        caddy_public=False,
        caddy_external=False,
        shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
        shared_caddy_email=None,
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
        skip_scan=False,
        max_content_size=None,
        disable_password_change=False,
    )

    config = config_from_args(args)
    assert config.caddy_mode == CADDY_MODE_NONE


def test_config_from_args_respects_disable_password_change_flag() -> None:
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password="strong-password!",
        admin_display_name=None,
        caddy_domain=None,
        caddy_email=None,
        caddy_public=False,
        caddy_external=False,
        shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
        shared_caddy_email=None,
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
        skip_scan=False,
        max_content_size=None,
        disable_password_change=True,
    )

    config = config_from_args(args)
    assert config.disable_password_change is True


# ── build_caddy_site_snippet ─────────────────────────────────────────


def test_build_caddy_site_snippet_contains_domain_block() -> None:
    caddy = CaddyConfig(domain="blog.example.com", email="ops@example.com")
    content = build_caddy_site_snippet(caddy)
    assert "blog.example.com {" in content
    assert "reverse_proxy agblogger:8000" in content
    assert "email" not in content.split("{")[0]


def test_build_caddy_site_snippet_includes_request_body_limits() -> None:
    caddy = CaddyConfig(domain="blog.example.com", email=None)
    content = build_caddy_site_snippet(caddy)
    assert "@postUpload" in content
    assert "max_size 55MB" in content
    assert "@syncCommit" in content
    assert "max_size 100MB" in content


def test_build_caddy_site_snippet_includes_hsts() -> None:
    caddy = CaddyConfig(domain="blog.example.com", email=None)
    content = build_caddy_site_snippet(caddy)
    assert "Strict-Transport-Security" in content


# ── build_shared_caddyfile_content ───────────────────────────────────


def test_build_shared_caddyfile_with_email() -> None:
    content = build_shared_caddyfile_content(acme_email="ops@example.com")
    assert "email ops@example.com" in content
    assert "protocols h1 h2 h3" in content
    assert "import /etc/caddy/sites/*.caddy" in content


def test_build_shared_caddyfile_without_email() -> None:
    content = build_shared_caddyfile_content(acme_email=None)
    assert "email" not in content
    assert "protocols h1 h2 h3" in content
    assert "import /etc/caddy/sites/*.caddy" in content


# ── build_shared_caddy_compose_content ──────────────────────────────


def test_build_shared_caddy_compose_has_caddy_service() -> None:
    content = build_shared_caddy_compose_content()
    assert "caddy:" in content
    assert "image: caddy:2" in content
    assert '"80:80"' in content
    assert '"443:443"' in content
    assert '"443:443/udp"' in content


def test_build_shared_caddy_compose_has_sites_volume() -> None:
    content = build_shared_caddy_compose_content()
    assert "./sites:/etc/caddy/sites:ro" in content
    assert "./Caddyfile:/etc/caddy/Caddyfile:ro" in content


def test_build_shared_caddy_compose_defines_external_network() -> None:
    content = build_shared_caddy_compose_content()
    assert f"name: {EXTERNAL_CADDY_NETWORK_NAME}" in content


def test_build_shared_caddy_compose_has_restart_policy() -> None:
    content = build_shared_caddy_compose_content()
    assert "restart: unless-stopped" in content


# ── build_external_caddy_compose_content ─────────────────────────────


def test_build_external_caddy_compose_joins_external_network() -> None:
    content = build_external_caddy_compose_content()
    assert f"name: {EXTERNAL_CADDY_NETWORK_NAME}" in content
    assert "external: true" in content
    assert "caddy:" not in content.split("networks:")[0]


def test_build_external_caddy_compose_exposes_port_internally() -> None:
    content = build_external_caddy_compose_content()
    assert "expose:" in content
    assert '"8000"' in content
    assert "ports:" not in content


def test_build_external_caddy_compose_has_build_directive() -> None:
    content = build_external_caddy_compose_content()
    assert "build: ." in content


# ── build_image_external_caddy_compose_content ───────────────────────


def test_build_image_external_caddy_compose_uses_image_ref() -> None:
    content = build_image_external_caddy_compose_content()
    assert "${AGBLOGGER_IMAGE?Set AGBLOGGER_IMAGE}" in content
    assert "build:" not in content


def test_build_image_external_caddy_compose_joins_external_network() -> None:
    content = build_image_external_caddy_compose_content()
    assert f"name: {EXTERNAL_CADDY_NETWORK_NAME}" in content
    assert "external: true" in content


# ── ensure_shared_caddy ──────────────────────────────────────────────


def test_ensure_shared_caddy_creates_directory_structure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    commands = _stub_subprocess(monkeypatch)
    _stub_docker_inspect_missing(monkeypatch)
    caddy_dir = tmp_path / "caddy"
    ensure_shared_caddy(caddy_dir=caddy_dir, acme_email="ops@example.com")
    assert (caddy_dir / "sites").is_dir()
    assert (caddy_dir / "Caddyfile").exists()
    assert "import /etc/caddy/sites/*.caddy" in (caddy_dir / "Caddyfile").read_text("utf-8")
    assert "email ops@example.com" in (caddy_dir / "Caddyfile").read_text("utf-8")
    assert (caddy_dir / "docker-compose.yml").exists()
    _ = commands  # captured but not inspected here


def test_ensure_shared_caddy_starts_container(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    commands = _stub_subprocess(monkeypatch)
    _stub_docker_inspect_missing(monkeypatch)
    caddy_dir = tmp_path / "caddy"
    ensure_shared_caddy(caddy_dir=caddy_dir, acme_email=None)
    run_calls = [(cmd, cwd) for cmd, cwd, _ in commands if cmd[:3] == ["docker", "run", "-d"]]
    assert len(run_calls) == 1
    assert run_calls[0][1] == caddy_dir
    assert "--name" in run_calls[0][0]
    assert SHARED_CADDY_CONTAINER_NAME in run_calls[0][0]


def test_ensure_shared_caddy_skips_if_already_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    commands = _stub_subprocess(monkeypatch)
    _stub_docker_inspect_running(monkeypatch)
    caddy_dir = tmp_path / "caddy"
    caddy_dir.mkdir()
    (caddy_dir / "sites").mkdir()
    (caddy_dir / "Caddyfile").write_text("existing", encoding="utf-8")
    (caddy_dir / "docker-compose.yml").write_text("existing", encoding="utf-8")
    ensure_shared_caddy(caddy_dir=caddy_dir, acme_email=None)
    start_calls = [cmd for cmd, _, _ in commands if cmd[:2] == ["docker", "start"]]
    run_calls = [cmd for cmd, _, _ in commands if cmd[:3] == ["docker", "run", "-d"]]
    assert len(start_calls) == 0
    assert len(run_calls) == 0


# ── write_caddy_site_snippet / reload_shared_caddy ───────────────────


def test_write_caddy_site_snippet_creates_file(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()
    caddy_config = CaddyConfig(domain="blog.example.com", email=None)
    write_caddy_site_snippet(caddy_config, tmp_path)
    snippet_path = sites_dir / "blog.example.com.caddy"
    assert snippet_path.exists()
    content = snippet_path.read_text(encoding="utf-8")
    assert "blog.example.com {" in content
    assert "reverse_proxy agblogger:8000" in content


def test_write_caddy_site_snippet_overwrites_existing(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()
    snippet_path = sites_dir / "blog.example.com.caddy"
    snippet_path.write_text("old content", encoding="utf-8")
    caddy_config = CaddyConfig(domain="blog.example.com", email=None)
    write_caddy_site_snippet(caddy_config, tmp_path)
    assert "old content" not in snippet_path.read_text(encoding="utf-8")
    assert "blog.example.com {" in snippet_path.read_text(encoding="utf-8")


def test_reload_shared_caddy_runs_docker_exec(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("cli.deploy_production.subprocess.run", fake_run)
    reload_shared_caddy()
    assert calls == [
        [
            "docker",
            "exec",
            SHARED_CADDY_CONTAINER_NAME,
            "caddy",
            "reload",
            "--config",
            "/etc/caddy/Caddyfile",
        ],
    ]


class TestReloadSharedCaddyFailure:
    """reload_shared_caddy should wrap subprocess errors in DeployError."""

    def test_raises_deploy_error_on_subprocess_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import subprocess as sp

        from cli.deploy_production import DeployError, reload_shared_caddy

        def fake_run(*_args, **kwargs):
            exc = sp.CalledProcessError(1, ["docker", "exec", "caddy", "caddy", "reload"])
            exc.stderr = "adapt: syntax error"
            raise exc

        monkeypatch.setattr("cli.deploy_production.subprocess.run", fake_run)

        with pytest.raises(DeployError, match="Failed to reload shared Caddy"):
            reload_shared_caddy()


# ── Task 13: write_config_files external Caddy mode ──────────────────


def test_write_config_files_external_caddy(tmp_path: Path) -> None:
    config = _make_config(
        caddy_mode=CADDY_MODE_EXTERNAL,
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
        shared_caddy_config=SharedCaddyConfig(caddy_dir=tmp_path / "caddy", acme_email=None),
    )
    write_config_files(config, tmp_path)
    assert (tmp_path / ".env.production").exists()
    assert (tmp_path / DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE).exists()
    assert not (tmp_path / "Caddyfile.production").exists()
    assert not (tmp_path / DEFAULT_NO_CADDY_COMPOSE_FILE).exists()
    assert not (tmp_path / DEFAULT_CADDY_PUBLIC_COMPOSE_FILE).exists()


# ── Task 14: write_bundle_files external Caddy mode ──────────────────


def test_write_bundle_files_external_caddy(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    config = _make_config(
        caddy_mode=CADDY_MODE_EXTERNAL,
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
        shared_caddy_config=SharedCaddyConfig(caddy_dir=tmp_path / "caddy", acme_email=None),
        deployment_mode=DEPLOY_MODE_REGISTRY,
        image_ref="ghcr.io/example/agblogger:1.0",
    )
    write_bundle_files(config, bundle_dir)
    assert (bundle_dir / (DEFAULT_IMAGE_EXTERNAL_CADDY_COMPOSE_FILE + ".generated")).exists()
    assert not (bundle_dir / (DEFAULT_IMAGE_COMPOSE_FILE + ".generated")).exists()
    assert not (bundle_dir / (DEFAULT_IMAGE_NO_CADDY_COMPOSE_FILE + ".generated")).exists()
    assert not (bundle_dir / "Caddyfile.production.generated").exists()


# ── Task 15: deploy with external Caddy bootstraps shared Caddy ───────


def test_deploy_external_caddy_local_bootstraps_and_writes_snippet(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    commands = _stub_subprocess(monkeypatch)
    _stub_no_trivy(monkeypatch)
    _stub_docker_inspect_missing(monkeypatch)
    caddy_dir = tmp_path / "shared-caddy"
    config = _make_config(
        caddy_mode=CADDY_MODE_EXTERNAL,
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
        shared_caddy_config=SharedCaddyConfig(caddy_dir=caddy_dir, acme_email="ops@example.com"),
    )
    monkeypatch.setattr("cli.deploy_production.reload_shared_caddy", lambda: None)
    result = deploy(config=config, project_dir=tmp_path)
    # Shared Caddy bootstrapped
    assert (caddy_dir / "sites").is_dir()
    assert (caddy_dir / "Caddyfile").exists()
    # Site snippet written
    assert (caddy_dir / "sites" / "blog.example.com.caddy").exists()
    # AgBlogger compose file written
    assert (tmp_path / DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE).exists()
    # Lifecycle commands use external caddy compose
    assert DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE in result.commands["start"]
    _ = commands


def test_deploy_external_caddy_local_replaces_proxy_subnet_placeholder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    _stub_subprocess(monkeypatch)
    _stub_no_trivy(monkeypatch)
    _stub_docker_inspect_missing(monkeypatch)
    monkeypatch.setattr("cli.deploy_production.reload_shared_caddy", lambda: None)
    monkeypatch.setattr(
        "cli.deploy_production._detect_external_caddy_subnet",
        lambda _project_dir: "172.31.0.0/16",
    )

    config = _make_config(
        caddy_mode=CADDY_MODE_EXTERNAL,
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
        trusted_proxy_ips=[CADDY_NETWORK_SUBNET_PLACEHOLDER, "10.0.0.0/8"],
        shared_caddy_config=SharedCaddyConfig(
            caddy_dir=tmp_path / "shared-caddy",
            acme_email="ops@example.com",
        ),
    )

    deploy(config=config, project_dir=tmp_path)

    env_content = (tmp_path / DEFAULT_ENV_FILE).read_text(encoding="utf-8")
    assert CADDY_NETWORK_SUBNET_PLACEHOLDER not in env_content
    assert 'TRUSTED_PROXY_IPS=["172.31.0.0/16","10.0.0.0/8"]' in env_content


# ── Task 19: _wait_for_healthy skips bundled caddy in external mode ───


def test_wait_for_healthy_skips_caddy_check_in_external_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """In external Caddy mode, _wait_for_healthy should only check agblogger, not caddy."""
    from cli.deploy_production import _wait_for_healthy

    config = _make_config(
        caddy_mode=CADDY_MODE_EXTERNAL,
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
        shared_caddy_config=SharedCaddyConfig(caddy_dir=Path("/opt/caddy"), acme_email=None),
    )
    call_count = 0

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        nonlocal call_count
        call_count += 1
        if "ps" in command:
            return SimpleNamespace(
                returncode=0,
                stdout="agblogger: Up (healthy)\n",
            )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("cli.deploy_production.subprocess.run", fake_run)
    monkeypatch.setattr("cli.deploy_production.time.sleep", lambda _: None)

    # Should NOT raise even though there's no caddy container in output
    _wait_for_healthy(config, tmp_path, timeout=10, interval=1)


# ── Task 21: end-to-end deploy with external Caddy ────────────────────


def test_deploy_external_caddy_full_flow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Full local deploy with external Caddy: bootstrap, snippet, compose, start."""
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    commands = _stub_subprocess(monkeypatch)
    _stub_no_trivy(monkeypatch)
    _stub_docker_inspect_missing(monkeypatch)
    monkeypatch.setattr("cli.deploy_production.reload_shared_caddy", lambda: None)

    caddy_dir = tmp_path / "shared-caddy"
    config = DeployConfig(
        secret_key="x" * 64,
        admin_username="admin",
        admin_password="very-strong-password",
        trusted_hosts=["blog.example.com"],
        trusted_proxy_ips=[],
        host_port=8000,
        host_bind_ip=LOCALHOST_BIND_IP,
        caddy_config=CaddyConfig(domain="blog.example.com", email="ops@example.com"),
        caddy_public=False,
        expose_docs=False,
        deployment_mode=DEPLOY_MODE_LOCAL,
        image_ref=None,
        bundle_dir=DEFAULT_BUNDLE_DIR,
        tarball_filename=DEFAULT_IMAGE_TARBALL,
        caddy_mode=CADDY_MODE_EXTERNAL,
        shared_caddy_config=SharedCaddyConfig(
            caddy_dir=caddy_dir,
            acme_email="ops@example.com",
        ),
    )

    result = deploy(config=config, project_dir=tmp_path)

    # Shared Caddy bootstrapped
    assert (caddy_dir / "sites").is_dir()
    caddyfile = (caddy_dir / "Caddyfile").read_text("utf-8")
    assert "import /etc/caddy/sites/*.caddy" in caddyfile
    assert "email ops@example.com" in caddyfile

    # Site snippet written
    snippet = (caddy_dir / "sites" / "blog.example.com.caddy").read_text("utf-8")
    assert "blog.example.com {" in snippet
    assert "reverse_proxy agblogger:8000" in snippet

    # AgBlogger compose file written (external caddy variant)
    assert (tmp_path / DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE).exists()
    compose = (tmp_path / DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE).read_text("utf-8")
    assert "external: true" in compose

    # No bundled Caddy files
    assert not (tmp_path / "Caddyfile.production").exists()
    assert not (tmp_path / DEFAULT_CADDY_PUBLIC_COMPOSE_FILE).exists()

    # Lifecycle commands reference external caddy compose
    assert DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE in result.commands["start"]

    # Docker commands: shared caddy bootstrap + agblogger compose up
    run_calls = [(cmd, cwd) for cmd, cwd, _ in commands if cmd[:3] == ["docker", "run", "-d"]]
    compose_up_calls = [(cmd, cwd) for cmd, cwd, _ in commands if "compose" in cmd and "up" in cmd]
    assert len(run_calls) == 1
    assert run_calls[0][1] == caddy_dir
    assert len(compose_up_calls) == 1  # agblogger only


# ── Base docker-compose.yml ADMIN_DISPLAY_NAME ───────────────────────


class TestBaseComposeAdminDisplayName:
    def test_base_compose_includes_admin_display_name(self) -> None:
        compose_path = Path(__file__).resolve().parent.parent.parent / "docker-compose.yml"
        content = compose_path.read_text(encoding="utf-8")
        assert "ADMIN_DISPLAY_NAME" in content

    def test_base_compose_includes_goatcounter_site_host_env(self) -> None:
        compose_path = Path(__file__).resolve().parent.parent.parent / "docker-compose.yml"
        content = compose_path.read_text(encoding="utf-8")
        assert "GOATCOUNTER_SITE_HOST=${GOATCOUNTER_SITE_HOST:-stats.internal}" in content

    def test_base_compose_includes_analytics_enabled_default_env(self) -> None:
        compose_path = Path(__file__).resolve().parent.parent.parent / "docker-compose.yml"
        content = compose_path.read_text(encoding="utf-8")
        assert "ANALYTICS_ENABLED_DEFAULT=${ANALYTICS_ENABLED_DEFAULT:-true}" in content


# ── config_from_args: --caddy-external without --caddy-domain ────────


def test_config_from_args_raises_on_caddy_external_without_domain() -> None:
    args = argparse.Namespace(
        secret_key="x" * 64,
        admin_username="admin",
        admin_password="password1234",
        admin_display_name="Admin",
        caddy_domain=None,
        caddy_email=None,
        caddy_public=False,
        caddy_external=True,
        shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
        shared_caddy_email=None,
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
        skip_scan=False,
        max_content_size=None,
        disable_password_change=False,
    )
    with pytest.raises(DeployError, match="--caddy-external requires --caddy-domain"):
        config_from_args(args)


# ── write_config_files: content directory seeding ────────────────────


def test_write_config_files_creates_content_directory(tmp_path: Path) -> None:
    config = _make_config()
    write_config_files(config, tmp_path)
    assert (tmp_path / "content").is_dir()


# ── config_from_args: external Caddy proxy subnet placeholder ────────


def test_config_from_args_external_caddy_uses_placeholder_not_compose_subnet() -> None:
    args = argparse.Namespace(
        secret_key="x" * 64,
        admin_username="admin",
        admin_password="password1234",
        admin_display_name="Admin",
        caddy_domain="blog.example.com",
        caddy_email="admin@example.com",
        caddy_public=False,
        caddy_external=True,
        shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
        shared_caddy_email=None,
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
        skip_scan=False,
        max_content_size=None,
        disable_password_change=False,
    )
    config = config_from_args(args)
    assert CADDY_NETWORK_SUBNET_PLACEHOLDER in config.trusted_proxy_ips
    assert COMPOSE_SUBNET not in config.trusted_proxy_ips


class TestBuildSetupScript:
    def test_tarball_no_caddy_loads_image_and_starts(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        assert script.startswith("#!/usr/bin/env bash")
        assert "set -euo pipefail" in script
        # Preflight
        assert "docker info" in script
        # Load image
        assert "docker load -i" in script
        assert DEFAULT_IMAGE_TARBALL in script
        # Start
        assert "docker compose" in script
        assert "up -d" in script
        # Health check
        assert "docker inspect" in script
        assert '"healthy"' in script
        # No Caddy bootstrapping
        assert "caddy reload" not in script

    def test_registry_no_caddy_pulls_image(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        assert "pull" in script
        assert "docker load" not in script
        assert "caddy reload" not in script

    def test_tarball_bundled_caddy_has_no_caddy_bootstrap(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="admin@example.com"),
            caddy_mode=CADDY_MODE_BUNDLED,
            caddy_public=True,
        )
        script = build_setup_script_content(config)
        assert "docker load -i" in script
        # Bundled Caddy starts via compose, no separate bootstrap
        assert "/opt/caddy" not in script
        assert "caddy reload" not in script

    def test_bundled_caddy_waits_for_caddy_service_before_success(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="admin@example.com"),
            caddy_mode=CADDY_MODE_BUNDLED,
            caddy_public=True,
        )
        script = build_setup_script_content(config)
        assert "CADDY_ID=$(" in script
        assert ".State.Status" in script
        # Detects exited/dead Caddy and reports a specific error
        assert "Caddy container failed" in script
        assert "caddy container not found yet" in script

    def test_external_caddy_bootstraps_shared_caddy(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="admin@example.com"),
            caddy_mode=CADDY_MODE_EXTERNAL,
            shared_caddy_config=SharedCaddyConfig(
                caddy_dir=Path("/opt/caddy"),
                acme_email="admin@example.com",
            ),
        )
        script = build_setup_script_content(config)
        # Directory creation
        assert "mkdir -p" in script
        assert "CADDY_DIR='/opt/caddy'" in script
        assert 'mkdir -p "$CADDY_DIR/sites"' in script

    def test_external_caddy_tilde_path_uses_home_variable(self) -> None:
        """Tilde in caddy_dir must resolve to remote $HOME, not local home."""
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="admin@example.com"),
            caddy_mode=CADDY_MODE_EXTERNAL,
            shared_caddy_config=SharedCaddyConfig(
                caddy_dir=Path("~/.local/share/caddy"),
                acme_email=None,
            ),
        )
        script = build_setup_script_content(config)
        lines = script.split("\n")
        # The CADDY_DIR= assignment line must use $HOME (double-quoted) for remote expansion
        assert any(line == 'CADDY_DIR="$HOME/.local/share/caddy"' for line in lines)
        # Must NOT embed the local machine's expanded home path in CADDY_DIR= assignment
        import os

        local_home = os.path.expanduser("~")
        assert not any(line.startswith(f"CADDY_DIR='{local_home}") for line in lines)
        # Shared Caddyfile heredoc
        assert "import /etc/caddy/sites/*.caddy" in script
        # Shared compose heredoc
        assert "image: caddy:2" in script
        # Network creation
        assert "docker network create" in script
        assert EXTERNAL_CADDY_NETWORK_NAME in script
        # Start shared Caddy without depending on compose file discovery
        assert "docker run -d" in script
        assert f"--name {SHARED_CADDY_CONTAINER_NAME}" in script
        assert "-p 443:443/udp" in script
        assert "docker compose up -d" not in script
        # Subnet detection
        assert "docker network inspect" in script
        assert CADDY_NETWORK_SUBNET_PLACEHOLDER in script
        # Site snippet
        assert "blog.example.com" in script
        assert "reverse_proxy agblogger:8000" in script
        # Caddy reload
        assert "caddy reload" in script

    def test_external_caddy_detects_single_subnet_from_network(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="admin@example.com"),
            caddy_mode=CADDY_MODE_EXTERNAL,
            shared_caddy_config=SharedCaddyConfig(
                caddy_dir=Path("/opt/caddy"),
                acme_email="admin@example.com",
            ),
        )
        script = build_setup_script_content(config)
        assert "index .IPAM.Config 0" in script
        assert "range .IPAM.Config" not in script
        assert (
            "docker network inspect caddy "
            '--format "{{with index .IPAM.Config 0}}{{.Subnet}}{{end}}"'
        ) in script
        assert "{{{{with index .IPAM.Config 0}}" not in script

    def test_external_caddy_uses_custom_caddy_dir(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email=None),
            caddy_mode=CADDY_MODE_EXTERNAL,
            shared_caddy_config=SharedCaddyConfig(
                caddy_dir=Path("/srv/caddy"),
                acme_email=None,
            ),
        )
        script = build_setup_script_content(config)
        assert "/srv/caddy" in script
        assert "/opt/caddy" not in script

    def test_preflight_checks_docker_compose_v2(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        assert "docker compose version" in script

    def test_backs_up_env_production(self) -> None:
        """Old unconditional env backup is replaced by per-file conditional backup."""
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        assert "cp .env.production .env.production.bak" not in script

    def test_displays_version_on_fresh_install(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        assert "Installing AgBlogger" in script
        assert "Upgrading AgBlogger" in script

    def test_external_caddy_reload_failure_exits(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="admin@example.com"),
            caddy_mode=CADDY_MODE_EXTERNAL,
            shared_caddy_config=SharedCaddyConfig(
                caddy_dir=Path("/opt/caddy"),
                acme_email="admin@example.com",
            ),
        )
        script = build_setup_script_content(config)
        assert "if ! docker exec caddy caddy reload" in script

    def test_health_check_uses_docker_inspect(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        assert "docker inspect" in script
        assert ".State.Health.Status" in script

    def test_force_recreate_ensures_fresh_containers(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        assert "--force-recreate" in script

    def test_force_recreate_also_removes_orphans(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        assert "up -d --force-recreate --remove-orphans" in script

    def test_compose_failure_shows_diagnostics_immediately(self) -> None:
        """Compose failure triggers diagnostics without waiting for health timeout."""
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        # errexit is disabled around compose so failure doesn't kill the script
        assert "set +e" in script
        assert "COMPOSE_EXIT=$?" in script
        assert "set -e" in script
        # Diagnostics are called immediately on compose failure
        assert "show_diagnostics" in script

    def test_prunes_dangling_images_on_success(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        assert "docker image prune" in script

    def test_diagnostics_function_shows_container_info(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        assert "show_diagnostics() {" in script
        assert "AgBlogger container" in script
        assert "Manual health check probe" in script
        assert "docker exec" in script
        assert "wget -O -" in script
        assert "AgBlogger logs" in script
        assert "Full logs" in script

    def test_diagnostics_includes_caddy_state_when_bundled(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="a@b.com"),
            caddy_mode=CADDY_MODE_BUNDLED,
            caddy_public=True,
        )
        script = build_setup_script_content(config)
        assert "Caddy container" in script
        assert "Caddy logs" in script

    def test_external_caddy_uses_managed_block_helper_for_shared_files(self) -> None:
        """Shared root files refresh on every deploy via the managed-block helper.

        The previous behavior wrote them only on first install (``if [ ! -f ]``),
        so template fixes (e.g., enabling HTTP/3) never reached existing
        deployments. The helper replaces only the marker-delimited region, so
        operator customizations outside the markers survive across deploys.
        """
        from cli.deploy_production import (
            SHARED_MANAGED_BEGIN_MARKER,
            SHARED_MANAGED_END_MARKER,
        )

        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="admin@example.com"),
            caddy_mode=CADDY_MODE_EXTERNAL,
            shared_caddy_config=SharedCaddyConfig(
                caddy_dir=Path("/opt/caddy"),
                acme_email="admin@example.com",
            ),
        )
        script = build_setup_script_content(config)

        # Helper function defined exactly once and the markers are present.
        assert script.count("write_managed_block() {") == 1
        assert SHARED_MANAGED_BEGIN_MARKER in script
        assert SHARED_MANAGED_END_MARKER in script

        # Both shared files are written through the helper rather than via the
        # old ``if [ ! -f ... ]`` guard.
        assert 'write_managed_block "$CADDY_DIR/Caddyfile"' in script
        assert 'write_managed_block "$CADDY_DIR/docker-compose.yml"' in script
        assert 'if [ ! -f "$CADDY_DIR/Caddyfile" ]' not in script
        assert 'if [ ! -f "$CADDY_DIR/docker-compose.yml" ]' not in script


class TestSetupScriptFilePlacement:
    """File placement logic: .generated files moved into final positions."""

    def test_preflight_checks_for_generated_env_not_plain(self) -> None:
        """Old preflight exit-on-missing-.env.production replaced; new check covers .generated."""
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        # Old preflight that exits when only .env.production is missing must be gone
        assert "Error: .env.production not found" not in script, (
            "Old 'not found' preflight error must be removed"
        )
        # New check must reference both files and the .generated file
        assert ".env.production.generated" in script
        assert "Neither .env.production nor .env.production.generated found" in script

    def test_config_files_backed_up_and_moved(self) -> None:
        """Compose .generated files are backed up then moved into final position."""
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        # Default tarball+no-caddy uses docker-compose.image.nocaddy.yml
        f = "docker-compose.image.nocaddy.yml"
        assert f'cp "{f}" "{f}.bak"' in script
        assert f'mv "{f}.generated" "{f}"' in script

    def test_config_files_backed_up_and_moved_bundled_caddy(self) -> None:
        """Caddyfile.production is also backed up and moved in bundled caddy mode."""
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="a@b.com"),
            caddy_mode=CADDY_MODE_BUNDLED,
            caddy_public=True,
        )
        script = build_setup_script_content(config)
        assert 'cp "Caddyfile.production" "Caddyfile.production.bak"' in script
        assert 'mv "Caddyfile.production.generated" "Caddyfile.production"' in script

    def test_config_files_no_caddyfile_for_external_caddy(self) -> None:
        """External caddy mode does not back up or place Caddyfile.production."""
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="a@b.com"),
            caddy_mode=CADDY_MODE_EXTERNAL,
            shared_caddy_config=SharedCaddyConfig(
                caddy_dir=Path("/opt/caddy"),
                acme_email="a@b.com",
            ),
        )
        script = build_setup_script_content(config)
        # External caddy uses different compose file
        assert 'mv "docker-compose.image.external-caddy.yml.generated"' in script
        assert "Caddyfile.production.generated" not in script

    def test_env_production_seed_only_on_first_install(self) -> None:
        """On first install (no .env.production), the generated template is moved into place."""
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        assert "if [ ! -f .env.production ]" in script
        assert "mv .env.production.generated .env.production" in script
        assert "Created .env.production from generated template." in script

    def test_env_production_kept_on_upgrade(self) -> None:
        """On upgrade (existing .env.production), generated file is not applied automatically."""
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        assert "Existing .env.production found" in script
        assert "cp .env.production.generated .env.production" in script

    def test_env_production_upgrade_replaces_managed_analytics_defaults(self) -> None:
        """Upgrades should rewrite deployment-managed analytics keys from the template."""
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        managed_keys_loop = (
            "for key in ANALYTICS_ENABLED_DEFAULT GOATCOUNTER_SITE_HOST TRUSTED_PROXY_IPS; do"
        )
        assert managed_keys_loop in script
        assert 'if grep -q "^${key}=" .env.production.generated; then' in script
        assert 'sed -i "/^${key}=/d" .env.production' in script
        assert 'grep "^${key}=" .env.production.generated >> .env.production' in script

    def test_env_production_upgrade_replaces_trusted_proxy_ips(self) -> None:
        """Upgrades should refresh deployment-managed trusted proxy subnets from the template."""
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        managed_keys_loop = (
            "for key in ANALYTICS_ENABLED_DEFAULT GOATCOUNTER_SITE_HOST TRUSTED_PROXY_IPS; do"
        )
        assert managed_keys_loop in script

    def test_chmod_600_applied_in_both_branches(self) -> None:
        """chmod 600 must appear after mv (first install) AND after the upgrade message."""
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        lines = script.splitlines()

        # Find the if-branch mv line and the else-branch message line
        mv_idx = next(
            i
            for i, line in enumerate(lines)
            if "mv .env.production.generated .env.production" in line
        )
        upgrade_msg_idx = next(
            i for i, line in enumerate(lines) if "Existing .env.production found" in line
        )

        # chmod 600 must appear after each of those lines
        chmod_indices = [i for i, line in enumerate(lines) if "chmod 600 .env.production" in line]
        assert len(chmod_indices) >= 2, "Expected chmod 600 in both branches"
        assert any(idx > mv_idx for idx in chmod_indices), "chmod 600 must appear after mv"
        assert any(idx > upgrade_msg_idx for idx in chmod_indices), (
            "chmod 600 must appear after upgrade message"
        )

    def test_file_placement_before_image_load(self) -> None:
        """File placement section must appear before docker load / docker pull."""
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        lines = script.splitlines()

        placement_idx = next(
            i for i, line in enumerate(lines) if "mv .env.production.generated" in line
        )
        load_idx = next(i for i, line in enumerate(lines) if "docker load" in line)
        assert placement_idx < load_idx, "File placement must happen before docker load"

    def test_compose_commands_use_final_filenames(self) -> None:
        """docker compose up must use the final (non-.generated) compose filename."""
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        # Default tarball+no-caddy compose up uses the nocaddy file
        assert "-f docker-compose.image.nocaddy.yml" in script
        # .generated suffix must NOT appear in any compose up invocation
        lines = script.splitlines()
        compose_up_lines = [line for line in lines if "compose" in line and "up -d" in line]
        assert compose_up_lines, "Expected at least one compose up line"
        for line in compose_up_lines:
            assert ".generated" not in line, f"compose up must not reference .generated: {line}"


class TestRemoteReadmeSetupScript:
    """Remote README should reference setup.sh instead of manual steps."""

    def test_readme_references_setup_script(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        commands = build_lifecycle_commands(
            deployment_mode=config.deployment_mode,
            use_caddy=False,
            caddy_public=False,
            tarball_filename=config.tarball_filename,
        )
        readme = _build_remote_readme_content(config, commands)
        assert "setup.sh" in readme

    def test_readme_no_longer_has_manual_load_start_steps(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        commands = build_lifecycle_commands(
            deployment_mode=config.deployment_mode,
            use_caddy=False,
            caddy_public=False,
            tarball_filename=config.tarball_filename,
        )
        readme = _build_remote_readme_content(config, commands)
        assert "Load the image" not in readme
        assert "Start the services" not in readme
        assert "Pull the image" not in readme

    def test_readme_removes_shared_caddy_setup_section(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email=None),
            caddy_mode=CADDY_MODE_EXTERNAL,
            shared_caddy_config=SharedCaddyConfig(caddy_dir=Path("/opt/caddy"), acme_email=None),
        )
        commands = build_lifecycle_commands(
            deployment_mode=config.deployment_mode,
            use_caddy=False,
            caddy_public=False,
            tarball_filename=config.tarball_filename,
            caddy_mode=CADDY_MODE_EXTERNAL,
        )
        readme = _build_remote_readme_content(config, commands)
        assert "Shared Caddy Setup" not in readme
        assert "deployment script will bootstrap" not in readme

    def test_readme_includes_dns_notice_for_caddy(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email=None),
            caddy_mode=CADDY_MODE_BUNDLED,
        )
        commands = build_lifecycle_commands(
            deployment_mode=config.deployment_mode,
            use_caddy=True,
            caddy_public=False,
            tarball_filename=config.tarball_filename,
        )
        readme = _build_remote_readme_content(config, commands)
        assert "DNS" in readme

    def test_readme_omits_dns_notice_for_no_caddy(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        commands = build_lifecycle_commands(
            deployment_mode=config.deployment_mode,
            use_caddy=False,
            caddy_public=False,
            tarball_filename=config.tarball_filename,
        )
        readme = _build_remote_readme_content(config, commands)
        assert "DNS" not in readme

    def test_readme_upgrade_references_setup_script(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        commands = build_lifecycle_commands(
            deployment_mode=config.deployment_mode,
            use_caddy=False,
            caddy_public=False,
            tarball_filename=config.tarball_filename,
        )
        readme = _build_remote_readme_content(config, commands)
        upgrade_idx = readme.index("Upgrading")
        assert "setup.sh" in readme[upgrade_idx:]

    def test_readme_mentions_env_preserved(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        commands = build_lifecycle_commands(
            deployment_mode=config.deployment_mode,
            use_caddy=False,
            caddy_public=False,
            tarball_filename=config.tarball_filename,
        )
        readme = _build_remote_readme_content(config, commands)
        assert ".env.production" in readme
        assert "preserved" in readme.lower() or "never" in readme.lower()


class TestSetupScriptInBundle:
    def test_write_bundle_files_creates_executable_setup_script(self, tmp_path: Path) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        bundle_dir = tmp_path / "bundle"
        write_bundle_files(config, bundle_dir)
        setup_path = bundle_dir / DEFAULT_SETUP_SCRIPT
        assert setup_path.exists()
        assert setup_path.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash")
        # Check executable permission
        assert setup_path.stat().st_mode & 0o111 != 0


# ── Generated suffix for bundle config files ──────────────────────────


class TestGeneratedSuffix:
    """Bundle config files should be written with a .generated suffix."""

    def test_bundled_caddy_creates_generated_files(self, tmp_path: Path) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="admin@example.com"),
            caddy_mode=CADDY_MODE_BUNDLED,
            caddy_public=True,
        )
        bundle_dir = tmp_path / "bundle"
        write_bundle_files(config, bundle_dir)

        # .generated versions must exist
        assert (bundle_dir / DEFAULT_ENV_GENERATED_FILE).exists()
        assert (bundle_dir / (DEFAULT_IMAGE_COMPOSE_FILE + ".generated")).exists()
        assert (bundle_dir / (DEFAULT_CADDYFILE + ".generated")).exists()

        # Un-suffixed config files must NOT exist
        assert not (bundle_dir / DEFAULT_ENV_FILE).exists()
        assert not (bundle_dir / DEFAULT_IMAGE_COMPOSE_FILE).exists()
        assert not (bundle_dir / DEFAULT_CADDYFILE).exists()

    def test_external_caddy_creates_generated_files(self, tmp_path: Path) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_mode=CADDY_MODE_EXTERNAL,
            caddy_config=CaddyConfig(domain="blog.example.com", email=None),
            host_bind_ip=LOCALHOST_BIND_IP,
            shared_caddy_config=SharedCaddyConfig(caddy_dir=tmp_path / "caddy", acme_email=None),
        )
        bundle_dir = tmp_path / "bundle"
        write_bundle_files(config, bundle_dir)

        assert (bundle_dir / DEFAULT_ENV_GENERATED_FILE).exists()
        assert (bundle_dir / (DEFAULT_IMAGE_EXTERNAL_CADDY_COMPOSE_FILE + ".generated")).exists()

        assert not (bundle_dir / DEFAULT_ENV_FILE).exists()
        assert not (bundle_dir / DEFAULT_IMAGE_EXTERNAL_CADDY_COMPOSE_FILE).exists()

    def test_no_caddy_creates_generated_files(self, tmp_path: Path) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        bundle_dir = tmp_path / "bundle"
        write_bundle_files(config, bundle_dir)

        assert (bundle_dir / DEFAULT_ENV_GENERATED_FILE).exists()
        assert (bundle_dir / (DEFAULT_IMAGE_NO_CADDY_COMPOSE_FILE + ".generated")).exists()

        assert not (bundle_dir / DEFAULT_ENV_FILE).exists()
        assert not (bundle_dir / DEFAULT_IMAGE_NO_CADDY_COMPOSE_FILE).exists()

    def test_env_generated_has_restrictive_permissions(self, tmp_path: Path) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        bundle_dir = tmp_path / "bundle"
        write_bundle_files(config, bundle_dir)

        env_path = bundle_dir / DEFAULT_ENV_GENERATED_FILE
        assert env_path.exists()
        assert env_path.stat().st_mode & 0o777 == 0o600

    def test_non_config_files_have_no_generated_suffix(self, tmp_path: Path) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="a@example.com"),
            caddy_mode=CADDY_MODE_BUNDLED,
            caddy_public=True,
        )
        bundle_dir = tmp_path / "bundle"
        write_bundle_files(config, bundle_dir)

        # These should keep their original names (no .generated suffix)
        assert (bundle_dir / DEFAULT_SETUP_SCRIPT).exists()
        assert (bundle_dir / DEFAULT_REMOTE_README).exists()
        assert (bundle_dir / "VERSION").exists()
        assert (bundle_dir / "content").is_dir()

        # Make sure .generated versions of non-config files do NOT exist
        assert not (bundle_dir / (DEFAULT_SETUP_SCRIPT + ".generated")).exists()
        assert not (bundle_dir / (DEFAULT_REMOTE_README + ".generated")).exists()
        assert not (bundle_dir / "VERSION.generated").exists()


# ── Old-stack teardown via .last-teardown marker ──────────────────────


class TestSetupScriptTeardown:
    """setup.sh detects Caddy mode changes and tears down the old stack."""

    def _nocaddy_config(self) -> DeployConfig:
        return _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )

    def _bundled_config(self) -> DeployConfig:
        return _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="a@b.com"),
            caddy_mode=CADDY_MODE_BUNDLED,
        )

    def _external_config(self) -> DeployConfig:
        return _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="a@b.com"),
            caddy_mode=CADDY_MODE_EXTERNAL,
            shared_caddy_config=SharedCaddyConfig(
                caddy_dir=Path("/opt/caddy"),
                acme_email="a@b.com",
            ),
        )

    def test_writes_last_teardown_marker_on_success(self) -> None:
        """After 'All services healthy', .last-teardown is written with compose flags."""
        script = build_setup_script_content(self._nocaddy_config())
        lines = script.splitlines()

        healthy_idx = next(i for i, ln in enumerate(lines) if "All services healthy" in ln)
        marker_write_indices = [
            i for i, ln in enumerate(lines) if ".last-teardown" in ln and ">" in ln
        ]
        assert marker_write_indices, "Expected a write to .last-teardown"
        assert any(idx > healthy_idx for idx in marker_write_indices), (
            ".last-teardown must be written after 'All services healthy'"
        )

    def test_reads_and_compares_last_teardown(self) -> None:
        """The script checks for the .last-teardown file and compares flags."""
        script = build_setup_script_content(self._nocaddy_config())
        assert "if [ -f .last-teardown ]" in script
        assert "OLD_COMPOSE_FLAGS" in script
        assert "CURRENT_COMPOSE_FLAGS" in script

    def test_tears_down_old_stack_on_mode_change(self) -> None:
        """When flags differ, teardown runs docker compose ... down using .bak files."""
        script = build_setup_script_content(self._nocaddy_config())
        # Teardown builds command with .bak files and runs down.
        assert "${flag}.bak" in script
        assert "$OLD_TEARDOWN_CMD down" in script
        # Exit code is captured and reported — not silently suppressed.
        assert "$OLD_TEARDOWN_CMD down || true" not in script
        assert "TEARDOWN_EXIT" in script

    def test_skips_teardown_when_flags_match(self) -> None:
        """When CURRENT_COMPOSE_FLAGS equals OLD_COMPOSE_FLAGS, teardown is skipped."""
        script = build_setup_script_content(self._nocaddy_config())
        # The comparison logic must be present
        assert "CURRENT_COMPOSE_FLAGS" in script
        assert '"$OLD_COMPOSE_FLAGS" != "$CURRENT_COMPOSE_FLAGS"' in script

    def test_no_teardown_on_first_install(self) -> None:
        """Teardown is guarded by marker file existence — safe on first install."""
        script = build_setup_script_content(self._nocaddy_config())
        # The entire teardown block is inside the if-file-exists guard
        lines = script.splitlines()
        marker_check_idx = next(
            (i for i, ln in enumerate(lines) if "if [ -f .last-teardown ]" in ln), None
        )
        assert marker_check_idx is not None, "Expected 'if [ -f .last-teardown ]' guard"

    def test_skips_teardown_with_warning_when_bak_missing(self) -> None:
        """If a .bak file is missing, a warning is printed and teardown is skipped."""
        script = build_setup_script_content(self._nocaddy_config())
        assert "TEARDOWN_OK" in script
        # Warning message when .bak not found
        assert ".bak not found" in script or "cannot tear down old stack" in script

    def test_marker_contains_compose_flags_nocaddy(self) -> None:
        """The .last-teardown marker write uses the correct compose filename (no-caddy mode)."""
        script = build_setup_script_content(self._nocaddy_config())
        lines = script.splitlines()
        # CURRENT_COMPOSE_FLAGS must be set to the no-caddy compose filename
        flag_lines = [ln for ln in lines if "CURRENT_COMPOSE_FLAGS=" in ln]
        assert flag_lines, "Expected CURRENT_COMPOSE_FLAGS assignment"
        assert any(DEFAULT_IMAGE_NO_CADDY_COMPOSE_FILE in ln for ln in flag_lines), (
            f"CURRENT_COMPOSE_FLAGS must contain {DEFAULT_IMAGE_NO_CADDY_COMPOSE_FILE}"
        )

    def test_marker_contains_compose_flags_bundled(self) -> None:
        """The .last-teardown marker write uses the correct compose filename (bundled caddy)."""
        script = build_setup_script_content(self._bundled_config())
        lines = script.splitlines()
        flag_lines = [ln for ln in lines if "CURRENT_COMPOSE_FLAGS=" in ln]
        assert flag_lines, "Expected CURRENT_COMPOSE_FLAGS assignment"
        assert any(DEFAULT_IMAGE_COMPOSE_FILE in ln for ln in flag_lines), (
            f"CURRENT_COMPOSE_FLAGS must contain {DEFAULT_IMAGE_COMPOSE_FILE}"
        )

    def test_marker_contains_compose_flags_external(self) -> None:
        """The .last-teardown marker write uses the correct compose filename (external caddy)."""
        script = build_setup_script_content(self._external_config())
        lines = script.splitlines()
        flag_lines = [ln for ln in lines if "CURRENT_COMPOSE_FLAGS=" in ln]
        assert flag_lines, "Expected CURRENT_COMPOSE_FLAGS assignment"
        assert any(DEFAULT_IMAGE_EXTERNAL_CADDY_COMPOSE_FILE in ln for ln in flag_lines), (
            f"CURRENT_COMPOSE_FLAGS must contain {DEFAULT_IMAGE_EXTERNAL_CADDY_COMPOSE_FILE}"
        )

    def test_teardown_section_before_version_info(self) -> None:
        """Teardown section must appear after file placement but before version info."""
        script = build_setup_script_content(self._nocaddy_config())
        lines = script.splitlines()

        placement_idx = next((i for i, ln in enumerate(lines) if "File placement" in ln), None)
        teardown_idx = next(
            (i for i, ln in enumerate(lines) if "Stack teardown" in ln or "last-teardown" in ln),
            None,
        )
        version_idx = next((i for i, ln in enumerate(lines) if "Version info" in ln), None)
        assert placement_idx is not None
        assert teardown_idx is not None
        assert version_idx is not None
        assert placement_idx < teardown_idx < version_idx, (
            "Teardown section must be between file placement and version info"
        )


class TestSetupScriptDualSubnetPatch:
    def _external_config(self) -> DeployConfig:
        return _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="admin@example.com"),
            caddy_mode=CADDY_MODE_EXTERNAL,
            shared_caddy_config=SharedCaddyConfig(
                caddy_dir=Path("/opt/caddy"),
                acme_email="admin@example.com",
            ),
            trusted_proxy_ips=[CADDY_NETWORK_SUBNET_PLACEHOLDER],
        )

    def test_patches_env_production(self) -> None:
        script = build_setup_script_content(self._external_config())
        assert (
            f'sed -i "s|{CADDY_NETWORK_SUBNET_PLACEHOLDER}|$CADDY_SUBNET|" .env.production'
            in script
        )

    def test_patches_env_generated_with_existence_guard(self) -> None:
        script = build_setup_script_content(self._external_config())
        assert (
            f'sed -i "s|{CADDY_NETWORK_SUBNET_PLACEHOLDER}|$CADDY_SUBNET|"'
            " .env.production.generated" in script
        )
        assert "if [ -f .env.production.generated ]" in script

    def test_no_subnet_patch_for_bundled_mode(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="admin@example.com"),
            caddy_mode=CADDY_MODE_BUNDLED,
            caddy_public=True,
        )
        script = build_setup_script_content(config)
        assert CADDY_NETWORK_SUBNET_PLACEHOLDER not in script


class TestLocalBackupGuard:
    def test_no_backup_files_created_for_remote_bundle(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Remote bundle generation should NOT create .bak files in project root."""
        (tmp_path / DEFAULT_ENV_FILE).write_text("old", encoding="utf-8")
        (tmp_path / DEFAULT_CADDYFILE).write_text("old", encoding="utf-8")
        _stub_subprocess(monkeypatch)
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="admin@example.com"),
            caddy_mode=CADDY_MODE_BUNDLED,
            caddy_public=True,
        )
        deploy(config, tmp_path)
        bak_files = list(tmp_path.glob("*.bak"))
        assert not bak_files, f"Unexpected .bak files in project root: {bak_files}"

    def test_no_backup_files_created_in_bundle_dir(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Bundle dir should NOT have .bak files."""
        bundle_dir = tmp_path / DEFAULT_BUNDLE_DIR
        bundle_dir.mkdir(parents=True)
        (bundle_dir / DEFAULT_ENV_FILE).write_text("old", encoding="utf-8")
        _stub_subprocess(monkeypatch)
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        deploy(config, tmp_path)
        bak_files = list(bundle_dir.glob("*.bak"))
        assert not bak_files, f"Unexpected .bak files in bundle dir: {bak_files}"


class TestStaleGeneratedCleanup:
    def test_cleans_stale_generated_files_from_other_modes(self, tmp_path: Path) -> None:
        """Switching from bundled to no-caddy should clean bundled .generated files."""
        (tmp_path / "docker-compose.image.yml.generated").write_text("old", encoding="utf-8")
        (tmp_path / "Caddyfile.production.generated").write_text("old", encoding="utf-8")
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        write_bundle_files(config, tmp_path)
        assert not (tmp_path / "docker-compose.image.yml.generated").exists()
        assert not (tmp_path / "Caddyfile.production.generated").exists()
        assert (tmp_path / "docker-compose.image.nocaddy.yml.generated").exists()

    def test_cleans_old_unsuffixed_files_on_transition(self, tmp_path: Path) -> None:
        """First .generated bundle should clean up old un-suffixed files."""
        (tmp_path / ".env.production").write_text("old", encoding="utf-8")
        (tmp_path / "docker-compose.image.yml").write_text("old", encoding="utf-8")
        (tmp_path / "Caddyfile.production").write_text("old", encoding="utf-8")
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        write_bundle_files(config, tmp_path)
        assert not (tmp_path / ".env.production").exists()
        assert not (tmp_path / "docker-compose.image.yml").exists()
        assert not (tmp_path / "Caddyfile.production").exists()


class TestReadmeRedesign:
    def _readme(self) -> str:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        commands = build_lifecycle_commands(
            deployment_mode=config.deployment_mode,
            use_caddy=False,
            caddy_public=False,
            caddy_mode=config.caddy_mode,
        )
        return _build_remote_readme_content(config, commands)

    def test_upgrade_no_longer_excludes_env_production(self) -> None:
        readme = self._readme()
        assert "except" not in readme.lower() or ".env.production" not in readme.split("except")[1]
        assert "copy all files" in readme.lower()

    def test_upgrade_mentions_env_preserved(self) -> None:
        readme = self._readme()
        # Find lines that mention .env.production and check for preservation language.
        # Use replace() to strip .env.production.generated occurrences so we only match
        # lines that reference the plain .env.production file.
        env_lines = [
            line
            for line in readme.splitlines()
            if ".env.production" in line.replace(".env.production.generated", "")
        ]
        assert any(
            "preserved" in line.lower() or "automatically" in line.lower() for line in env_lines
        )

    def test_upgrade_mentions_generated_reference(self) -> None:
        readme = self._readme()
        assert ".env.production.generated" in readme

    def test_rollback_no_longer_references_env_bak(self) -> None:
        readme = self._readme()
        assert "## Rollback" in readme
        assert ".bak" in readme
        assert ".env.production.bak" not in readme

    def test_upgrade_mentions_caddy_mode_switch(self) -> None:
        readme = self._readme()
        assert "caddy mode" in readme.lower()
        assert "tears down" in readme.lower() or "torn down" in readme.lower()

    def test_no_longer_mentions_manual_env_backup(self) -> None:
        readme = self._readme()
        assert "backs up .env.production" not in readme.lower()


# ── _bash_quote ───────────────────────────────────────────────────────


def test_bash_quote_plain_string() -> None:
    """Plain strings are wrapped in single quotes."""
    assert _bash_quote("hello") == "'hello'"


def test_bash_quote_empty_string() -> None:
    """Empty string is represented as two single quotes."""
    assert _bash_quote("") == "''"


def test_bash_quote_string_with_spaces() -> None:
    """Strings with spaces are safely quoted."""
    result = _bash_quote("hello world")
    assert result == "'hello world'"


def test_bash_quote_string_with_single_quote() -> None:
    """Embedded single quotes are escaped correctly."""
    result = _bash_quote("it's")
    # The standard technique: end quote, escaped quote, reopen quote
    assert result == "'it'\\''s'"


def test_bash_quote_string_with_double_quotes() -> None:
    """Double quotes need no special treatment inside single-quoted strings."""
    result = _bash_quote('say "hello"')
    assert result == "'say \"hello\"'"


def test_bash_quote_string_with_backslash() -> None:
    """Backslashes are treated literally inside single-quoted strings."""
    result = _bash_quote("a\\b")
    assert result == "'a\\b'"


def test_bash_quote_string_with_dollar_sign() -> None:
    """Dollar signs are not interpreted inside single-quoted strings."""
    result = _bash_quote("$HOME")
    assert result == "'$HOME'"


def test_bash_quote_string_with_multiple_single_quotes() -> None:
    """Multiple embedded single quotes are all escaped."""
    result = _bash_quote("a'b'c")
    assert result == "'a'\\''b'\\''c'"


@given(st.text())
@settings(max_examples=500, suppress_health_check=[HealthCheck.too_slow])
def test_bash_quote_property_starts_and_ends_with_single_quote(value: str) -> None:
    """The output always starts and ends with a single quote."""
    result = _bash_quote(value)
    assert result.startswith("'")
    assert result.endswith("'")


@given(st.text())
@settings(max_examples=500, suppress_health_check=[HealthCheck.too_slow])
def test_bash_quote_property_no_unescaped_single_quotes_in_body(value: str) -> None:
    """Any single quote in the input is escaped as '\\'' in the output."""
    result = _bash_quote(value)
    # Strip the outer quotes; remaining bare single quotes would be unsafe.
    inner = result[1:-1]
    # After removing all escaped-quote sequences, no lone single quote should remain.
    sanitised = inner.replace("'\\''", "")
    assert "'" not in sanitised


# ── scan_image: trivy report write failure ────────────────────────────


def test_scan_image_prints_summary_even_when_report_write_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Vulnerability summary is always printed even if the report file cannot be written."""
    import json

    trivy_output = {
        "Results": [
            {
                "Target": "usr/local/bin/uv (rustbinary)",
                "Type": "rustbinary",
                "Vulnerabilities": [
                    {
                        "VulnerabilityID": "CVE-2026-11111",
                        "PkgName": "badcrate",
                        "InstalledVersion": "0.1.0",
                        "FixedVersion": "",
                        "Severity": "CRITICAL",
                        "Title": "Critical bug",
                    },
                ],
            },
        ],
    }

    monkeypatch.setattr(
        "cli.deploy_production.subprocess.run",
        lambda *_a, **_kw: SimpleNamespace(
            returncode=1,
            stdout=json.dumps(trivy_output).encode(),
            stderr=b"",
        ),
    )

    # Make the report directory read-only so write_text raises OSError.
    tmp_path.chmod(0o555)
    try:
        findings = scan_image(tmp_path, "img:test")
    finally:
        tmp_path.chmod(0o755)

    # Results are still returned.
    assert len(findings) == 1
    assert findings[0]["id"] == "CVE-2026-11111"

    captured = capsys.readouterr()
    # Summary is always printed to stderr.
    assert "CVE-2026-11111" in captured.err
    assert "1 vulnerability" in captured.err
    # A warning about the failed write is shown.
    assert "trivy-report.json" in captured.err


def test_scan_image_warns_when_report_write_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A clear warning is printed when the trivy report cannot be saved to disk."""
    import json

    trivy_output = {
        "Results": [
            {
                "Target": "some/binary",
                "Type": "gobinary",
                "Vulnerabilities": [
                    {
                        "VulnerabilityID": "CVE-2026-22222",
                        "PkgName": "pkg",
                        "InstalledVersion": "1.0.0",
                        "FixedVersion": "1.0.1",
                        "Severity": "HIGH",
                        "Title": "Another bug",
                    },
                ],
            },
        ],
    }

    monkeypatch.setattr(
        "cli.deploy_production.subprocess.run",
        lambda *_a, **_kw: SimpleNamespace(
            returncode=1,
            stdout=json.dumps(trivy_output).encode(),
            stderr=b"",
        ),
    )

    # Use a read-only directory to trigger a real OSError on file write.
    report_dir = tmp_path / "readonly"
    report_dir.mkdir()
    report_dir.chmod(0o555)
    try:
        findings = scan_image(report_dir, "img:test")
    finally:
        report_dir.chmod(0o755)

    assert len(findings) == 1
    captured = capsys.readouterr()
    # Warning about failed save.
    assert "warning" in captured.err.lower()
    assert "trivy-report.json" in captured.err


# ── build_setup_script_content: teardown exit code ────────────────────


def test_setup_script_teardown_does_not_suppress_errors_with_or_true() -> None:
    """The generated setup.sh must not use '|| true' to silently swallow teardown failures."""
    config = _make_config(caddy_mode=CADDY_MODE_NONE)
    script = build_setup_script_content(config)

    # '|| true' on the teardown command hides failures — it must not appear.
    assert "$OLD_TEARDOWN_CMD down || true" not in script
    # Exit code capture must be present instead.
    assert "TEARDOWN_EXIT" in script


def test_setup_script_teardown_warns_on_failure() -> None:
    """The generated setup.sh emits a warning when teardown exits with non-zero."""
    config = _make_config(caddy_mode=CADDY_MODE_BUNDLED)
    script = build_setup_script_content(config)

    # Exit code is captured.
    assert "TEARDOWN_EXIT=$?" in script
    # Non-zero exit is checked.
    assert '"$TEARDOWN_EXIT" -ne 0' in script
    # A warning is emitted to stderr.
    assert ">&2" in script
    assert "Warning:" in script


# ── GoatCounter integration in compose builders ───────────────────────


def test_build_direct_compose_includes_goatcounter_service() -> None:
    content = build_direct_compose_content()
    assert "goatcounter:" in content
    assert "arp242/goatcounter:latest" in content
    assert "user: root" in content
    assert "goatcounter-db:/data/goatcounter" in content
    assert "goatcounter-token:/data/goatcounter-token:ro" in content


def test_build_image_compose_includes_goatcounter_service() -> None:
    content = build_image_compose_content()
    assert "goatcounter:" in content
    assert "arp242/goatcounter:latest" in content
    assert "user: root" in content
    assert "goatcounter-db:/data/goatcounter" in content
    assert "goatcounter-token:/data/goatcounter-token:ro" in content
    assert GOATCOUNTER_STATIC_IP in content


def test_build_image_direct_compose_includes_goatcounter_service() -> None:
    content = build_image_direct_compose_content()
    assert "goatcounter:" in content
    assert "user: root" in content
    assert "goatcounter-db:/data/goatcounter" in content
    assert "goatcounter-token:/data/goatcounter-token:ro" in content


def test_build_direct_compose_can_disable_goatcounter_service() -> None:
    content = build_direct_compose_content(deploy_goatcounter=False)

    assert "goatcounter:" not in content
    assert "goatcounter-db:/data/goatcounter" not in content
    assert "goatcounter-token:/data/goatcounter-token:ro" not in content


def test_build_image_compose_can_disable_goatcounter_service() -> None:
    content = build_image_compose_content(deploy_goatcounter=False)

    assert "goatcounter:" not in content
    assert "goatcounter-db:/data/goatcounter" not in content
    assert "goatcounter-token:/data/goatcounter-token:ro" not in content


def test_goatcounter_env_uses_generated_site_host() -> None:
    content = build_image_compose_content()

    assert "GOATCOUNTER_SITE_HOST=${GOATCOUNTER_SITE_HOST:-stats.internal}" in content


def test_analytics_default_env_is_forwarded_to_compose() -> None:
    content = build_image_compose_content()

    assert "ANALYTICS_ENABLED_DEFAULT=${ANALYTICS_ENABLED_DEFAULT:-true}" in content


@pytest.mark.parametrize(
    "builder",
    [
        build_direct_compose_content,
        build_image_compose_content,
        build_image_direct_compose_content,
        build_external_caddy_compose_content,
        build_image_external_caddy_compose_content,
    ],
)
def test_goatcounter_healthcheck_sends_configured_host_header(
    builder: Callable[[], str],
) -> None:
    content = builder()
    expected = (
        'test: ["CMD-SHELL", "wget -qO/dev/null '
        '--header=\\"Host: ${GOATCOUNTER_SITE_HOST:-stats.internal}\\" '
        'http://127.0.0.1:8080/user/new"]'
    )

    assert expected in content
    assert 'test: ["CMD", "wget", "--spider", "-q", "http://localhost:8080"]' not in content


def test_setup_script_waits_for_goatcounter_when_enabled() -> None:
    script = build_setup_script_content(_make_config())

    assert "ps -q goatcounter" in script
    assert "goatcounter container not found yet" in script
    assert "goatcounter: $GOATCOUNTER_HEALTH" in script
    assert "Error: GoatCounter container failed" in script


def test_all_compose_builders_share_only_the_goatcounter_token_with_agblogger() -> None:
    """All compose builders should expose only the token volume to agblogger, not the DB volume."""
    builders_and_contents = [
        ("build_direct_compose_content", build_direct_compose_content()),
        ("build_image_compose_content", build_image_compose_content()),
        ("build_image_direct_compose_content", build_image_direct_compose_content()),
        ("build_external_caddy_compose_content", build_external_caddy_compose_content()),
        (
            "build_image_external_caddy_compose_content",
            build_image_external_caddy_compose_content(),
        ),
    ]
    for name, content in builders_and_contents:
        assert "goatcounter-token:/data/goatcounter-token:ro" in content, (
            f"{name} missing read-only GoatCounter token mount"
        )
        assert "user: root" in content, f"{name} should run GoatCounter as root"
        assert content.count("goatcounter-db:/data/goatcounter") == 1, (
            f"{name} should keep GoatCounter DB private to the GoatCounter service"
        )


def test_build_external_caddy_compose_includes_goatcounter_on_caddy_network() -> None:
    content = build_external_caddy_compose_content()
    assert "goatcounter:" in content
    assert "arp242/goatcounter:latest" in content
    # GoatCounter must be on the same network as agblogger
    assert EXTERNAL_CADDY_NETWORK_NAME in content


def test_build_image_external_caddy_compose_includes_goatcounter_on_caddy_network() -> None:
    content = build_image_external_caddy_compose_content()
    assert "goatcounter:" in content
    assert EXTERNAL_CADDY_NETWORK_NAME in content


def test_write_bundle_files_includes_goatcounter_entrypoint(tmp_path: Path) -> None:
    """Deployment bundle includes the GoatCounter entrypoint script."""
    config = _make_config(
        deployment_mode=DEPLOY_MODE_TARBALL,
        image_ref="ghcr.io/example/agblogger:v1.0",
    )
    bundle_dir = tmp_path / "bundle"
    write_bundle_files(config, bundle_dir)
    entrypoint = bundle_dir / "goatcounter" / "entrypoint.sh"
    assert entrypoint.exists()
    assert entrypoint.stat().st_mode & 0o111 != 0


def test_write_bundle_files_omits_goatcounter_entrypoint_when_disabled(tmp_path: Path) -> None:
    config = _make_config(
        deployment_mode=DEPLOY_MODE_TARBALL,
        image_ref="ghcr.io/example/agblogger:v1.0",
        deploy_goatcounter=False,
    )
    bundle_dir = tmp_path / "bundle"

    write_bundle_files(config, bundle_dir)

    assert not (bundle_dir / "goatcounter" / "entrypoint.sh").exists()


def test_write_bundle_files_fails_gracefully_when_entrypoint_missing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Deployment bundle should fail with a clear error when entrypoint.sh is missing."""
    config = _make_config(
        deployment_mode=DEPLOY_MODE_TARBALL,
        image_ref="ghcr.io/example/agblogger:v1.0",
    )
    bundle_dir = tmp_path / "bundle"

    # Make the entrypoint source path resolve to a non-existent location
    fake_goatcounter_dir = tmp_path / "fake_repo" / "goatcounter"
    fake_goatcounter_dir.mkdir(parents=True)
    # Do NOT create entrypoint.sh — it should be missing

    with (
        patch(
            "cli.deploy_production.Path.resolve",
            return_value=tmp_path / "fake_repo" / "cli" / "deploy_production.py",
        ),
        pytest.raises(SystemExit),
    ):
        write_bundle_files(config, bundle_dir)

    captured = capsys.readouterr()
    assert "entrypoint" in captured.err.lower()


def test_build_env_content_includes_max_content_size() -> None:
    """MAX_CONTENT_SIZE should appear in .env when set."""
    config = _make_config(max_content_size="2G")
    env = build_env_content(config)
    assert "MAX_CONTENT_SIZE=2G" in env


def test_build_env_content_omits_max_content_size_when_none() -> None:
    """MAX_CONTENT_SIZE should not appear in .env when not set."""
    config = _make_config()
    env = build_env_content(config)
    assert "MAX_CONTENT_SIZE" not in env
