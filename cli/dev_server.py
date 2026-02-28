"""Development server process manager for backend and frontend."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import signal
import socket
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

STATE_FILE_NAME: Final = "dev-server.json"
BACKEND_PORT_FILE_NAME: Final = "backend.port"
FRONTEND_PORT_FILE_NAME: Final = "frontend.port"
LEGACY_PID_FILE_NAME: Final = "dev.pid"
BACKEND_LOG_FILE_NAME: Final = "backend.log"
FRONTEND_LOG_FILE_NAME: Final = "frontend.log"
DEFAULT_STARTUP_TIMEOUT_SECONDS: Final = 30.0
DEFAULT_POLL_INTERVAL_SECONDS: Final = 0.2
TERMINATE_TIMEOUT_SECONDS: Final = 5.0
TAIL_LINES: Final = 20


@dataclass(frozen=True)
class ServiceConfig:
    """Runtime configuration for a single managed service."""

    name: str
    command: list[str]
    env: dict[str, str]
    health_url: str
    log_path: Path


@dataclass(frozen=True)
class RunningService:
    """A started service process and its configuration."""

    config: ServiceConfig
    pid: int


@dataclass(frozen=True)
class DevServerState:
    """Persisted state for the development server."""

    backend_pid: int
    frontend_pid: int
    backend_port: int
    frontend_port: int
    backend_log: str
    frontend_log: str


def validate_port(port_text: str) -> int:
    """Validate a TCP port from CLI text input."""
    try:
        port = int(port_text)
    except ValueError as exc:
        msg = f"Invalid TCP port: {port_text} (must be 1-65535)"
        raise ValueError(msg) from exc
    if port < 1 or port > 65535:
        msg = f"Invalid TCP port: {port} (must be 1-65535)"
        raise ValueError(msg)
    return port


def is_port_in_use(port: int) -> bool:
    """Return whether a local TCP port is already bound on 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def find_free_port(preferred_port: int, blocked_port: int | None = None) -> int:
    """Find the preferred TCP port or the next available one."""
    for port in range(preferred_port, 65536):
        if blocked_port is not None and port == blocked_port:
            continue
        if not is_port_in_use(port):
            return port
    msg = "no free TCP port found in range"
    raise RuntimeError(msg)


def state_file_path(localdir: Path) -> Path:
    """Return the persisted state file path."""
    return localdir / STATE_FILE_NAME


def _backend_port_file(localdir: Path) -> Path:
    return localdir / BACKEND_PORT_FILE_NAME


def _frontend_port_file(localdir: Path) -> Path:
    return localdir / FRONTEND_PORT_FILE_NAME


def _legacy_pid_file(localdir: Path) -> Path:
    return localdir / LEGACY_PID_FILE_NAME


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def load_state(localdir: Path) -> DevServerState | None:
    """Load persisted dev server state if present."""
    path = state_file_path(localdir)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return DevServerState(
        backend_pid=int(data["backend_pid"]),
        frontend_pid=int(data["frontend_pid"]),
        backend_port=int(data["backend_port"]),
        frontend_port=int(data["frontend_port"]),
        backend_log=str(data["backend_log"]),
        frontend_log=str(data["frontend_log"]),
    )


