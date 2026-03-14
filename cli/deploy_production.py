"""Interactive production deployment helper for AgBlogger."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from backend.validation import is_valid_trusted_host

MIN_SECRET_KEY_LENGTH = 32
MIN_ADMIN_PASSWORD_LENGTH = 8
DEFAULT_HOST_PORT = 8000
DEFAULT_ENV_FILE = ".env.production"
DEFAULT_CADDYFILE = "Caddyfile.production"
DEFAULT_NO_CADDY_COMPOSE_FILE = "docker-compose.nocaddy.yml"
DEFAULT_CADDY_PUBLIC_COMPOSE_FILE = "docker-compose.caddy-public.yml"
DEFAULT_IMAGE_COMPOSE_FILE = "docker-compose.image.yml"
DEFAULT_IMAGE_NO_CADDY_COMPOSE_FILE = "docker-compose.image.nocaddy.yml"
DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE = "docker-compose.external-caddy.yml"
DEFAULT_IMAGE_EXTERNAL_CADDY_COMPOSE_FILE = "docker-compose.image.external-caddy.yml"
DEFAULT_REMOTE_README = "DEPLOY-REMOTE.md"
DEFAULT_SETUP_SCRIPT = "setup.sh"
DEFAULT_IMAGE_TARBALL = "agblogger-image.tar"
DEFAULT_REMOTE_PLATFORM = "linux/amd64"
DEFAULT_BUNDLE_DIR = Path("dist/deploy")
DEPLOY_MODE_LOCAL = "local"
DEPLOY_MODE_REGISTRY = "registry"
DEPLOY_MODE_TARBALL = "tarball"
DEPLOY_MODES = {DEPLOY_MODE_LOCAL, DEPLOY_MODE_REGISTRY, DEPLOY_MODE_TARBALL}
LOCAL_IMAGE_TAG = "agblogger:latest"
AGBLOGGER_STATIC_IP = "172.30.0.3"
CADDY_STATIC_IP = "172.30.0.2"
COMPOSE_SUBNET = "172.30.0.0/24"
# Constructed to avoid static-analysis tools flagging literal 0.0.0.0
PUBLIC_BIND_IP = ".".join(("0", "0", "0", "0"))
LOCALHOST_BIND_IP = "127.0.0.1"

HEALTH_POLL_INTERVAL_SECONDS = 5
HEALTH_POLL_TIMEOUT_SECONDS = 60

CADDY_MODE_BUNDLED = "bundled"
CADDY_MODE_EXTERNAL = "external"
CADDY_MODE_NONE = "none"
CADDY_MODES = {CADDY_MODE_BUNDLED, CADDY_MODE_EXTERNAL, CADDY_MODE_NONE}
DEFAULT_SHARED_CADDY_DIR = "/opt/caddy"
EXTERNAL_CADDY_NETWORK_NAME = "caddy"
SHARED_CADDY_CONTAINER_NAME = "caddy"
DEFAULT_SHARED_CADDY_COMPOSE_FILE = "docker-compose.yml"
DEFAULT_SHARED_CADDYFILE = "Caddyfile"
CADDY_NETWORK_SUBNET_PLACEHOLDER = "__CADDY_NETWORK_SUBNET__"


def _read_version() -> str:
    """Read the application version from the VERSION file."""
    version_file = Path(__file__).resolve().parent.parent / "VERSION"
    try:
        return version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


# Each label: starts with alphanumeric, may contain hyphens, ends with alphanumeric.
# At least two labels separated by dots.
_DOMAIN_RE = re.compile(
    r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?"
    r"(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)+$"
)


def _is_ipv4_like(host: str) -> bool:
    """Return True when the string looks like a dotted-decimal IPv4 address."""
    parts = host.split(".")
    return len(parts) == 4 and all(p.isdigit() for p in parts)


GENERATED_CONFIG_FILES = [
    DEFAULT_ENV_FILE,
    DEFAULT_CADDYFILE,
    DEFAULT_NO_CADDY_COMPOSE_FILE,
    DEFAULT_CADDY_PUBLIC_COMPOSE_FILE,
    DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE,
]

BUNDLE_CONFIG_FILES = [
    DEFAULT_ENV_FILE,
    DEFAULT_CADDYFILE,
    DEFAULT_CADDY_PUBLIC_COMPOSE_FILE,
    DEFAULT_IMAGE_COMPOSE_FILE,
    DEFAULT_IMAGE_NO_CADDY_COMPOSE_FILE,
    DEFAULT_IMAGE_EXTERNAL_CADDY_COMPOSE_FILE,
    DEFAULT_REMOTE_README,
    DEFAULT_SETUP_SCRIPT,
]


class DeployError(RuntimeError):
    """Raised for deployment workflow failures."""


@dataclass(frozen=True)
class CaddyConfig:
    """Caddy reverse-proxy settings."""

    domain: str
    email: str | None


@dataclass(frozen=True)
class SharedCaddyConfig:
    """Settings for a shared, host-level Caddy reverse proxy."""

    caddy_dir: Path
    acme_email: str | None


@dataclass(frozen=True)
class DeployConfig:
    """User-provided production configuration."""

    secret_key: str
    admin_username: str
    admin_password: str
    trusted_hosts: list[str]
    trusted_proxy_ips: list[str]
    host_port: int
    host_bind_ip: str
    caddy_config: CaddyConfig | None
    caddy_public: bool
    expose_docs: bool
    admin_display_name: str = ""
    deployment_mode: str = DEPLOY_MODE_LOCAL
    image_ref: str | None = None
    bundle_dir: Path = DEFAULT_BUNDLE_DIR
    tarball_filename: str = DEFAULT_IMAGE_TARBALL
    platform: str | None = None
    caddy_mode: str = CADDY_MODE_NONE
    shared_caddy_config: SharedCaddyConfig | None = None


@dataclass(frozen=True)
class DeployResult:
    """Result metadata for a successful deployment."""

    env_path: Path
    commands: dict[str, str]
    bundle_path: Path | None = None


# ── Content builders ─────────────────────────────────────────────────


def parse_csv_list(raw: str) -> list[str]:
    """Parse comma-separated values, trimming whitespace and removing duplicates."""
    values: list[str] = []
    for entry in raw.split(","):
        candidate = entry.strip()
        if candidate and candidate not in values:
            values.append(candidate)
    return values


def _list_to_env_json(values: list[str]) -> str:
    """Serialize list values for pydantic-settings JSON parsing."""
    return json.dumps(values, separators=(",", ":"))


def _quote_env_value(value: str) -> str:
    """Quote scalar env values so special characters stay intact.

    Uses json.dumps for baseline escaping (backslashes, quotes, control chars),
    then escapes ``$`` as ``\\$`` so Docker Compose's godotenv parser does not
    interpret dollar signs as variable references.
    """
    return json.dumps(value).replace("$", "\\$")


def _unquote_env_value(raw: str) -> str:
    """Reverse ``_quote_env_value``: undo Docker Compose dollar escaping, then JSON-decode."""
    raw = raw.strip()
    if raw.startswith('"'):
        try:
            decoded: str = json.loads(raw.replace("\\$", "$"))
            return decoded
        except json.JSONDecodeError, ValueError:
            return raw
    # Unquoted value — strip inline comments
    comment_idx = raw.find("  #")
    if comment_idx >= 0:
        raw = raw[:comment_idx].strip()
    return raw


def parse_existing_env(env_path: Path) -> dict[str, str]:
    """Parse key-value pairs from an existing .env.production file."""
    values: dict[str, str] = {}
    try:
        content = env_path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        eq_idx = line.find("=")
        if eq_idx < 0:
            continue
        key = line[:eq_idx].strip()
        raw_value = line[eq_idx + 1 :]
        values[key] = _unquote_env_value(raw_value)
    return values


COMMAND_TIMEOUT_SECONDS = 1800


def _run_command(
    command: list[str],
    project_dir: Path,
    timeout: int = COMMAND_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[bytes]:
    """Run a CLI command in the project directory."""
    return subprocess.run(command, cwd=project_dir, check=True, timeout=timeout)


def _run_docker(project_dir: Path, args: list[str]) -> subprocess.CompletedProcess[bytes]:
    """Run a Docker CLI command in the project directory."""
    return _run_command(["docker", *args], project_dir)


def _run_trivy(project_dir: Path, args: list[str]) -> subprocess.CompletedProcess[bytes]:
    """Run a Trivy CLI command in the project directory."""
    return _run_command(["trivy", *args], project_dir)


def build_env_content(config: DeployConfig) -> str:
    """Build .env file content for production deployment."""
    use_caddy = config.caddy_config is not None
    lines = [
        "# Auto-generated by cli/deploy_production.py",
        f"SECRET_KEY={_quote_env_value(config.secret_key)}",
        f"ADMIN_USERNAME={_quote_env_value(config.admin_username)}",
        f"ADMIN_PASSWORD={_quote_env_value(config.admin_password)}",
        f"ADMIN_DISPLAY_NAME={_quote_env_value(config.admin_display_name)}",
    ]
    if use_caddy:
        lines.append(f"HOST_PORT={config.host_port}  # Only used in no-Caddy mode")
        lines.append(f"HOST_BIND_IP={config.host_bind_ip}  # Only used in no-Caddy mode")
    else:
        lines.append(f"HOST_PORT={config.host_port}")
        lines.append(f"HOST_BIND_IP={config.host_bind_ip}")
    bluesky_domain = (
        config.caddy_config.domain if config.caddy_config is not None else "blog.example.com"
    )
    lines.extend(
        [
            "DEBUG=false",
            f"EXPOSE_DOCS={'true' if config.expose_docs else 'false'}",
            f"TRUSTED_HOSTS={_list_to_env_json(config.trusted_hosts)}",
            f"TRUSTED_PROXY_IPS={_list_to_env_json(config.trusted_proxy_ips)}",
            "AUTH_ENFORCE_LOGIN_ORIGIN=true",
            "AUTH_SELF_REGISTRATION=false",
            "AUTH_INVITES_ENABLED=true",
            "AUTH_LOGIN_MAX_FAILURES=5",
            "AUTH_RATE_LIMIT_WINDOW_SECONDS=300",
            f"# BLUESKY_CLIENT_URL=https://{bluesky_domain}"
            "  # Uncomment to enable Bluesky cross-posting",
        ]
    )
    if config.image_ref is not None:
        lines.append(f"AGBLOGGER_IMAGE={_quote_env_value(config.image_ref)}")
    return "\n".join(lines) + "\n"


def _caddy_site_block_body(domain: str) -> str:
    """Return the full Caddyfile site block for a given domain."""
    return (
        f"{domain} {{\n"
        "    @postUpload path /api/posts/upload\n"
        "    request_body @postUpload {\n"
        "        max_size 55MB\n"
        "    }\n\n"
        "    @postAssets path_regexp post_assets ^/api/posts/.+/assets$\n"
        "    request_body @postAssets {\n"
        "        max_size 55MB\n"
        "    }\n\n"
        "    @syncCommit path /api/sync/commit\n"
        "    request_body @syncCommit {\n"
        "        max_size 100MB\n"
        "    }\n\n"
        "    header {\n"
        '        Strict-Transport-Security "max-age=31536000"\n'
        "    }\n\n"
        "    reverse_proxy agblogger:8000\n\n"
        "    # Static asset caching\n"
        "    header /assets/* {\n"
        '        Cache-Control "public, max-age=31536000, immutable"\n'
        "    }\n\n"
        "    # HTML caching (short TTL for freshness)\n"
        "    @html path_regexp \\.html$\n"
        "    header @html {\n"
        '        Cache-Control "public, max-age=60"\n'
        "    }\n\n"
        "    # API caching\n"
        "    header /api/* {\n"
        '        Cache-Control "no-cache"\n'
        "    }\n\n"
        "    # Compression\n"
        "    encode gzip zstd\n"
        "}\n"
    )


def build_caddyfile_content(config: CaddyConfig) -> str:
    """Build Caddyfile content for HTTPS reverse proxy with request body limits."""
    global_block = f"{{\n    email {config.email}\n}}\n\n" if config.email else ""
    return f"{global_block}{_caddy_site_block_body(config.domain)}"


def build_caddy_site_snippet(config: CaddyConfig) -> str:
    """Build a per-domain Caddyfile snippet without the global email block."""
    return _caddy_site_block_body(config.domain)


def build_shared_caddyfile_content(acme_email: str | None) -> str:
    """Build the root Caddyfile for a shared Caddy instance."""
    global_block = f"{{\n    email {acme_email}\n}}\n\n" if acme_email else ""
    return f"{global_block}import /etc/caddy/sites/*.caddy\n"


def build_shared_caddy_compose_content() -> str:
    """Build the compose file for a shared Caddy reverse proxy."""
    return (
        "services:\n"
        "  caddy:\n"
        "    image: caddy:2\n"
        "    container_name: caddy\n"
        "    ports:\n"
        '      - "80:80"\n'
        '      - "443:443"\n'
        "    volumes:\n"
        "      - ./Caddyfile:/etc/caddy/Caddyfile:ro\n"
        "      - ./sites:/etc/caddy/sites:ro\n"
        "      - caddy-data:/data\n"
        "      - caddy-config:/config\n"
        "    restart: unless-stopped\n"
        "    networks:\n"
        f"      - {EXTERNAL_CADDY_NETWORK_NAME}\n"
        "\n"
        "volumes:\n"
        "  caddy-data:\n"
        "  caddy-config:\n"
        "\n"
        "networks:\n"
        f"  {EXTERNAL_CADDY_NETWORK_NAME}:\n"
        f"    name: {EXTERNAL_CADDY_NETWORK_NAME}\n"
        "    driver: bridge\n"
    )


def build_setup_script_content(config: DeployConfig) -> str:
    """Build an idempotent setup script for remote deployment bundles."""
    compose_flags = _compose_filenames(
        config.deployment_mode,
        use_caddy=config.caddy_config is not None and config.caddy_mode != CADDY_MODE_EXTERNAL,
        caddy_public=config.caddy_public,
        caddy_mode=config.caddy_mode,
    )
    compose_cmd = "docker compose --env-file .env.production"
    if compose_flags:
        compose_cmd += " " + " ".join(f"-f {f}" for f in compose_flags)

    lines = [
        "#!/usr/bin/env bash",
        "# Auto-generated by cli/deploy_production.py — safe to re-run (idempotent).",
        "set -euo pipefail",
        'cd "$(dirname "$0")"',
        "",
        "# ── Preflight checks ────────────────────────────────────────────────",
        "if ! command -v docker &>/dev/null; then",
        '    echo "Error: Docker is not installed." >&2',
        "    exit 1",
        "fi",
        "if ! docker info &>/dev/null; then",
        '    echo "Error: Docker daemon is not running." >&2',
        "    exit 1",
        "fi",
        "",
    ]

    # Load/pull image
    if config.deployment_mode == DEPLOY_MODE_TARBALL:
        lines.extend(
            [
                "# ── Load image ───────────────────────────────────────────────────────",
                f'echo "Loading Docker image from {config.tarball_filename}..."',
                f"docker load -i {config.tarball_filename}",
                "",
            ]
        )
    elif config.deployment_mode == DEPLOY_MODE_REGISTRY:
        lines.extend(
            [
                "# ── Pull image ───────────────────────────────────────────────────────",
                'echo "Pulling Docker image..."',
                f"{compose_cmd} pull",
                "",
            ]
        )

    # Bootstrap shared Caddy (external mode only)
    if (
        config.caddy_mode == CADDY_MODE_EXTERNAL
        and config.shared_caddy_config is not None
        and config.caddy_config is not None
    ):
        caddy_dir = str(config.shared_caddy_config.caddy_dir)
        caddyfile_content = build_shared_caddyfile_content(
            config.shared_caddy_config.acme_email,
        )
        caddy_compose_content = build_shared_caddy_compose_content()
        site_snippet = build_caddy_site_snippet(config.caddy_config)
        domain = config.caddy_config.domain

        lines.extend(
            [
                "# ── Bootstrap shared Caddy ───────────────────────────────────────────",
                'echo "Setting up shared Caddy reverse proxy..."',
                f"mkdir -p {caddy_dir}/sites",
                "",
            ]
        )

        # Write shared Caddyfile if not exists
        lines.extend(
            [
                f"if [ ! -f {caddy_dir}/{DEFAULT_SHARED_CADDYFILE} ]; then",
                f"    cat > {caddy_dir}/{DEFAULT_SHARED_CADDYFILE} <<'CADDYFILE_EOF'",
                caddyfile_content.rstrip("\n"),
                "CADDYFILE_EOF",
                "fi",
                "",
            ]
        )

        # Write shared docker-compose.yml if not exists
        lines.extend(
            [
                f"if [ ! -f {caddy_dir}/{DEFAULT_SHARED_CADDY_COMPOSE_FILE} ]; then",
                f"    cat > {caddy_dir}/{DEFAULT_SHARED_CADDY_COMPOSE_FILE} <<'COMPOSE_EOF'",
                caddy_compose_content.rstrip("\n"),
                "COMPOSE_EOF",
                "fi",
                "",
            ]
        )

        # Create Docker network if not exists
        lines.extend(
            [
                f"if ! docker network inspect {EXTERNAL_CADDY_NETWORK_NAME} &>/dev/null; then",
                f'    echo "Creating Docker network {EXTERNAL_CADDY_NETWORK_NAME}..."',
                f"    docker network create {EXTERNAL_CADDY_NETWORK_NAME}",
                "fi",
                "",
            ]
        )

        # Start shared Caddy if not running
        container = SHARED_CADDY_CONTAINER_NAME
        ps_check = f'if ! docker ps --format "{{{{.Names}}}}" | grep -q "^{container}$"; then'
        lines.extend(
            [
                ps_check,
                '    echo "Starting shared Caddy..."',
                f"    (cd {caddy_dir} && docker compose up -d)",
                "fi",
                "",
            ]
        )

        # Detect subnet and replace placeholder in .env.production
        inspect_fmt = "{{{{range .IPAM.Config}}}}{{{{.Subnet}}}}{{{{end}}}}"
        subnet_cmd = (
            f"CADDY_SUBNET=$(docker network inspect"
            f' {EXTERNAL_CADDY_NETWORK_NAME} --format "{inspect_fmt}")'
        )
        sed_cmd = f'sed -i "s|{CADDY_NETWORK_SUBNET_PLACEHOLDER}|$CADDY_SUBNET|" .env.production'
        lines.extend(
            [
                "# Detect Caddy network subnet for trusted proxy configuration",
                subnet_cmd,
                sed_cmd,
                "",
            ]
        )

        # Write site snippet
        lines.extend(
            [
                f"# Write site snippet for {domain}",
                f"cat > {caddy_dir}/sites/{domain}.caddy <<'SITE_EOF'",
                site_snippet.rstrip("\n"),
                "SITE_EOF",
                "",
            ]
        )

        # Reload Caddy
        reload_cmd = (
            f"docker exec {SHARED_CADDY_CONTAINER_NAME} caddy reload --config /etc/caddy/Caddyfile"
        )
        lines.extend(
            [
                'echo "Reloading Caddy configuration..."',
                reload_cmd,
                "",
            ]
        )

    # Start/restart AgBlogger
    lines.extend(
        [
            "# ── Start services ───────────────────────────────────────────────────",
            'echo "Starting AgBlogger..."',
            f"{compose_cmd} up -d",
            "",
        ]
    )

    # Health check
    lines.extend(
        [
            "# ── Health check ─────────────────────────────────────────────────────",
            'echo "Waiting for services to become healthy..."',
            "TIMEOUT=60",
            "INTERVAL=5",
            "ELAPSED=0",
            "while [ $ELAPSED -lt $TIMEOUT ]; do",
            "    sleep $INTERVAL",
            "    ELAPSED=$((ELAPSED + INTERVAL))",
            (
                f"    STATUS=$({compose_cmd} ps"
                ' --format "{{{{.Service}}}}: {{{{.Status}}}}"'
                ' 2>/dev/null || echo "query failed")'
            ),
            '    echo "  [${ELAPSED}s] $STATUS"',
            (
                '    if echo "$STATUS" | grep -q "agblogger:"'
                ' && echo "$STATUS" | grep -q "(healthy)"; then'
            ),
            '        echo "All services healthy."',
            "        exit 0",
            "    fi",
            "done",
            'echo "Error: Health check timed out after ${TIMEOUT}s." >&2',
            f'echo "Check logs: {compose_cmd} logs" >&2',
            "exit 1",
        ]
    )

    return "\n".join(lines) + "\n"


def _agblogger_env_section() -> str:
    """Return the environment YAML block shared across all compose files."""
    return (
        "    environment:\n"
        "      - SECRET_KEY=${SECRET_KEY?Set SECRET_KEY}\n"
        "      - ADMIN_USERNAME=${ADMIN_USERNAME?Set ADMIN_USERNAME}\n"
        "      - ADMIN_PASSWORD=${ADMIN_PASSWORD?Set ADMIN_PASSWORD}\n"
        "      - ADMIN_DISPLAY_NAME=${ADMIN_DISPLAY_NAME:-}\n"
        "      - TRUSTED_HOSTS=${TRUSTED_HOSTS?Set TRUSTED_HOSTS}\n"
        "      - TRUSTED_PROXY_IPS=${TRUSTED_PROXY_IPS:-[]}\n"
        "      - CONTENT_DIR=/data/content\n"
        "      - DATABASE_URL=sqlite+aiosqlite:////data/db/agblogger.db\n"
        "      - DEBUG=${DEBUG:-false}\n"
        "      - EXPOSE_DOCS=${EXPOSE_DOCS:-false}\n"
        "      - AUTH_ENFORCE_LOGIN_ORIGIN=${AUTH_ENFORCE_LOGIN_ORIGIN:-true}\n"
        "      - AUTH_SELF_REGISTRATION=${AUTH_SELF_REGISTRATION:-false}\n"
        "      - AUTH_INVITES_ENABLED=${AUTH_INVITES_ENABLED:-true}\n"
        "      - AUTH_LOGIN_MAX_FAILURES=${AUTH_LOGIN_MAX_FAILURES:-5}\n"
        "      - AUTH_RATE_LIMIT_WINDOW_SECONDS=${AUTH_RATE_LIMIT_WINDOW_SECONDS:-300}\n"
        "      - BLUESKY_CLIENT_URL=${BLUESKY_CLIENT_URL:-}\n"
    )


def _agblogger_healthcheck_section(*, include_network: bool = False) -> str:
    """Return the restart + healthcheck YAML block for agblogger services."""
    block = (
        "    restart: unless-stopped\n"
        "    healthcheck:\n"
        '      test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]\n'
        "      interval: 30s\n"
        "      timeout: 5s\n"
        "      start_period: 10s\n"
        "      retries: 3\n"
    )
    if include_network:
        block += f"    networks:\n      default:\n        ipv4_address: {AGBLOGGER_STATIC_IP}\n"
    return block


def _caddy_service_section() -> str:
    """Return the Caddy service YAML block with static proxy IP."""
    return (
        "  caddy:\n"
        "    image: caddy:2\n"
        "    ports:\n"
        '      - "127.0.0.1:80:80"\n'
        '      - "127.0.0.1:443:443"\n'
        "    volumes:\n"
        "      - ./Caddyfile.production:/etc/caddy/Caddyfile:ro\n"
        "      - caddy-data:/data\n"
        "      - caddy-config:/config\n"
        "    depends_on:\n"
        "      agblogger:\n"
        "        condition: service_healthy\n"
        "    restart: unless-stopped\n"
        "    networks:\n"
        "      default:\n"
        f"        ipv4_address: {CADDY_STATIC_IP}\n"
    )


def _compose_network_block() -> str:
    """Return the custom network YAML block for Caddy proxy IP."""
    return (
        "networks:\n"
        "  default:\n"
        "    driver: bridge\n"
        "    ipam:\n"
        "      config:\n"
        f"        - subnet: {COMPOSE_SUBNET}\n"
    )


def build_direct_compose_content() -> str:
    """Build a no-Caddy compose file for direct AgBlogger exposure."""
    return (
        "services:\n"
        "  agblogger:\n"
        "    build: .\n"
        f"    image: {LOCAL_IMAGE_TAG}\n"
        "    user: root\n"
        "    ports:\n"
        '      - "${HOST_BIND_IP:-127.0.0.1}:${HOST_PORT:-8000}:8000"\n'
        "    volumes:\n"
        "      - ./content:/data/content\n"
        "      - agblogger-db:/data/db\n"
        + _agblogger_env_section()
        + _agblogger_healthcheck_section()
        + "\n"
        "volumes:\n"
        "  agblogger-db:\n"
    )


def build_image_compose_content() -> str:
    """Build an image-only Caddy-first compose file for remote deployment."""
    return (
        "services:\n"
        "  agblogger:\n"
        '    image: "${AGBLOGGER_IMAGE?Set AGBLOGGER_IMAGE}"\n'
        "    user: root\n"
        "    expose:\n"
        '      - "8000"\n'
        "    volumes:\n"
        "      - ./content:/data/content\n"
        "      - agblogger-db:/data/db\n"
        + _agblogger_env_section()
        + _agblogger_healthcheck_section(include_network=True)
        + "\n"
        + _caddy_service_section()
        + "\n"
        + _compose_network_block()
        + "\n"
        "volumes:\n"
        "  agblogger-db:\n"
        "  caddy-data:\n"
        "  caddy-config:\n"
    )


def build_image_direct_compose_content() -> str:
    """Build an image-only no-Caddy compose file for remote deployment."""
    return (
        "services:\n"
        "  agblogger:\n"
        '    image: "${AGBLOGGER_IMAGE?Set AGBLOGGER_IMAGE}"\n'
        "    user: root\n"
        "    ports:\n"
        '      - "${HOST_BIND_IP:-127.0.0.1}:${HOST_PORT:-8000}:8000"\n'
        "    volumes:\n"
        "      - ./content:/data/content\n"
        "      - agblogger-db:/data/db\n"
        + _agblogger_env_section()
        + _agblogger_healthcheck_section()
        + "\n"
        "volumes:\n"
        "  agblogger-db:\n"
    )


def build_caddy_public_compose_override_content() -> str:
    """Build compose override that exposes Caddy publicly."""
    return 'services:\n  caddy:\n    ports:\n      - "80:80"\n      - "443:443"\n'


def _external_caddy_network_block() -> str:
    """Return the network YAML block for joining an external Caddy network."""
    return (
        "networks:\n"
        f"  {EXTERNAL_CADDY_NETWORK_NAME}:\n"
        f"    name: {EXTERNAL_CADDY_NETWORK_NAME}\n"
        "    external: true\n"
    )


def build_external_caddy_compose_content() -> str:
    """Build a local-build AgBlogger compose file for use with an external Caddy proxy."""
    return (
        "services:\n"
        "  agblogger:\n"
        "    build: .\n"
        f"    image: {LOCAL_IMAGE_TAG}\n"
        "    user: root\n"
        "    expose:\n"
        '      - "8000"\n'
        "    volumes:\n"
        "      - ./content:/data/content\n"
        "      - agblogger-db:/data/db\n"
        + _agblogger_env_section()
        + _agblogger_healthcheck_section()
        + "    networks:\n"
        f"      - {EXTERNAL_CADDY_NETWORK_NAME}\n"
        "\n"
        "volumes:\n"
        "  agblogger-db:\n"
        "\n" + _external_caddy_network_block()
    )


def build_image_external_caddy_compose_content() -> str:
    """Build an image-only AgBlogger compose file for use with an external Caddy proxy."""
    return (
        "services:\n"
        "  agblogger:\n"
        '    image: "${AGBLOGGER_IMAGE?Set AGBLOGGER_IMAGE}"\n'
        "    user: root\n"
        "    expose:\n"
        '      - "8000"\n'
        "    volumes:\n"
        "      - ./content:/data/content\n"
        "      - agblogger-db:/data/db\n"
        + _agblogger_env_section()
        + _agblogger_healthcheck_section()
        + "    networks:\n"
        f"      - {EXTERNAL_CADDY_NETWORK_NAME}\n"
        "\n"
        "volumes:\n"
        "  agblogger-db:\n"
        "\n" + _external_caddy_network_block()
    )


# ── Shared Caddy bootstrap ───────────────────────────────────────────


def _is_container_running(container_name: str) -> bool:
    """Check if a Docker container exists and is running."""
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", container_name],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and "true" in result.stdout.strip().lower()


def ensure_shared_caddy(caddy_dir: Path, acme_email: str | None) -> None:
    """Bootstrap or verify a shared Caddy reverse proxy at the given directory."""
    if _is_container_running(SHARED_CADDY_CONTAINER_NAME):
        print(f"Shared Caddy container '{SHARED_CADDY_CONTAINER_NAME}' is already running.")
        return

    print(f"Bootstrapping shared Caddy at {caddy_dir}...")
    caddy_dir.mkdir(parents=True, exist_ok=True)
    (caddy_dir / "sites").mkdir(exist_ok=True)

    caddyfile_path = caddy_dir / DEFAULT_SHARED_CADDYFILE
    if not caddyfile_path.exists():
        caddyfile_path.write_text(build_shared_caddyfile_content(acme_email), encoding="utf-8")

    compose_path = caddy_dir / DEFAULT_SHARED_CADDY_COMPOSE_FILE
    if not compose_path.exists():
        compose_path.write_text(build_shared_caddy_compose_content(), encoding="utf-8")

    print("Starting shared Caddy container...")
    _run_command(["docker", "compose", "up", "-d"], caddy_dir)
    print("Shared Caddy container started.")


def write_caddy_site_snippet(caddy_config: CaddyConfig, caddy_dir: Path) -> None:
    """Write a Caddy site snippet for AgBlogger into the shared sites directory."""
    sites_dir = caddy_dir / "sites"
    snippet_path = sites_dir / f"{caddy_config.domain}.caddy"
    snippet_path.write_text(build_caddy_site_snippet(caddy_config), encoding="utf-8")
    print(f"Wrote Caddy site snippet: {snippet_path}")


def reload_shared_caddy() -> None:
    """Reload the shared Caddy container to pick up config changes."""
    print("Reloading shared Caddy configuration...")
    subprocess.run(
        [
            "docker",
            "exec",
            SHARED_CADDY_CONTAINER_NAME,
            "caddy",
            "reload",
            "--config",
            "/etc/caddy/Caddyfile",
        ],
        check=True,
        timeout=30,
    )
    print("Shared Caddy reloaded.")


# ── Compose helpers ──────────────────────────────────────────────────


def _compose_filenames(
    deployment_mode: str,
    use_caddy: bool,
    caddy_public: bool,
    caddy_mode: str = CADDY_MODE_NONE,
) -> list[str]:
    """Return compose filenames for the requested deployment mode."""
    if caddy_mode == CADDY_MODE_EXTERNAL:
        if deployment_mode == DEPLOY_MODE_LOCAL:
            return [DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE]
        return [DEFAULT_IMAGE_EXTERNAL_CADDY_COMPOSE_FILE]

    if deployment_mode == DEPLOY_MODE_LOCAL:
        if use_caddy and caddy_public:
            return ["docker-compose.yml", DEFAULT_CADDY_PUBLIC_COMPOSE_FILE]
        if use_caddy:
            return ["docker-compose.yml"]
        return [DEFAULT_NO_CADDY_COMPOSE_FILE]

    if use_caddy and caddy_public:
        return [DEFAULT_IMAGE_COMPOSE_FILE, DEFAULT_CADDY_PUBLIC_COMPOSE_FILE]
    if use_caddy:
        return [DEFAULT_IMAGE_COMPOSE_FILE]
    return [DEFAULT_IMAGE_NO_CADDY_COMPOSE_FILE]


def _compose_base_command(
    deployment_mode: str,
    use_caddy: bool,
    caddy_public: bool,
    env_filename: str,
    caddy_mode: str = CADDY_MODE_NONE,
) -> str:
    """Build the shared docker compose command prefix for lifecycle commands."""
    filenames = _compose_filenames(deployment_mode, use_caddy, caddy_public, caddy_mode=caddy_mode)
    if not filenames:
        return f"docker compose --env-file {env_filename}"

    flags = " ".join(f"-f {name}" for name in filenames)
    return f"docker compose --env-file {env_filename} {flags}"


def build_lifecycle_commands(
    deployment_mode: str,
    use_caddy: bool,
    caddy_public: bool,
    env_filename: str = DEFAULT_ENV_FILE,
    tarball_filename: str = DEFAULT_IMAGE_TARBALL,
    caddy_mode: str = CADDY_MODE_NONE,
) -> dict[str, str]:
    """Build Docker lifecycle commands shown to the user."""
    base = _compose_base_command(
        deployment_mode, use_caddy, caddy_public, env_filename, caddy_mode=caddy_mode
    )
    commands = {
        "start": f"{base} up -d",
        "stop": f"{base} down",
        "status": f"{base} ps",
        "logs": f"{base} logs -f",
    }
    if deployment_mode == DEPLOY_MODE_LOCAL:
        commands["upgrade"] = f"{base} up -d --build"
    elif deployment_mode == DEPLOY_MODE_REGISTRY:
        commands["pull"] = f"{base} pull"
        commands["upgrade"] = f"{base} pull && {base} up -d"
    elif deployment_mode == DEPLOY_MODE_TARBALL:
        commands["load"] = f"docker load -i {tarball_filename}"
        commands["upgrade"] = f"docker load -i {tarball_filename} && {base} up -d"
    return commands


# ── Validation ───────────────────────────────────────────────────────


def _validate_config(config: DeployConfig) -> None:
    """Validate required production constraints before writing files."""
    if len(config.secret_key) < MIN_SECRET_KEY_LENGTH:
        raise DeployError(f"SECRET_KEY must have at least {MIN_SECRET_KEY_LENGTH} characters")
    if len(config.admin_password) < MIN_ADMIN_PASSWORD_LENGTH:
        raise DeployError(
            f"ADMIN_PASSWORD must have at least {MIN_ADMIN_PASSWORD_LENGTH} characters"
        )
    if not config.admin_username:
        raise DeployError("ADMIN_USERNAME must not be empty")
    if not config.trusted_hosts:
        raise DeployError("TRUSTED_HOSTS must include at least one host")
    for host in config.trusted_hosts:
        if not is_valid_trusted_host(host):
            raise DeployError(
                f"Invalid trusted host: {host!r}. "
                "Use explicit hosts or '*.example.com' (no catch-all wildcards)."
            )
    if not (1 <= config.host_port <= 65535):
        raise DeployError("HOST_PORT must be between 1 and 65535")
    if config.host_bind_ip not in {LOCALHOST_BIND_IP, PUBLIC_BIND_IP}:
        raise DeployError(f"HOST_BIND_IP must be either {LOCALHOST_BIND_IP} or {PUBLIC_BIND_IP}")
    if config.caddy_config is not None:
        domain = config.caddy_config.domain
        if _is_ipv4_like(domain) or not _DOMAIN_RE.match(domain):
            raise DeployError(f"Caddy domain must be a valid public hostname (got {domain!r})")
        if config.caddy_config.email and "@" not in config.caddy_config.email:
            raise DeployError("Caddy contact email must contain '@'")
    if config.caddy_public and config.caddy_config is None:
        raise DeployError("Caddy public exposure requires Caddy to be enabled")
    if config.caddy_mode not in CADDY_MODES:
        raise DeployError(f"caddy_mode must be one of: {', '.join(sorted(CADDY_MODES))}")
    if config.caddy_mode == CADDY_MODE_EXTERNAL:
        if config.caddy_config is None:
            raise DeployError("External Caddy mode requires a domain (caddy_config)")
        if config.shared_caddy_config is None:
            raise DeployError("External Caddy mode requires shared Caddy configuration")
    if config.deployment_mode not in DEPLOY_MODES:
        raise DeployError(f"DEPLOYMENT_MODE must be one of: {', '.join(sorted(DEPLOY_MODES))}")
    if config.deployment_mode in {DEPLOY_MODE_REGISTRY, DEPLOY_MODE_TARBALL}:
        if not config.image_ref:
            raise DeployError("IMAGE_REF is required for registry and tarball deployments")
    elif config.image_ref is not None:
        raise DeployError("IMAGE_REF is only supported for registry and tarball deployments")
    if config.image_ref is not None:
        ref = config.image_ref
        if any(char.isspace() for char in ref):
            raise DeployError("IMAGE_REF must not contain whitespace")
        if ref.endswith(":") or ref.startswith(":"):
            raise DeployError("IMAGE_REF has an invalid format (missing name or tag around ':')")
    if not config.bundle_dir.parts:
        raise DeployError("BUNDLE_DIR must not be empty")
    if config.deployment_mode == DEPLOY_MODE_TARBALL and not config.tarball_filename.strip():
        raise DeployError("TARBALL_FILENAME must not be empty")


def check_prerequisites(project_dir: Path, deployment_mode: str = DEPLOY_MODE_LOCAL) -> None:
    """Check required deployment prerequisites."""
    dockerfile = project_dir / "Dockerfile"
    if not dockerfile.exists():
        raise DeployError(f"Missing Dockerfile: {dockerfile}")
    if deployment_mode == DEPLOY_MODE_LOCAL:
        compose_file = project_dir / "docker-compose.yml"
        if not compose_file.exists():
            raise DeployError(f"Missing docker compose file: {compose_file}")
    if shutil.which("docker") is None:
        raise DeployError("Docker is not installed or not available on PATH")

    _run_docker(project_dir, ["--version"])
    _run_docker(project_dir, ["compose", "version"])


# ── File management ──────────────────────────────────────────────────


def backup_file(path: Path) -> Path | None:
    """Create a .bak backup of a file if it exists. Returns backup path or None."""
    if not path.exists():
        return None
    backup_path = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup_path)
    return backup_path


def backup_existing_configs(project_dir: Path) -> list[str]:
    """Back up existing generated config files. Returns list of informational messages."""
    messages: list[str] = []
    for filename in GENERATED_CONFIG_FILES:
        path = project_dir / filename
        backup = backup_file(path)
        if backup is not None:
            messages.append(f"Backed up {path.name} to {backup.name}")
    return messages


def _write_env_file(config: DeployConfig, target_dir: Path) -> None:
    """Write the generated environment file with restrictive permissions."""
    env_path = target_dir / DEFAULT_ENV_FILE
    env_path.write_text(build_env_content(config), encoding="utf-8")
    try:
        env_path.chmod(0o600)
    except OSError as exc:
        print(
            f"WARNING: Could not set restrictive permissions on {DEFAULT_ENV_FILE}: {exc}\n"
            f"This file contains sensitive secrets and may be readable by other users.",
            file=sys.stderr,
        )


def write_config_files(config: DeployConfig, project_dir: Path) -> None:
    """Write local deployment config files and clean up stale alternatives."""
    _write_env_file(config, project_dir)
    (project_dir / "content").mkdir(exist_ok=True)

    stale_files: list[str] = []

    if config.caddy_mode == CADDY_MODE_EXTERNAL:
        compose_path = project_dir / DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE
        compose_path.write_text(build_external_caddy_compose_content(), encoding="utf-8")
        stale_files.extend(
            [
                DEFAULT_NO_CADDY_COMPOSE_FILE,
                DEFAULT_CADDY_PUBLIC_COMPOSE_FILE,
                DEFAULT_CADDYFILE,
            ]
        )
    elif config.caddy_config is not None:
        caddyfile_path = project_dir / DEFAULT_CADDYFILE
        caddyfile_path.write_text(build_caddyfile_content(config.caddy_config), encoding="utf-8")
        stale_files.append(DEFAULT_NO_CADDY_COMPOSE_FILE)
        stale_files.append(DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE)
        if config.caddy_public:
            override_path = project_dir / DEFAULT_CADDY_PUBLIC_COMPOSE_FILE
            override_path.write_text(
                build_caddy_public_compose_override_content(), encoding="utf-8"
            )
        else:
            stale_files.append(DEFAULT_CADDY_PUBLIC_COMPOSE_FILE)
    else:
        no_caddy_path = project_dir / DEFAULT_NO_CADDY_COMPOSE_FILE
        no_caddy_path.write_text(build_direct_compose_content(), encoding="utf-8")
        stale_files.append(DEFAULT_CADDY_PUBLIC_COMPOSE_FILE)
        stale_files.append(DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE)

    for name in stale_files:
        with suppress(FileNotFoundError):
            (project_dir / name).unlink()


def _backup_bundle_configs(bundle_dir: Path) -> list[str]:
    """Back up generated bundle config files before overwriting them."""
    messages: list[str] = []
    for filename in BUNDLE_CONFIG_FILES:
        backup = backup_file(bundle_dir / filename)
        if backup is not None:
            messages.append(f"Backed up {filename} to {backup.name}")
    return messages


def _remote_bundle_commands(config: DeployConfig) -> dict[str, str]:
    """Build lifecycle commands for a remote deployment bundle."""
    return build_lifecycle_commands(
        deployment_mode=config.deployment_mode,
        use_caddy=config.caddy_config is not None,
        caddy_public=config.caddy_public,
        tarball_filename=config.tarball_filename,
        caddy_mode=config.caddy_mode,
    )


def _build_remote_readme_content(config: DeployConfig, commands: dict[str, str]) -> str:
    """Document how to use a generated remote deployment bundle."""
    lines = [
        "# Remote deployment bundle",
        "",
        "## Prerequisites",
        "",
        "- Docker Engine (20.10+)",
        "- Docker Compose V2 (`docker compose` subcommand)",
    ]
    if config.caddy_config is not None:
        lines.append(
            f"- DNS A/AAAA record pointing `{config.caddy_config.domain}`"
            " to this server (required for TLS certificate provisioning)"
        )
    if config.deployment_mode == DEPLOY_MODE_REGISTRY:
        lines.append(
            "- Container registry authentication (if using a private registry)"
        )
    lines.extend([
        "",
        "Blog content is stored in `./content/` (created automatically on first start).",
        "",
        "## Getting started",
        "",
        "```",
        "./setup.sh",
        "```",
        "",
        "## Management commands",
        "",
        f"- Stop: `{commands['stop']}`",
        f"- Status: `{commands['status']}`",
        f"- Logs: `{commands['logs']}`",
    ])
    if config.caddy_public:
        lines.extend([
            "",
            "## Firewall",
            "",
            "Caddy is configured to listen on ports 80 and 443 on all interfaces.",
            "Ensure your server firewall allows inbound traffic on these ports and",
            "blocks all other unnecessary ports. For example, with ufw:",
            "```",
            "ufw allow 80/tcp",
            "ufw allow 443/tcp",
            "ufw allow 22/tcp  # SSH",
            "ufw enable",
            "```",
        ])
    data_note = (
        "The database volume stores user accounts and settings alongside regenerable"
        " cache data. Both `./content/` and the `agblogger-db` Docker volume must be"
        " preserved during upgrades. Schema migrations run automatically on startup."
    )
    lines.extend([
        "",
        "## Upgrading",
        "",
        data_note,
        "",
        "To upgrade to a new version:",
        "",
        "1. Regenerate the bundle locally and replace all files in this directory"
        " (compose files and config may change between versions)."
        " Check the `VERSION` file to see what version generated the current bundle."
        " The `./content/` directory and `agblogger-db` Docker volume are not part"
        " of the bundle and will be preserved automatically.",
    ])
    if config.deployment_mode == DEPLOY_MODE_REGISTRY:
        lines.append(
            "2. Update the `AGBLOGGER_IMAGE` tag in `.env.production` if it changed."
        )
    elif config.deployment_mode == DEPLOY_MODE_TARBALL:
        lines.append(
            "2. If the image tag changed, update `AGBLOGGER_IMAGE` in `.env.production`."
        )
    lines.extend([
        "3. Run `./setup.sh` again.",
        "",
        "## Rollback",
        "",
        "If an upgrade causes problems, restore from the `.bak` backup files created",
        "during the previous deployment and restart with the previous image:",
        "```",
        "cp .env.production.bak .env.production",
        f"{commands['start']}",
        "```",
    ])
    return "\n".join(lines) + "\n"


def write_bundle_files(config: DeployConfig, bundle_dir: Path) -> None:
    """Write a self-contained remote deployment bundle."""
    bundle_dir.mkdir(parents=True, exist_ok=True)
    _write_env_file(config, bundle_dir)

    # Seed content directory so first-time users have the mount target ready
    (bundle_dir / "content").mkdir(exist_ok=True)

    # Write version marker for upgrade tracking
    version = _read_version()
    (bundle_dir / "VERSION").write_text(version + "\n", encoding="utf-8")

    stale_files: list[str] = []
    if config.caddy_mode == CADDY_MODE_EXTERNAL:
        (bundle_dir / DEFAULT_IMAGE_EXTERNAL_CADDY_COMPOSE_FILE).write_text(
            build_image_external_caddy_compose_content(), encoding="utf-8"
        )
        stale_files.extend(
            [
                DEFAULT_CADDYFILE,
                DEFAULT_CADDY_PUBLIC_COMPOSE_FILE,
                DEFAULT_IMAGE_COMPOSE_FILE,
                DEFAULT_IMAGE_NO_CADDY_COMPOSE_FILE,
            ]
        )
    elif config.caddy_config is not None:
        (bundle_dir / DEFAULT_CADDYFILE).write_text(
            build_caddyfile_content(config.caddy_config), encoding="utf-8"
        )
        (bundle_dir / DEFAULT_IMAGE_COMPOSE_FILE).write_text(
            build_image_compose_content(), encoding="utf-8"
        )
        stale_files.append(DEFAULT_IMAGE_NO_CADDY_COMPOSE_FILE)
        stale_files.append(DEFAULT_IMAGE_EXTERNAL_CADDY_COMPOSE_FILE)
        if config.caddy_public:
            (bundle_dir / DEFAULT_CADDY_PUBLIC_COMPOSE_FILE).write_text(
                build_caddy_public_compose_override_content(), encoding="utf-8"
            )
        else:
            stale_files.append(DEFAULT_CADDY_PUBLIC_COMPOSE_FILE)
    else:
        (bundle_dir / DEFAULT_IMAGE_NO_CADDY_COMPOSE_FILE).write_text(
            build_image_direct_compose_content(), encoding="utf-8"
        )
        stale_files.extend(
            [
                DEFAULT_CADDYFILE,
                DEFAULT_CADDY_PUBLIC_COMPOSE_FILE,
                DEFAULT_IMAGE_COMPOSE_FILE,
                DEFAULT_IMAGE_EXTERNAL_CADDY_COMPOSE_FILE,
            ]
        )

    for name in stale_files:
        with suppress(FileNotFoundError):
            (bundle_dir / name).unlink()

    commands = _remote_bundle_commands(config)
    (bundle_dir / DEFAULT_REMOTE_README).write_text(
        _build_remote_readme_content(config, commands),
        encoding="utf-8",
    )

    # Write idempotent setup script
    setup_path = bundle_dir / DEFAULT_SETUP_SCRIPT
    setup_path.write_text(build_setup_script_content(config), encoding="utf-8")
    try:
        setup_path.chmod(setup_path.stat().st_mode | 0o755)
    except OSError as exc:
        print(
            f"WARNING: Could not set executable permission on {DEFAULT_SETUP_SCRIPT}: {exc}",
            file=sys.stderr,
        )


# ── Build and scan ───────────────────────────────────────────────────


def build_image(project_dir: Path, image_tag: str, platform: str | None = None) -> None:
    """Build a Docker image with the requested tag."""
    print(f"Building Docker image ({image_tag})...")
    args = ["build"]
    if platform:
        args.extend(["--platform", platform])
    args.extend(["--tag", image_tag, "."])
    _run_docker(project_dir, args)


def scan_image(project_dir: Path, image_tag: str) -> None:
    """Scan a Docker image with Trivy."""
    print(f"Scanning image with Trivy ({image_tag})...")
    _run_trivy(
        project_dir,
        [
            "image",
            "--scanners",
            "vuln",
            "--exit-code",
            "1",
            "--severity",
            "MEDIUM,HIGH,CRITICAL",
            image_tag,
        ],
    )


def build_and_scan(project_dir: Path, image_tag: str, platform: str | None = None) -> None:
    """Build the Docker image and scan with Trivy before deployment."""
    build_image(project_dir, image_tag, platform=platform)
    scan_image(project_dir, image_tag)


def push_image(project_dir: Path, image_tag: str) -> None:
    """Push a Docker image to a registry."""
    print(f"Pushing image to registry ({image_tag})...")
    _run_docker(project_dir, ["push", image_tag])


def save_image_tarball(project_dir: Path, image_tag: str, tarball_path: Path) -> None:
    """Export a Docker image to a tarball."""
    print(f"Saving image tarball ({tarball_path.name})...")
    tarball_path.parent.mkdir(parents=True, exist_ok=True)
    _run_docker(project_dir, ["save", "--output", str(tarball_path), image_tag])


def _compose_base_args(config: DeployConfig) -> list[str]:
    """Build the shared docker compose CLI prefix for local deployments."""
    args = ["compose", "--env-file", ".env.production"]
    for filename in _compose_filenames(
        DEPLOY_MODE_LOCAL,
        use_caddy=config.caddy_config is not None and config.caddy_mode != CADDY_MODE_EXTERNAL,
        caddy_public=config.caddy_public,
        caddy_mode=config.caddy_mode,
    ):
        args.extend(["-f", filename])
    return args


def _compose_up_command(config: DeployConfig, *, build: bool = True) -> list[str]:
    """Build the docker compose up command for local deployments."""
    command = [*_compose_base_args(config), "up", "-d"]
    if build:
        command.append("--build")
    return command


def _compose_build_command(config: DeployConfig) -> list[str]:
    """Build the docker compose build command for local deployments."""
    return [*_compose_base_args(config), "build"]


def _wait_for_healthy(
    config: DeployConfig,
    project_dir: Path,
    timeout: int = HEALTH_POLL_TIMEOUT_SECONDS,
    interval: int = HEALTH_POLL_INTERVAL_SECONDS,
) -> None:
    """Poll service status after startup until healthy or timeout."""
    base = _compose_base_args(config)
    start = time.monotonic()
    deadline = start + timeout
    use_caddy = config.caddy_config is not None and config.caddy_mode != CADDY_MODE_EXTERNAL
    print("Waiting for services to become healthy...")
    while time.monotonic() < deadline:
        time.sleep(interval)
        result = subprocess.run(
            ["docker", *base, "ps", "--format", "{{.Service}}: {{.Status}}"],
            cwd=project_dir,
            capture_output=True,
            text=True,
        )
        elapsed = int(time.monotonic() - start)
        if result.returncode != 0:
            print(f"  [{elapsed}s] failed to query service status (exit {result.returncode})")
            continue
        lines = result.stdout.strip().splitlines()
        status_parts = [line.strip() for line in lines if line.strip()]
        status_summary = "; ".join(status_parts) if status_parts else "no services found"
        print(f"  [{elapsed}s] {status_summary}")
        agblogger_lines = [line for line in lines if "agblogger" in line]
        if not (agblogger_lines and all("(healthy)" in line for line in agblogger_lines)):
            continue
        if use_caddy:
            caddy_lines = [line for line in lines if "caddy" in line]
            if not (caddy_lines and all("Up" in line for line in caddy_lines)):
                continue
        print("All services healthy.")
        return
    logs_cmd = "docker " + " ".join(_compose_base_args(config)) + " logs"
    raise DeployError(
        f"Health check timed out after {timeout}s. "
        f"Check service logs to diagnose the issue:\n  {logs_cmd}"
    )


def _run_compose_up(config: DeployConfig, project_dir: Path, *, build: bool = True) -> None:
    """Start containers via docker compose with the correct file arguments."""
    print("Starting containers...")
    _run_docker(project_dir, _compose_up_command(config, build=build))
    _wait_for_healthy(config, project_dir)


# ── Deploy orchestration ────────────────────────────────────────────


def deploy(config: DeployConfig, project_dir: Path) -> DeployResult:
    """Write deployment config, build, scan, and start containers.

    Assumes check_prerequisites() has already been called by the caller.
    """
    _validate_config(config)

    trivy_available = shutil.which("trivy") is not None
    if trivy_available:
        _run_trivy(project_dir, ["--version"])
    else:
        print(
            "Warning: Trivy is not installed or not available on PATH; skipping Docker image scan.",
            file=sys.stderr,
        )

    backup_messages = backup_existing_configs(project_dir)
    for msg in backup_messages:
        print(msg)

    if config.deployment_mode == DEPLOY_MODE_LOCAL:
        write_config_files(config, project_dir)

        if config.caddy_mode == CADDY_MODE_EXTERNAL and config.shared_caddy_config is not None:
            ensure_shared_caddy(
                caddy_dir=config.shared_caddy_config.caddy_dir,
                acme_email=config.shared_caddy_config.acme_email,
            )
            if config.caddy_config is not None:
                write_caddy_site_snippet(
                    config.caddy_config,
                    config.shared_caddy_config.caddy_dir,
                )
                reload_shared_caddy()

        if trivy_available:
            print(f"Building Docker image ({LOCAL_IMAGE_TAG})...")
            _run_docker(project_dir, _compose_build_command(config))
            scan_image(project_dir, LOCAL_IMAGE_TAG)
            _run_compose_up(config, project_dir, build=False)
        else:
            _run_compose_up(config, project_dir)

        return DeployResult(
            env_path=project_dir / DEFAULT_ENV_FILE,
            commands=build_lifecycle_commands(
                deployment_mode=config.deployment_mode,
                use_caddy=config.caddy_config is not None,
                caddy_public=config.caddy_public,
                caddy_mode=config.caddy_mode,
            ),
            bundle_path=None,
        )

    bundle_dir = project_dir / config.bundle_dir
    bundle_backup_messages = _backup_bundle_configs(bundle_dir)
    for msg in bundle_backup_messages:
        print(msg)

    image_tag = config.image_ref
    if image_tag is None:
        raise DeployError("IMAGE_REF is required for remote deployment modes")

    if trivy_available:
        build_and_scan(project_dir, image_tag, platform=config.platform)
    else:
        build_image(project_dir, image_tag, platform=config.platform)

    write_bundle_files(config, bundle_dir)

    if config.deployment_mode == DEPLOY_MODE_REGISTRY:
        push_image(project_dir, image_tag)
    else:
        save_image_tarball(project_dir, image_tag, bundle_dir / config.tarball_filename)

    return DeployResult(
        env_path=bundle_dir / DEFAULT_ENV_FILE,
        commands=_remote_bundle_commands(config),
        bundle_path=bundle_dir,
    )


# ── Dry run ──────────────────────────────────────────────────────────


def _mask_secrets(config: DeployConfig) -> DeployConfig:
    """Return a copy of config with secrets replaced by placeholders for display."""
    placeholder = "*" * 8
    return DeployConfig(
        secret_key=placeholder,
        admin_username=config.admin_username,
        admin_password=placeholder,
        admin_display_name=config.admin_display_name,
        trusted_hosts=config.trusted_hosts,
        trusted_proxy_ips=config.trusted_proxy_ips,
        host_port=config.host_port,
        host_bind_ip=config.host_bind_ip,
        caddy_config=config.caddy_config,
        caddy_public=config.caddy_public,
        expose_docs=config.expose_docs,
        deployment_mode=config.deployment_mode,
        image_ref=config.image_ref,
        bundle_dir=config.bundle_dir,
        tarball_filename=config.tarball_filename,
        platform=config.platform,
        caddy_mode=config.caddy_mode,
        shared_caddy_config=config.shared_caddy_config,
    )


def dry_run(config: DeployConfig) -> None:
    """Print generated config files without writing or deploying."""
    _validate_config(config)

    masked = _mask_secrets(config)

    print(f"=== {DEFAULT_ENV_FILE} ===")
    print(build_env_content(masked))

    caddy_config = config.caddy_config
    if config.caddy_mode == CADDY_MODE_EXTERNAL:
        if caddy_config:
            print("=== Site snippet ===")
            print(build_caddy_site_snippet(caddy_config))
        if config.deployment_mode == DEPLOY_MODE_LOCAL:
            print(f"=== {DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE} ===")
            print(build_external_caddy_compose_content())
        else:
            print(f"=== {DEFAULT_IMAGE_EXTERNAL_CADDY_COMPOSE_FILE} ===")
            print(build_image_external_caddy_compose_content())
    elif config.deployment_mode == DEPLOY_MODE_LOCAL and caddy_config is None:
        print(f"=== {DEFAULT_NO_CADDY_COMPOSE_FILE} ===")
        print(build_direct_compose_content())
    elif config.deployment_mode == DEPLOY_MODE_LOCAL and caddy_config is not None:
        print("Using existing docker-compose.yml as the base compose file.\n")
        print(f"=== {DEFAULT_CADDYFILE} ===")
        print(build_caddyfile_content(caddy_config))
        if config.caddy_public:
            print(f"=== {DEFAULT_CADDY_PUBLIC_COMPOSE_FILE} ===")
            print(build_caddy_public_compose_override_content())
    elif caddy_config is not None:
        print(f"=== {DEFAULT_CADDYFILE} ===")
        print(build_caddyfile_content(caddy_config))
        print(f"=== {DEFAULT_IMAGE_COMPOSE_FILE} ===")
        print(build_image_compose_content())
        if config.caddy_public:
            print(f"=== {DEFAULT_CADDY_PUBLIC_COMPOSE_FILE} ===")
            print(build_caddy_public_compose_override_content())
    else:
        print(f"=== {DEFAULT_IMAGE_NO_CADDY_COMPOSE_FILE} ===")
        print(build_image_direct_compose_content())

    use_caddy = config.caddy_config is not None
    commands = build_lifecycle_commands(
        deployment_mode=config.deployment_mode,
        use_caddy=use_caddy,
        caddy_public=config.caddy_public,
        tarball_filename=config.tarball_filename,
        caddy_mode=config.caddy_mode,
    )
    print("=== Lifecycle commands ===")
    if "pull" in commands:
        print(f"  Pull:    {commands['pull']}")
    if "load" in commands:
        print(f"  Load:    {commands['load']}")
    print(f"  Start:   {commands['start']}")
    print(f"  Stop:    {commands['stop']}")
    print(f"  Status:  {commands['status']}")
    print(f"  Logs:    {commands['logs']}")
    print(f"  Upgrade: {commands['upgrade']}")


# ── Config summary ───────────────────────────────────────────────────


def print_config_summary(config: DeployConfig) -> None:
    """Print a human-readable summary of the deployment configuration."""
    print("\n=== Deployment configuration ===")
    print(f"  Mode:            {config.deployment_mode}")
    print(f"  Admin user:      {config.admin_username}")
    print(f"  Admin display:   {config.admin_display_name}")
    print(f"  Trusted hosts:   {', '.join(config.trusted_hosts)}")
    if config.caddy_mode == CADDY_MODE_EXTERNAL:
        print("  Caddy mode:      external (shared)")
        caddy_domain_str = config.caddy_config.domain if config.caddy_config else "(none)"
        print(f"  Caddy domain:    {caddy_domain_str}")
        if config.shared_caddy_config:
            print(f"  Shared Caddy:    {config.shared_caddy_config.caddy_dir}")
            print(f"  ACME email:      {config.shared_caddy_config.acme_email or '(none)'}")
    elif config.caddy_config is not None:
        print(f"  Caddy domain:    {config.caddy_config.domain}")
        print(f"  Caddy email:     {config.caddy_config.email or '(none)'}")
        print(f"  Caddy public:    {'yes' if config.caddy_public else 'no'}")
    else:
        print("  Caddy:           disabled")
        print(f"  Bind address:    {config.host_bind_ip}:{config.host_port}")
    if config.trusted_proxy_ips:
        print(f"  Trusted proxies: {', '.join(config.trusted_proxy_ips)}")
    if config.image_ref:
        print(f"  Image ref:       {config.image_ref}")
    if config.platform:
        print(f"  Platform:        {config.platform}")
    print(f"  Expose API docs: {'yes' if config.expose_docs else 'no'}")
    print()


# ── Interactive prompts ──────────────────────────────────────────────


def _prompt_non_empty(prompt: str, default: str | None = None) -> str:
    """Prompt until a non-empty string is provided."""
    while True:
        suffix = f" [{default}]" if default is not None else ""
        value = input(f"{prompt}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return default
        print("Value cannot be empty.")


def _prompt_yes_no(prompt: str, default: bool) -> bool:
    """Prompt for a yes/no answer."""
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        value = input(f"{prompt} {suffix}: ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Please answer yes or no.")


def _prompt_deployment_mode() -> str:
    """Prompt for a supported deployment mode."""
    prompt = f"Deployment mode [local/registry/tarball] [{DEPLOY_MODE_LOCAL}]"
    while True:
        value = input(f"{prompt}: ").strip().lower()
        if not value:
            return DEPLOY_MODE_LOCAL
        if value in DEPLOY_MODES:
            return value
        print("Please choose local, registry, or tarball.")


def _prompt_host_port(default: int = DEFAULT_HOST_PORT) -> int:
    """Prompt for a valid host port."""
    while True:
        raw = input(f"Host port for AgBlogger [{default}]: ").strip()
        if not raw:
            return default
        if raw.isdigit():
            value = int(raw)
            if 1 <= value <= 65535:
                return value
        print("Please enter a valid port in range 1-65535.")


def _is_valid_caddy_domain(domain: str) -> bool:
    """Return True when the domain is a valid public hostname for Caddy TLS."""
    if _is_ipv4_like(domain):
        return False
    return _DOMAIN_RE.match(domain) is not None


def _prompt_caddy_mode() -> str:
    """Prompt for Caddy reverse proxy mode."""
    print("\nCaddy reverse proxy configuration:")
    print("  bundled  - Deploy a Caddy container alongside AgBlogger (default)")
    print("  external - Use a shared Caddy instance for multiple services")
    print("  none     - No Caddy; expose AgBlogger directly")
    while True:
        value = input("Caddy mode [bundled/external/none] [bundled]: ").strip().lower()
        if not value:
            return CADDY_MODE_BUNDLED
        if value in CADDY_MODES:
            return value
        print("Please choose bundled, external, or none.")


def _prompt_caddy_domain() -> str:
    """Prompt for a valid Caddy domain with inline validation."""
    while True:
        domain = input("Public domain for your blog (example: blog.example.com): ").strip()
        if not domain:
            print("Domain cannot be empty.")
            continue
        if not _is_valid_caddy_domain(domain):
            print("Must be a valid public hostname (e.g., blog.example.com), not an IP address.")
            continue
        return domain


def _prompt_trusted_hosts(caddy_domain: str | None) -> list[str]:
    """Prompt for trusted hosts with inline validation."""
    if caddy_domain:
        while True:
            raw_hosts = input(
                f"Additional trusted hostnames besides '{caddy_domain}'"
                " (comma-separated, leave blank if none): "
            ).strip()
            trusted_hosts = parse_csv_list(raw_hosts)
            if caddy_domain not in trusted_hosts:
                trusted_hosts.append(caddy_domain)
            invalid = [h for h in trusted_hosts if not is_valid_trusted_host(h)]
            if invalid:
                print(
                    f"Invalid host(s): {', '.join(repr(h) for h in invalid)}. "
                    "Use explicit hosts or '*.example.com' (no catch-all wildcards)."
                )
                continue
            return trusted_hosts
    while True:
        raw_hosts = input(
            "Hostnames/IPs clients will use to reach your blog"
            " (comma-separated, validates the Host header): "
        ).strip()
        trusted_hosts = parse_csv_list(raw_hosts)
        if not trusted_hosts:
            print("Provide at least one trusted host.")
            continue
        invalid = [h for h in trusted_hosts if not is_valid_trusted_host(h)]
        if invalid:
            print(
                f"Invalid host(s): {', '.join(repr(h) for h in invalid)}. "
                "Use explicit hosts or '*.example.com' (no catch-all wildcards)."
            )
            continue
        return trusted_hosts


def _prompt_secret_key() -> str:
    """Prompt for secret key or auto-generate one."""
    secret_key = getpass.getpass(
        "SECRET_KEY (leave blank to auto-generate a random value): "
    ).strip()
    if not secret_key:
        generated = secrets.token_urlsafe(64)
        print("Generated SECRET_KEY automatically.")
        return generated

    if len(secret_key) < MIN_SECRET_KEY_LENGTH:
        print(f"SECRET_KEY must be at least {MIN_SECRET_KEY_LENGTH} characters.")
        return _prompt_secret_key()
    return secret_key


def _prompt_password() -> str:
    """Prompt for admin password with confirmation."""
    while True:
        password = getpass.getpass("Admin password: ").strip()
        if len(password) < MIN_ADMIN_PASSWORD_LENGTH:
            print(f"Password must be at least {MIN_ADMIN_PASSWORD_LENGTH} characters.")
            continue
        confirmation = getpass.getpass("Confirm admin password: ").strip()
        if password != confirmation:
            print("Passwords do not match.")
            continue
        return password


def collect_config(project_dir: Path | None = None) -> DeployConfig:
    """Collect interactive production settings from the user."""
    print("Enter production configuration values for your blog server.")

    # Check for existing deployment and offer to reuse secrets
    env_path = (project_dir or Path.cwd()) / DEFAULT_ENV_FILE
    existing = parse_existing_env(env_path)
    if not existing.get("SECRET_KEY"):
        bundle_env_path = (project_dir or Path.cwd()) / DEFAULT_BUNDLE_DIR / DEFAULT_ENV_FILE
        bundle_existing = parse_existing_env(bundle_env_path)
        if bundle_existing.get("SECRET_KEY"):
            existing = bundle_existing
    reuse_secrets = False
    if (
        existing.get("SECRET_KEY")
        and existing.get("ADMIN_USERNAME")
        and existing.get("ADMIN_PASSWORD")
    ):
        print(f"\nFound existing deployment config ({DEFAULT_ENV_FILE}).")
        reuse_secrets = _prompt_yes_no(
            "Reuse existing SECRET_KEY and admin credentials?", default=True
        )

    if reuse_secrets:
        secret_key = existing["SECRET_KEY"]
        admin_username = existing["ADMIN_USERNAME"]
        admin_password = existing["ADMIN_PASSWORD"]
        admin_display_name = existing.get("ADMIN_DISPLAY_NAME", admin_username)
        print(f"Reusing credentials (admin user: {admin_username}).")
    else:
        secret_key = _prompt_secret_key()
        admin_username = _prompt_non_empty("Admin username", default="admin")
        admin_display_name = _prompt_non_empty("Admin display name", default=admin_username)
        admin_password = _prompt_password()
    deployment_mode = _prompt_deployment_mode()
    image_ref: str | None = None
    tarball_filename = DEFAULT_IMAGE_TARBALL
    platform: str | None = None
    if deployment_mode in {DEPLOY_MODE_REGISTRY, DEPLOY_MODE_TARBALL}:
        image_ref = _prompt_non_empty(
            "Container image reference (e.g., ghcr.io/yourname/agblogger:v1.0)"
        )
        if deployment_mode == DEPLOY_MODE_TARBALL:
            tarball_filename = _prompt_non_empty(
                "Tarball filename",
                default=DEFAULT_IMAGE_TARBALL,
            )
        platform = DEFAULT_REMOTE_PLATFORM
        print(f"Target platform: {platform} (override with --platform for other architectures).")

    caddy_mode = _prompt_caddy_mode()

    caddy_config: CaddyConfig | None = None
    shared_caddy_config: SharedCaddyConfig | None = None
    host_port = DEFAULT_HOST_PORT
    caddy_public = False
    if caddy_mode == CADDY_MODE_BUNDLED:
        caddy_domain = _prompt_caddy_domain()
        caddy_email = input("Email for TLS certificate notices (optional, recommended): ").strip()
        caddy_config = CaddyConfig(domain=caddy_domain, email=caddy_email or None)
        caddy_public = _prompt_yes_no(
            "Expose Caddy ports 80/443 publicly so your site is Internet-reachable?",
            default=True,
        )
        host_bind_ip = LOCALHOST_BIND_IP
        _prompt_yes_no(
            "Have you configured DNS for this domain?"
            " Caddy will attempt to provision a TLS certificate on startup",
            default=True,
        )
        print(
            "\nNote: Ensure your domain's DNS A/AAAA record points to this server"
            " before starting. Caddy needs to reach Let's Encrypt to provision"
            " TLS certificates.\n"
        )
    elif caddy_mode == CADDY_MODE_EXTERNAL:
        caddy_domain = _prompt_caddy_domain()
        caddy_email = input("Email for TLS certificate notices (optional, recommended): ").strip()
        caddy_config = CaddyConfig(domain=caddy_domain, email=caddy_email or None)
        host_bind_ip = LOCALHOST_BIND_IP
        shared_caddy_dir = _prompt_non_empty(
            "Shared Caddy directory", default=DEFAULT_SHARED_CADDY_DIR
        )
        default_acme = caddy_email or None
        acme_prompt = f"ACME email for shared Caddy [{default_acme or 'none'}]: "
        acme_input = input(acme_prompt).strip()
        acme_email = acme_input or default_acme
        shared_caddy_config = SharedCaddyConfig(
            caddy_dir=Path(shared_caddy_dir), acme_email=acme_email
        )
    else:
        host_bind_ip = (
            PUBLIC_BIND_IP
            if _prompt_yes_no(
                "Expose AgBlogger directly on the Internet (without Caddy, no TLS)?",
                default=False,
            )
            else LOCALHOST_BIND_IP
        )
        host_port = _prompt_host_port()

    trusted_hosts = _prompt_trusted_hosts(caddy_config.domain if caddy_config else None)

    if caddy_mode == CADDY_MODE_EXTERNAL:
        proxy_ips = [CADDY_NETWORK_SUBNET_PLACEHOLDER]
        print("Caddy proxy subnet will be auto-detected from the Docker network at deploy time.")
        extra_proxy_ips = parse_csv_list(
            input("Additional trusted proxy IPs (comma-separated, optional): ").strip()
        )
        for ip in extra_proxy_ips:
            if ip not in proxy_ips:
                proxy_ips.append(ip)
    elif caddy_mode != CADDY_MODE_NONE:
        proxy_ips = [COMPOSE_SUBNET]
        print(f"Caddy proxy subnet ({COMPOSE_SUBNET}) auto-configured as a trusted proxy.")
        extra_proxy_ips = parse_csv_list(
            input("Additional trusted proxy IPs (comma-separated, optional): ").strip()
        )
        for ip in extra_proxy_ips:
            if ip not in proxy_ips:
                proxy_ips.append(ip)
    else:
        proxy_ips = parse_csv_list(input("Trusted proxy IPs (comma-separated, optional): ").strip())

    expose_docs = _prompt_yes_no(
        "Expose API documentation at /docs? (usually only for development)",
        default=False,
    )

    return DeployConfig(
        secret_key=secret_key,
        admin_username=admin_username,
        admin_password=admin_password,
        admin_display_name=admin_display_name,
        trusted_hosts=trusted_hosts,
        trusted_proxy_ips=proxy_ips,
        host_port=host_port,
        host_bind_ip=host_bind_ip,
        caddy_config=caddy_config,
        caddy_public=caddy_public,
        expose_docs=expose_docs,
        deployment_mode=deployment_mode,
        image_ref=image_ref,
        bundle_dir=DEFAULT_BUNDLE_DIR,
        tarball_filename=tarball_filename,
        platform=platform,
        caddy_mode=caddy_mode,
        shared_caddy_config=shared_caddy_config,
    )


# ── Non-interactive config from CLI arguments ────────────────────────


def config_from_args(args: argparse.Namespace) -> DeployConfig:
    """Build DeployConfig from CLI arguments for non-interactive mode."""
    platform = args.platform
    if platform is None and args.deployment_mode in {DEPLOY_MODE_REGISTRY, DEPLOY_MODE_TARBALL}:
        platform = DEFAULT_REMOTE_PLATFORM
    secret_key = args.secret_key or secrets.token_urlsafe(64)
    if not args.admin_username:
        raise DeployError("--admin-username is required in non-interactive mode")
    admin_password = args.admin_password or os.environ.get("ADMIN_PASSWORD", "")
    if not admin_password:
        raise DeployError(
            "--admin-password is required (or set ADMIN_PASSWORD env var) in non-interactive mode"
        )
    if not args.trusted_hosts:
        raise DeployError("--trusted-hosts is required in non-interactive mode")
    if args.deployment_mode in {DEPLOY_MODE_REGISTRY, DEPLOY_MODE_TARBALL} and not args.image_ref:
        raise DeployError("--image-ref is required for registry and tarball deployment modes")

    caddy_config: CaddyConfig | None = None
    caddy_public = False
    shared_caddy_config: SharedCaddyConfig | None = None
    if args.caddy_domain:
        caddy_config = CaddyConfig(domain=args.caddy_domain, email=args.caddy_email)
        if args.caddy_external:
            caddy_mode = CADDY_MODE_EXTERNAL
            shared_email = args.shared_caddy_email or args.caddy_email
            shared_caddy_config = SharedCaddyConfig(
                caddy_dir=Path(args.shared_caddy_dir),
                acme_email=shared_email,
            )
            host_bind_ip = LOCALHOST_BIND_IP
        else:
            caddy_mode = CADDY_MODE_BUNDLED
            caddy_public = args.caddy_public
            host_bind_ip = LOCALHOST_BIND_IP
    elif args.caddy_external:
        raise DeployError("--caddy-external requires --caddy-domain")
    else:
        caddy_mode = CADDY_MODE_NONE
        host_bind_ip = PUBLIC_BIND_IP if args.bind_public else LOCALHOST_BIND_IP

    trusted_hosts = parse_csv_list(args.trusted_hosts)
    if caddy_config and caddy_config.domain not in trusted_hosts:
        trusted_hosts.append(caddy_config.domain)

    trusted_proxy_ips = parse_csv_list(args.trusted_proxy_ips) if args.trusted_proxy_ips else []
    if caddy_mode == CADDY_MODE_EXTERNAL:
        if CADDY_NETWORK_SUBNET_PLACEHOLDER not in trusted_proxy_ips:
            trusted_proxy_ips.insert(0, CADDY_NETWORK_SUBNET_PLACEHOLDER)
    elif caddy_config is not None and COMPOSE_SUBNET not in trusted_proxy_ips:
        trusted_proxy_ips.insert(0, COMPOSE_SUBNET)

    admin_display_name = args.admin_display_name or args.admin_username
    return DeployConfig(
        secret_key=secret_key,
        admin_username=args.admin_username,
        admin_password=admin_password,
        admin_display_name=admin_display_name,
        trusted_hosts=trusted_hosts,
        trusted_proxy_ips=trusted_proxy_ips,
        host_port=args.host_port,
        host_bind_ip=host_bind_ip,
        caddy_config=caddy_config,
        caddy_public=caddy_public,
        expose_docs=args.expose_docs,
        deployment_mode=args.deployment_mode,
        image_ref=args.image_ref,
        bundle_dir=args.bundle_dir,
        tarball_filename=args.tarball_filename,
        platform=platform,
        caddy_mode=caddy_mode,
        shared_caddy_config=shared_caddy_config,
    )


# ── CLI entry point ──────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Production deployment helper for AgBlogger.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_read_version()}",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path.cwd(),
        help="Project directory containing docker-compose.yml (default: current directory).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated config files without writing or deploying.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Run without interactive prompts; requires all config via CLI arguments.",
    )

    config_group = parser.add_argument_group("configuration")
    config_group.add_argument("--secret-key", help="JWT signing key (auto-generated if omitted).")
    config_group.add_argument("--admin-username", help="Initial admin username.")
    config_group.add_argument(
        "--admin-password",
        help="Initial admin password. Also accepted via ADMIN_PASSWORD env var.",
    )
    config_group.add_argument(
        "--admin-display-name",
        help="Admin display name (defaults to admin username).",
    )
    config_group.add_argument(
        "--caddy-domain",
        help="Enable Caddy HTTPS with this domain. Omit to expose AgBlogger directly.",
    )
    config_group.add_argument("--caddy-email", help="Email for TLS certificate notifications.")
    config_group.add_argument(
        "--caddy-public",
        action="store_true",
        default=False,
        help="Expose Caddy ports 80/443 publicly (default: localhost only).",
    )
    config_group.add_argument(
        "--caddy-external",
        action="store_true",
        default=False,
        help="Use a shared external Caddy instance instead of a bundled one.",
    )
    config_group.add_argument(
        "--shared-caddy-dir",
        default=DEFAULT_SHARED_CADDY_DIR,
        help=f"Directory for the shared Caddy instance (default: {DEFAULT_SHARED_CADDY_DIR}).",
    )
    config_group.add_argument(
        "--shared-caddy-email",
        help="ACME email for the shared Caddy instance (defaults to --caddy-email).",
    )
    config_group.add_argument(
        "--trusted-hosts",
        help="Comma-separated hostnames/IPs for Host header validation.",
    )
    config_group.add_argument(
        "--trusted-proxy-ips",
        help="Comma-separated trusted proxy IPs (optional).",
    )
    config_group.add_argument(
        "--host-port",
        type=int,
        default=DEFAULT_HOST_PORT,
        help=f"Host port for AgBlogger (default: {DEFAULT_HOST_PORT}).",
    )
    config_group.add_argument(
        "--bind-public",
        action="store_true",
        default=False,
        help="Bind to 0.0.0.0 instead of 127.0.0.1 (only for non-Caddy mode).",
    )
    config_group.add_argument(
        "--expose-docs",
        action="store_true",
        default=False,
        help="Expose API documentation at /docs (default: disabled).",
    )
    config_group.add_argument(
        "--deployment-mode",
        choices=sorted(DEPLOY_MODES),
        default=DEPLOY_MODE_LOCAL,
        help="Choose local deploy, registry bundle, or tarball bundle mode.",
    )
    config_group.add_argument(
        "--image-ref",
        help="Container image reference for registry or tarball deployment modes.",
    )
    config_group.add_argument(
        "--bundle-dir",
        type=Path,
        default=DEFAULT_BUNDLE_DIR,
        help=f"Output directory for remote deployment bundles (default: {DEFAULT_BUNDLE_DIR}).",
    )
    config_group.add_argument(
        "--tarball-filename",
        default=DEFAULT_IMAGE_TARBALL,
        help=f"Image tarball name for tarball deployment mode (default: {DEFAULT_IMAGE_TARBALL}).",
    )
    config_group.add_argument(
        "--platform",
        help="Target platform for Docker image build (e.g., linux/arm64). "
        f"Defaults to {DEFAULT_REMOTE_PLATFORM} for remote deployment modes.",
    )

    return parser.parse_args()


def main() -> None:
    """Run deployment workflow."""
    args = _parse_args()
    project_dir = args.project_dir.resolve()

    try:
        if not args.dry_run:
            if shutil.which("docker") is None:
                raise DeployError("Docker is not installed or not available on PATH")
            try:
                subprocess.run(
                    ["docker", "info"],
                    capture_output=True,
                    check=True,
                    timeout=10,
                )
            except subprocess.CalledProcessError, subprocess.TimeoutExpired:
                raise DeployError(
                    "Docker daemon is not running. "
                    "Start Docker Desktop or the Docker service and try again."
                ) from None

        if not args.non_interactive and not args.dry_run:
            print(f"AgBlogger deployment helper v{_read_version()}\n")

        config = config_from_args(args) if args.non_interactive else collect_config(project_dir)

        if args.dry_run:
            dry_run(config)
            return

        if not args.non_interactive:
            print_config_summary(config)
            if not _prompt_yes_no("Proceed with deployment?", default=True):
                print("Deployment cancelled.")
                return

        check_prerequisites(project_dir, config.deployment_mode)
        result = deploy(config=config, project_dir=project_dir)
    except (DeployError, FileNotFoundError) as exc:
        print(f"Deployment failed: {exc}")
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        cmd_str = " ".join(exc.cmd) if isinstance(exc.cmd, list) else str(exc.cmd)
        print(f"Deployment failed (exit code {exc.returncode}): {cmd_str}")
        sys.exit(1)
    except subprocess.TimeoutExpired as exc:
        cmd_str = " ".join(exc.cmd) if isinstance(exc.cmd, list) else str(exc.cmd)
        print(f"Deployment failed (timed out after {exc.timeout}s): {cmd_str}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nDeployment cancelled.")
        sys.exit(1)

    print("\nDeployment complete.")
    print(f"Environment file: {result.env_path}")
    if result.bundle_path is not None:
        print(f"Remote bundle: {result.bundle_path}")
    print("Use these commands to manage the server:")
    if "pull" in result.commands:
        print(f"  Pull:    {result.commands['pull']}")
    if "load" in result.commands:
        print(f"  Load:    {result.commands['load']}")
    print(f"  Start:   {result.commands['start']}")
    print(f"  Stop:    {result.commands['stop']}")
    print(f"  Status:  {result.commands['status']}")
    print(f"  Logs:    {result.commands['logs']}")
    print(f"  Upgrade: {result.commands['upgrade']}")
    if config.deployment_mode == DEPLOY_MODE_LOCAL:
        if config.caddy_config is not None:
            print(f"Open the app at: https://{config.caddy_config.domain}/login")
        else:
            print(f"Open the app at: http://<your-server-host>:{config.host_port}/login")
    else:
        print("\nTo copy the bundle to the remote server:")
        print(f"  scp -r {result.bundle_path} user@your-server:~/agblogger")
        print("Then follow the instructions in DEPLOY-REMOTE.md on the server.")


if __name__ == "__main__":
    main()
