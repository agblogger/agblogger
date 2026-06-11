"""Audit locked runtime dependencies with a fallback vulnerability service."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

_SERVICES: Final[tuple[str, ...]] = ("pypi", "osv")
_AUDIT_TIMEOUT_SECONDS: Final[int] = 300

type RunService = Callable[[str, Path, Path], int]


class AuditServiceError(RuntimeError):
    """Raised when no vulnerability service returns a trustworthy report."""


def _default_run_service(service: str, site_packages: Path, report_path: Path) -> int:
    if service not in _SERVICES:
        msg = f"unsupported vulnerability service: {service}"
        raise ValueError(msg)
    return asyncio.run(_run_service(service, site_packages, report_path))


async def _run_service(service: str, site_packages: Path, report_path: Path) -> int:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "pip_audit",
        "--progress-spinner",
        "off",
        "--path",
        str(site_packages),
        "--format",
        "json",
        "--output",
        str(report_path),
        "--vulnerability-service",
        service,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        return await asyncio.wait_for(process.wait(), timeout=_AUDIT_TIMEOUT_SECONDS)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise


def _parse_report(report_path: Path, production_packages: frozenset[str]) -> tuple[str, ...]:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        msg = "returned an unreadable audit report"
        raise AuditServiceError(msg) from exc

    if not isinstance(report, dict):
        msg = "returned an invalid audit report"
        raise AuditServiceError(msg)

    dependencies = report.get("dependencies")
    if not isinstance(dependencies, list):
        msg = "returned an audit report without dependencies"
        raise AuditServiceError(msg)
    if not dependencies:
        msg = "inspected no dependencies"
        raise AuditServiceError(msg)

    vulnerabilities: list[str] = []
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            msg = "returned an invalid dependency entry"
            raise AuditServiceError(msg)
        name = dependency.get("name")
        version = dependency.get("version")
        dependency_vulnerabilities = dependency.get("vulns")
        if (
            not isinstance(name, str)
            or not isinstance(version, str)
            or not isinstance(dependency_vulnerabilities, list)
        ):
            msg = "returned an invalid dependency entry"
            raise AuditServiceError(msg)

        normalized_name = name.lower().replace("_", "-")
        for vulnerability in dependency_vulnerabilities:
            if not isinstance(vulnerability, dict) or not isinstance(vulnerability.get("id"), str):
                msg = "returned an invalid vulnerability entry"
                raise AuditServiceError(msg)
            if normalized_name in production_packages:
                vulnerabilities.append(f"{name}=={version}:{vulnerability['id']}")

    return tuple(vulnerabilities)


def run_audit(
    site_packages: Path,
    production_packages: frozenset[str],
    *,
    services: Sequence[str] = _SERVICES,
    run_service: RunService = _default_run_service,
) -> tuple[str, ...]:
    """Return production vulnerabilities from the first trustworthy service report."""
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="agblogger-audit-") as temporary_directory:
        report_path = Path(temporary_directory) / "report.json"
        for service in services:
            report_path.unlink(missing_ok=True)
            try:
                return_code = run_service(service, site_packages, report_path)
            except (OSError, subprocess.SubprocessError) as exc:
                errors.append(f"{service}: audit command failed ({exc})")
                continue

            if return_code >= 2:
                errors.append(f"{service}: pip-audit exited {return_code}")
                continue

            try:
                return _parse_report(report_path, production_packages)
            except AuditServiceError as exc:
                errors.append(f"{service}: {exc}")

    msg = f"all vulnerability services failed: {'; '.join(errors)}"
    raise AuditServiceError(msg)


def _load_production_packages(path: Path) -> frozenset[str]:
    return frozenset(
        line.strip().lower().replace("_", "-")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the locked runtime dependency audit."""
    parser = argparse.ArgumentParser()
    parser.add_argument("site_packages", type=Path)
    parser.add_argument("production_packages", type=Path)
    args = parser.parse_args(argv)

    try:
        vulnerabilities = run_audit(
            args.site_packages,
            _load_production_packages(args.production_packages),
        )
    except (AuditServiceError, OSError) as exc:
        print(f"runtime dependency audit failed: {exc}", file=sys.stderr)
        return 2

    for vulnerability in vulnerabilities:
        print(vulnerability)
    return int(bool(vulnerabilities))


if __name__ == "__main__":
    raise SystemExit(main())