def write_state(localdir: Path, state: DevServerState) -> None:
    """Persist dev server state and compatibility port files."""
    localdir.mkdir(parents=True, exist_ok=True)
    state_file_path(localdir).write_text(
        json.dumps(asdict(state), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _backend_port_file(localdir).write_text(f"{state.backend_port}\n", encoding="utf-8")
    _frontend_port_file(localdir).write_text(f"{state.frontend_port}\n", encoding="utf-8")


def remove_state(localdir: Path) -> None:
    """Remove persisted dev server state and legacy compatibility files."""
    for path in (
        state_file_path(localdir),
        _backend_port_file(localdir),
        _frontend_port_file(localdir),
        _legacy_pid_file(localdir),
    ):
        path.unlink(missing_ok=True)


def is_process_alive(pid: int) -> bool:
    """Return whether a process ID still exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _tail_log(log_path: Path, lines: int = TAIL_LINES) -> str:
    """Return the last lines from a log file, if available."""
    if not log_path.exists():
        return "(log file missing)"
    content = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not content:
        return "(log file empty)"
    return "\n".join(content[-lines:])


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


def start_service(config: ServiceConfig) -> RunningService:
    """Start a background service in its own process group."""
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(config.env)
    stdin_fd = os.open("/dev/null", os.O_RDONLY)
    log_fd = os.open(
        config.log_path,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o644,
    )
    try:
        pid = os.posix_spawnp(
            config.command[0],
            config.command,
            env,
            file_actions=[
                (os.POSIX_SPAWN_DUP2, stdin_fd, 0),
                (os.POSIX_SPAWN_DUP2, log_fd, 1),
                (os.POSIX_SPAWN_DUP2, log_fd, 2),
                (os.POSIX_SPAWN_CLOSE, stdin_fd),
                (os.POSIX_SPAWN_CLOSE, log_fd),
            ],
            setpgroup=0,
        )
    finally:
        os.close(stdin_fd)
        os.close(log_fd)
    return RunningService(config=config, pid=pid)


def process_return_code(pid: int) -> int | None:
    """Return a child process exit code if it has exited, otherwise ``None``."""
    try:
        waited_pid, status = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return None if is_process_alive(pid) else 0
    if waited_pid == 0:
        return None
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return 1


def wait_for_services(
    services: list[RunningService],
    timeout_seconds: float,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
) -> None:
    """Wait until all services are healthy or fail if one exits early."""
    pending = {service.config.name: service for service in services}
    deadline = time.monotonic() + timeout_seconds

    while pending and time.monotonic() < deadline:
        for service in list(pending.values()):
            return_code = process_return_code(service.pid)
            if return_code is not None:
                log_tail = _tail_log(service.config.log_path)
                msg = (
                    f"{service.config.name} exited before becoming healthy "
                    f"(exit code {return_code}).\n"
                    f"Last log lines from {service.config.log_path}:\n{log_tail}"
                )
                raise RuntimeError(msg)
            if _is_http_ready(service.config.health_url):
                pending.pop(service.config.name, None)
        if pending:
            time.sleep(poll_interval_seconds)

    if pending:
        details = "\n\n".join(
            (
                f"{service.config.name} did not become healthy at "
                f"{service.config.health_url}.\n"
                f"Last log lines from {service.config.log_path}:\n"
                f"{_tail_log(service.config.log_path)}"
            )
            for service in pending.values()
        )
        msg = f"Timed out waiting for dev services to become healthy.\n\n{details}"
        raise RuntimeError(msg)


def terminate_process_group(pid: int) -> bool:
    """Terminate a process group, escalating to SIGKILL if needed."""
    try:
        process_group_id = os.getpgid(pid)
    except ProcessLookupError:
        return False

    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        return False
    except PermissionError:
        os.kill(pid, signal.SIGTERM)

    deadline = time.monotonic() + TERMINATE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process_return_code(pid) is not None or not is_process_alive(pid):
            return True
        time.sleep(0.1)

    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except PermissionError:
        os.kill(pid, signal.SIGKILL)

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if process_return_code(pid) is not None or not is_process_alive(pid):
            return True
        time.sleep(0.05)
    return process_return_code(pid) is not None or not is_process_alive(pid)


def stop_services(services: list[RunningService]) -> None:
    """Terminate all started services best-effort."""
    for service in services:
        terminate_process_group(service.pid)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_backend_command(port: int) -> list[str]:
    return [
        "uv",
        "run",
        "uvicorn",
        "backend.main:app",
        "--reload",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]


def _default_frontend_command(port: int) -> list[str]:
    frontend_dir = _repo_root() / "frontend"
    return [
        "npm",
        "--prefix",
        str(frontend_dir),
        "run",
        "dev",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]


def _cleanup_existing_state(localdir: Path) -> DevServerState | None:
    """Return existing running state, or clear stale state if dead."""
    state = load_state(localdir)
    if state is None:
        return None
    backend_alive = is_process_alive(state.backend_pid)
    frontend_alive = is_process_alive(state.frontend_pid)
    if backend_alive or frontend_alive:
        return state
    remove_state(localdir)
    return None


def start_dev_server(
    localdir: Path,
    requested_backend_port: int,
    requested_frontend_port: int,
    *,
    startup_timeout_seconds: float = DEFAULT_STARTUP_TIMEOUT_SECONDS,
    backend_command: list[str] | None = None,
    frontend_command: list[str] | None = None,
) -> DevServerState:
    """Start backend and frontend and wait until both are healthy."""
    existing_state = _cleanup_existing_state(localdir)
    if existing_state is not None:
        msg = (
            "Dev server is already running "
            f"(backend PID {existing_state.backend_pid}, "
            f"frontend PID {existing_state.frontend_pid})"
        )
        raise RuntimeError(msg)

    selected_backend_port = find_free_port(requested_backend_port)
    selected_frontend_port = find_free_port(requested_frontend_port, selected_backend_port)

    backend_log_path = localdir / BACKEND_LOG_FILE_NAME
    frontend_log_path = localdir / FRONTEND_LOG_FILE_NAME
    services: list[RunningService] = []

    try:
        services.append(
            start_service(
                ServiceConfig(
                    name="backend",
                    command=backend_command or _default_backend_command(selected_backend_port),
                    env={},
                    health_url=f"http://127.0.0.1:{selected_backend_port}/api/health",
                    log_path=backend_log_path,
                )
            )
        )
        services.append(
            start_service(
                ServiceConfig(
                    name="frontend",
                    command=frontend_command or _default_frontend_command(selected_frontend_port),
                    env={"AGBLOGGER_BACKEND_PORT": str(selected_backend_port)},
                    health_url=f"http://127.0.0.1:{selected_frontend_port}/",
                    log_path=frontend_log_path,
                )
            )
        )
        wait_for_services(services, timeout_seconds=startup_timeout_seconds)
    except Exception:
        stop_services(services)
        remove_state(localdir)
        raise

    state = DevServerState(
        backend_pid=services[0].pid,
        frontend_pid=services[1].pid,
        backend_port=selected_backend_port,
        frontend_port=selected_frontend_port,
        backend_log=str(backend_log_path),
        frontend_log=str(frontend_log_path),
    )
    write_state(localdir, state)
    return state


def stop_dev_server(localdir: Path) -> tuple[bool, str]:
    """Stop the dev server if state exists."""
    state = load_state(localdir)
    if state is None:
        legacy_pid_path = _legacy_pid_file(localdir)
        if not legacy_pid_path.exists():
            return False, "No dev server pidfile found"
        legacy_pid = int(_read_text(legacy_pid_path))
        if is_process_alive(legacy_pid):
            terminate_process_group(legacy_pid)
            remove_state(localdir)
            return True, f"Stopped legacy dev server (PID {legacy_pid})"
        remove_state(localdir)
        return False, "Dev server was not running (stale pidfile)"

    backend_stopped = terminate_process_group(state.backend_pid)
    frontend_stopped = terminate_process_group(state.frontend_pid)
    remove_state(localdir)

    if backend_stopped or frontend_stopped:
        return (
            True,
            "Dev server stopped "
            f"(backend PID {state.backend_pid}, frontend PID {state.frontend_pid})",
        )
    return False, "Dev server was not running (stale state)"


def health_dev_server(
    localdir: Path,
    default_backend_port: int,
    default_frontend_port: int,
) -> tuple[bool, int, int]:
    """Check backend and frontend health using current or default ports."""
    state = load_state(localdir)
    if state is not None:
        backend_port = state.backend_port
        frontend_port = state.frontend_port
    else:
        backend_port = (
            int(_read_text(_backend_port_file(localdir)))
            if _backend_port_file(localdir).exists()
            else default_backend_port
        )
        frontend_port = (
            int(_read_text(_frontend_port_file(localdir)))
            if _frontend_port_file(localdir).exists()
            else default_frontend_port
        )

    backend_ok = _is_http_ready(f"http://127.0.0.1:{backend_port}/api/health")
    frontend_ok = _is_http_ready(f"http://127.0.0.1:{frontend_port}/")

    print(f"Backend  (:{backend_port}): {'✓ healthy' if backend_ok else '✗ unreachable'}")
    print(f"Frontend (:{frontend_port}): {'✓ healthy' if frontend_ok else '✗ unreachable'}")
    if not (backend_ok and frontend_ok):
        print("Run 'just start' to start the dev server.")
    return backend_ok and frontend_ok, backend_port, frontend_port


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start")
    start_parser.add_argument("--localdir", type=Path, required=True)
    start_parser.add_argument("--backend-port", required=True)
    start_parser.add_argument("--frontend-port", required=True)
    start_parser.add_argument(
        "--startup-timeout-seconds",
        type=float,
        default=DEFAULT_STARTUP_TIMEOUT_SECONDS,
    )

    stop_parser = subparsers.add_parser("stop")
    stop_parser.add_argument("--localdir", type=Path, required=True)

    health_parser = subparsers.add_parser("health")
    health_parser.add_argument("--localdir", type=Path, required=True)
    health_parser.add_argument("--backend-port", required=True)
    health_parser.add_argument("--frontend-port", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "start":
        try:
            requested_backend_port = validate_port(args.backend_port)
            requested_frontend_port = validate_port(args.frontend_port)
            state = start_dev_server(
                args.localdir,
                requested_backend_port,
                requested_frontend_port,
                startup_timeout_seconds=args.startup_timeout_seconds,
            )
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            return 1

        if state.backend_port != requested_backend_port:
            print(
                f"Backend port :{requested_backend_port} unavailable, using :{state.backend_port}"
            )
        if state.frontend_port != requested_frontend_port:
            print(
                "Frontend port "
                f":{requested_frontend_port} unavailable, using :{state.frontend_port}"
            )
        print(
            "Dev server started "
            f"(backend PID {state.backend_pid}, frontend PID {state.frontend_pid}) "
            f"— backend :{state.backend_port}, frontend :{state.frontend_port}"
        )
        return 0

    if args.command == "stop":
        stopped, message = stop_dev_server(args.localdir)
        print(message)
        return 0 if stopped else 1

    backend_port = validate_port(args.backend_port)
    frontend_port = validate_port(args.frontend_port)
    healthy, _backend, _frontend = health_dev_server(args.localdir, backend_port, frontend_port)
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
