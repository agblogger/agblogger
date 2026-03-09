"""Run OWASP ZAP packaged scans against a local Caddy-served AgBlogger build."""

from __future__ import annotations

import argparse
import asyncio
import http.client
import platform
import shutil
import sys
import time
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import urlsplit

from cli import repo_root
from cli.dev_server import validate_port

DEFAULT_ZAP_IMAGE = "ghcr.io/zaproxy/zaproxy:stable"
DEFAULT_LOCAL_CADDY_PORT = 8080
LOCAL_CADDY_PROJECT_NAME = "agblogger-caddy-local"
LOCAL_CADDY_ENV_FILENAME = "caddy-local.env"
LOCAL_CADDY_COMPOSE_OVERRIDE = "docker-compose.caddy-local.yml"
LOCAL_CADDY_STARTUP_TIMEOUT_SECONDS = 120.0

ScanMode = Literal["baseline", "full"]


class ZapScanError(RuntimeError):
    """Raised when the ZAP workflow cannot be started."""


def _report_paths(scan_mode: ScanMode) -> dict[str, PurePosixPath]:
    report_dir = PurePosixPath("reports") / "zap" / scan_mode
    return {
        "dir": report_dir,
        "html": report_dir / "report.html",
        "markdown": report_dir / "report.md",
        "json": report_dir / "report.json",
        "xml": report_dir / "report.xml",
    }


def build_docker_command(
    *,
    scan_mode: ScanMode,
    project_dir: Path,
    caddy_port: int,
    minutes: int | None,
    system_name: str | None = None,
    image: str = DEFAULT_ZAP_IMAGE,
) -> list[str]:
    """Build the Docker command for a packaged ZAP scan."""
    reports = _report_paths(scan_mode)
    current_system = system_name or platform.system()

    script_name = "zap-baseline.py" if scan_mode == "baseline" else "zap-full-scan.py"
    target_url = f"http://host.docker.internal:{caddy_port}/"
    command = ["/usr/bin/env", "docker", "run", "--rm"]

    if current_system == "Linux":
        command.extend(["--add-host", "host.docker.internal:host-gateway"])

    command.extend(
        [
            "-v",
            f"{project_dir}:/zap/wrk:rw",
            image,
            script_name,
            "-t",
            target_url,
            "-j",
            "-I",
            "-r",
            str(reports["html"]),
            "-w",
            str(reports["markdown"]),
            "-J",
            str(reports["json"]),
            "-x",
            str(reports["xml"]),
        ]
    )
    if minutes is not None:
        command.extend(["-m", str(minutes)])
    return command


async def _run_command(command: list[str], cwd: Path) -> int:
    """Run a command with stdio inherited from the parent process."""
    try:
        process = await asyncio.create_subprocess_exec(*command, cwd=str(cwd))
    except FileNotFoundError as exc:
        msg = f"Command not found: {command[0]}"
        raise ZapScanError(msg) from exc
    return await process.wait()


def run_command(command: list[str], cwd: Path) -> int:
    """Run a command synchronously."""
    return asyncio.run(_run_command(command, cwd))


def check_prerequisites(project_dir: Path) -> None:
    """Validate required host dependencies before running a scan."""
    if shutil.which("docker") is None:
        raise ZapScanError("Docker is not installed or not available on PATH")

    docker_version = run_command(["/usr/bin/env", "docker", "--version"], project_dir)
    if docker_version != 0:
        raise ZapScanError("Failed to run 'docker --version'")

    compose_version = run_command(["/usr/bin/env", "docker", "compose", "version"], project_dir)
    if compose_version != 0:
        raise ZapScanError("Failed to run 'docker compose version'")


def _local_caddy_env_path(localdir: Path) -> Path:
    return localdir / LOCAL_CADDY_ENV_FILENAME


