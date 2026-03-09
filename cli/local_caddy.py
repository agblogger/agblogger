"""Manage the local Caddy-backed packaged AgBlogger profile."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cli import repo_root
from cli.dev_server import validate_port
from cli.zap_scan import (
    DEFAULT_LOCAL_CADDY_PORT,
    ZapScanError,
    check_prerequisites,
    local_caddy_profile_health,
    start_local_caddy_profile,
    stop_local_caddy_profile,
    write_local_caddy_env,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    root = repo_root()
    for command_name in ("start", "stop"):
        command_parser = subparsers.add_parser(command_name)
        command_parser.add_argument("--project-dir", type=Path, default=root)
        command_parser.add_argument("--localdir", type=Path, default=root / ".local")
        command_parser.add_argument("--caddy-port", default=str(DEFAULT_LOCAL_CADDY_PORT))

    health_parser = subparsers.add_parser("health")
    health_parser.add_argument("--caddy-port", default=str(DEFAULT_LOCAL_CADDY_PORT))

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        caddy_port = validate_port(args.caddy_port)
        if args.command == "health":
            return 0 if local_caddy_profile_health(caddy_port) else 1

        project_dir = args.project_dir.resolve()
        localdir = args.localdir.resolve()
        check_prerequisites(project_dir)
        env_file = write_local_caddy_env(localdir)

        if args.command == "start":
            if local_caddy_profile_health(caddy_port):
                print(f"Local Caddy profile already healthy at http://127.0.0.1:{caddy_port}/")
                return 0
            print(f"Starting local Caddy profile on http://127.0.0.1:{caddy_port}/")
            start_local_caddy_profile(project_dir, env_file, caddy_port)
            return 0

        if args.command == "stop":
            print("Stopping local Caddy profile")
            stop_local_caddy_profile(project_dir, env_file)
            return 0
    except (ValueError, ZapScanError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
