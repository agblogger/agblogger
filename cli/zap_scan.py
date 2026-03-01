"""Run OWASP ZAP packaged scans against the local AgBlogger dev server."""

from __future__ import annotations

import argparse
import asyncio
import platform
import shutil
import sys
from pathlib import Path, PurePosixPath
from typing import Literal

from cli import repo_root
from cli.dev_server import (
    DevServerState,
    health_dev_server,
    remove_state,
    start_dev_server,
    stop_dev_server,
    validate_port,
)

DEFAULT_ZAP_IMAGE = "ghcr.io/zaproxy/zaproxy:stable"

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
    frontend_port: int,
    minutes: int | None,
    system_name: str | None = None,
    image: str = DEFAULT_ZAP_IMAGE,
) -> list[str]:
    """Build the Docker command for a packaged ZAP scan."""
    reports = _report_paths(scan_mode)
    current_system = system_name or platform.system()

    script_name = "zap-baseline.py" if scan_mode == "baseline" else "zap-full-scan.py"
    target_url = f"http://host.docker.internal:{frontend_port}/"
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


def _start_dev_server_for_scan(
    localdir: Path, backend_port: int, frontend_port: int
) -> DevServerState:
    """Start the dev server, retrying once if stale state blocks startup."""
    try:
        return start_dev_server(localdir, backend_port, frontend_port)
    except RuntimeError as exc:
        if "Dev server is already running" not in str(exc):
            raise
        print("Detected stale dev-server state, clearing it and retrying once...")
        try:
            _stopped, message = stop_dev_server(localdir)
            print(message)
        except PermissionError:
            print("Unable to stop the recorded dev server; removing stale state and retrying...")
            remove_state(localdir)
        return start_dev_server(localdir, backend_port, frontend_port)


def _stop_dev_server_for_scan(localdir: Path) -> None:
    """Stop the dev server started for a scan, tolerating cleanup permission issues."""
    try:
        _stopped, message = stop_dev_server(localdir)
        print(message)
    except PermissionError:
        print("Unable to stop the dev server after the scan; removing recorded state instead...")
        remove_state(localdir)


def run_zap_scan(
    *,
    scan_mode: ScanMode,
    project_dir: Path,
    localdir: Path,
    backend_port: int,
    frontend_port: int,
    minutes: int | None,
) -> int:
    """Run a packaged ZAP scan against the frontend dev server."""
    if minutes is not None and minutes < 1:
        raise ValueError("minutes must be greater than zero")

    check_prerequisites(project_dir)
    reports = _report_paths(scan_mode)
    report_dir = project_dir / reports["dir"]
    report_dir.mkdir(parents=True, exist_ok=True)

    healthy, actual_backend_port, actual_frontend_port = health_dev_server(
        localdir, backend_port, frontend_port
    )
    started_dev_server = False

    try:
        if not healthy:
            print("Starting dev server for ZAP scan...")
            state = _start_dev_server_for_scan(localdir, backend_port, frontend_port)
            started_dev_server = True
            actual_backend_port = state.backend_port
            actual_frontend_port = state.frontend_port

        print(
            f"Running ZAP {scan_mode} scan against "
            f"http://127.0.0.1:{actual_frontend_port}/ "
            f"(backend :{actual_backend_port}, frontend :{actual_frontend_port})"
        )
        print(f"Writing ZAP reports to {report_dir}")
        command = build_docker_command(
            scan_mode=scan_mode,
            project_dir=project_dir,
            frontend_port=actual_frontend_port,
            minutes=minutes,
        )
        return run_command(command, project_dir)
    finally:
        if started_dev_server:
            _stop_dev_server_for_scan(localdir)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    root = repo_root()
    for command_name in ("baseline", "full"):
        command_parser = subparsers.add_parser(command_name)
        command_parser.add_argument("--project-dir", type=Path, default=root)
        command_parser.add_argument("--localdir", type=Path, default=root / ".local")
        command_parser.add_argument("--backend-port", default="8000")
        command_parser.add_argument("--frontend-port", default="5173")
        command_parser.add_argument("--minutes", type=int)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        backend_port = validate_port(args.backend_port)
        frontend_port = validate_port(args.frontend_port)
        return run_zap_scan(
            scan_mode=args.command,
            project_dir=args.project_dir.resolve(),
            localdir=args.localdir.resolve(),
            backend_port=backend_port,
            frontend_port=frontend_port,
            minutes=args.minutes,
        )
    except (ValueError, ZapScanError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