def write_local_caddy_env(localdir: Path) -> Path:
    """Write the local env file used by the dedicated Caddy-backed profile."""
    localdir.mkdir(parents=True, exist_ok=True)
    env_path = _local_caddy_env_path(localdir)
    env_path.write_text(
        "\n".join(
            (
                "SECRET_KEY=zap-local-secret-key-0123456789abcdef0123456789abcdef",
                "ADMIN_USERNAME=admin",
                "ADMIN_PASSWORD=zap-local-admin-password",
                'TRUSTED_HOSTS=["localhost","127.0.0.1","host.docker.internal"]',
                "TRUSTED_PROXY_IPS=[]",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    return env_path


def build_local_caddy_compose_command(
    *,
    project_dir: Path,
    env_file: Path,
    args: list[str],
) -> list[str]:
    """Build the docker compose command for the local Caddy-backed profile."""
    return [
        "/usr/bin/env",
        "docker",
        "compose",
        "-p",
        LOCAL_CADDY_PROJECT_NAME,
        "--env-file",
        str(env_file),
        "-f",
        str(project_dir / "docker-compose.yml"),
        "-f",
        str(project_dir / LOCAL_CADDY_COMPOSE_OVERRIDE),
        *args,
    ]


def _is_http_ready(url: str) -> bool:
    """Return whether an HTTP endpoint responds successfully."""
    parts = urlsplit(url)
    if parts.hostname is None:
        return False
    port = parts.port
    if port is None:
        port = 443 if parts.scheme == "https" else 80
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"

    connection_cls = (
        http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    )
    connection: http.client.HTTPConnection | http.client.HTTPSConnection | None = None
    try:
        connection = connection_cls(parts.hostname, port, timeout=1.0)
        connection.request("GET", path)
        response = connection.getresponse()
        return 200 <= response.status < 500
    except OSError:
        return False
    finally:
        if connection is not None:
            connection.close()


def local_caddy_profile_health(caddy_port: int) -> bool:
    """Return whether the local Caddy-backed profile is healthy."""
    backend_ok = _is_http_ready(f"http://127.0.0.1:{caddy_port}/api/health")
    frontend_ok = _is_http_ready(f"http://127.0.0.1:{caddy_port}/")
    status = "✓ healthy" if backend_ok and frontend_ok else "✗ unreachable"
    print(f"Caddy-backed app (:{caddy_port}): {status}")
    return backend_ok and frontend_ok


def start_local_caddy_profile(project_dir: Path, env_file: Path, caddy_port: int) -> None:
    """Start the dedicated local Caddy-backed profile and wait for it to become healthy."""
    up_command = build_local_caddy_compose_command(
        project_dir=project_dir,
        env_file=env_file,
        args=["up", "-d", "--build"],
    )
    exit_code = run_command(up_command, project_dir)
    if exit_code != 0:
        raise ZapScanError("Failed to start local Caddy profile")

    deadline = time.monotonic() + LOCAL_CADDY_STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if local_caddy_profile_health(caddy_port):
            return
        time.sleep(1.0)
    raise ZapScanError("Timed out waiting for the local Caddy profile to become healthy")


def stop_local_caddy_profile(project_dir: Path, env_file: Path) -> None:
    """Stop the dedicated local Caddy-backed profile."""
    down_command = build_local_caddy_compose_command(
        project_dir=project_dir,
        env_file=env_file,
        args=["down", "-v", "--remove-orphans"],
    )
    exit_code = run_command(down_command, project_dir)
    if exit_code != 0:
        raise ZapScanError("Failed to stop local Caddy profile")


def run_zap_scan(
    *,
    scan_mode: ScanMode,
    project_dir: Path,
    localdir: Path,
    caddy_port: int,
    minutes: int | None,
) -> int:
    """Run a packaged ZAP scan against the local Caddy-served build."""
    if minutes is not None and minutes < 1:
        raise ValueError("minutes must be greater than zero")

    check_prerequisites(project_dir)
    reports = _report_paths(scan_mode)
    report_dir = project_dir / reports["dir"]
    report_dir.mkdir(parents=True, exist_ok=True)
    env_file = write_local_caddy_env(localdir)

    healthy = local_caddy_profile_health(caddy_port)
    started_local_caddy_profile = False

    try:
        if not healthy:
            print("Starting local Caddy profile for ZAP scan...")
            start_local_caddy_profile(project_dir, env_file, caddy_port)
            started_local_caddy_profile = True

        print(
            f"Running ZAP {scan_mode} scan against "
            f"http://127.0.0.1:{caddy_port}/ "
            f"(Caddy :{caddy_port})"
        )
        print(f"Writing ZAP reports to {report_dir}")
        command = build_docker_command(
            scan_mode=scan_mode,
            project_dir=project_dir,
            caddy_port=caddy_port,
            minutes=minutes,
        )
        return run_command(command, project_dir)
    finally:
        if started_local_caddy_profile:
            stop_local_caddy_profile(project_dir, env_file)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    root = repo_root()
    for command_name in ("baseline", "full"):
        command_parser = subparsers.add_parser(command_name)
        command_parser.add_argument("--project-dir", type=Path, default=root)
        command_parser.add_argument("--localdir", type=Path, default=root / ".local")
        command_parser.add_argument("--caddy-port", default=str(DEFAULT_LOCAL_CADDY_PORT))
        command_parser.add_argument("--minutes", type=int)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        caddy_port = validate_port(args.caddy_port)
        return run_zap_scan(
            scan_mode=args.command,
            project_dir=args.project_dir.resolve(),
            localdir=args.localdir.resolve(),
            caddy_port=caddy_port,
            minutes=args.minutes,
        )
    except (ValueError, ZapScanError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
