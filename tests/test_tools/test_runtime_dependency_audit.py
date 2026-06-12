"""Tests for the locked runtime dependency audit quality gate."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from tools.runtime_dependency_audit import AuditServiceError, run_audit

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def _write_report(path: Path, dependencies: list[dict[str, object]]) -> None:
    path.write_text(json.dumps({"dependencies": dependencies}), encoding="utf-8")


def test_run_audit_falls_back_to_osv_when_pypi_leaves_empty_report(tmp_path: Path) -> None:
    services: list[str] = []

    def fake_run(service: str, _site_packages: Path, report_path: Path) -> int:
        services.append(service)
        if service == "pypi":
            report_path.write_text("", encoding="utf-8")
            return 2
        _write_report(
            report_path,
            [{"name": "fastapi", "version": "1.0", "vulns": []}],
        )
        return 0

    vulnerabilities = run_audit(
        tmp_path / "site-packages",
        frozenset({"fastapi"}),
        run_service=fake_run,
    )

    assert vulnerabilities == ()
    assert services == ["pypi", "osv"]


def test_run_audit_reports_production_vulnerabilities_from_fallback(tmp_path: Path) -> None:
    def fake_run(service: str, _site_packages: Path, report_path: Path) -> int:
        if service == "pypi":
            report_path.write_text("", encoding="utf-8")
            return 2
        _write_report(
            report_path,
            [
                {
                    "name": "fastapi",
                    "version": "1.0",
                    "vulns": [{"id": "CVE-2099-0001"}],
                },
                {
                    "name": "pytest",
                    "version": "1.0",
                    "vulns": [{"id": "CVE-2099-0002"}],
                },
            ],
        )
        return 1

    vulnerabilities = run_audit(
        tmp_path / "site-packages",
        frozenset({"fastapi"}),
        run_service=fake_run,
    )

    assert vulnerabilities == ("fastapi==1.0:CVE-2099-0001",)


def test_run_audit_falls_back_after_service_timeout(tmp_path: Path) -> None:
    services: list[str] = []

    def fake_run(service: str, _site_packages: Path, report_path: Path) -> int:
        services.append(service)
        if service == "pypi":
            raise TimeoutError
        _write_report(
            report_path,
            [{"name": "fastapi", "version": "1.0", "vulns": []}],
        )
        return 0

    vulnerabilities = run_audit(
        tmp_path / "site-packages",
        frozenset({"fastapi"}),
        run_service=fake_run,
    )

    assert vulnerabilities == ()
    assert services == ["pypi", "osv"]


def test_run_audit_fails_closed_when_all_services_return_invalid_reports(tmp_path: Path) -> None:
    def fake_run(_service: str, _site_packages: Path, report_path: Path) -> int:
        report_path.write_text("", encoding="utf-8")
        return 2

    with pytest.raises(AuditServiceError, match=r"pypi.*osv"):
        run_audit(
            tmp_path / "site-packages",
            frozenset({"fastapi"}),
            run_service=fake_run,
        )


@pytest.mark.parametrize(
    ("dependencies", "expected"),
    [
        ([], "inspected no dependencies"),
        ([{"name": "fastapi", "version": "1.0"}], "invalid dependency entry"),
    ],
)
def test_run_audit_rejects_incomplete_reports(
    tmp_path: Path,
    dependencies: list[dict[str, object]],
    expected: str,
) -> None:
    services: Sequence[str] = ("pypi", "osv")
    calls = 0

    def fake_run(_service: str, _site_packages: Path, report_path: Path) -> int:
        nonlocal calls
        calls += 1
        _write_report(report_path, dependencies)
        return 0

    with pytest.raises(AuditServiceError, match=expected):
        run_audit(
            tmp_path / "site-packages",
            frozenset({"fastapi"}),
            services=services,
            run_service=fake_run,
        )

    assert calls == 2
