"""Tests for backend mutation-testing orchestration."""

from __future__ import annotations

import json
from dataclasses import fields as dataclass_fields
from typing import TYPE_CHECKING

import pytest

from tools.mutation_backend import (
    PROFILE_BACKEND,
    PROFILE_BACKEND_FULL,
    BackendMutationProfile,
    MutationSummary,
    _write_report,
    collect_summary,
    evaluate_gate,
    render_setup_cfg,
    run_profile,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_render_setup_cfg_includes_profile_paths_and_tests() -> None:
    content = render_setup_cfg(PROFILE_BACKEND)

    assert "[mutmut]" in content
    assert "backend/services/auth_service.py" in content
    assert "tests/test_services/test_auth_service.py" in content
    assert "mutate_only_covered_lines = false" in content


def test_render_setup_cfg_includes_do_not_mutate_when_defined() -> None:
    content = render_setup_cfg(PROFILE_BACKEND_FULL)

    assert "do_not_mutate =" in content
    assert "backend/main.py" in content


def test_collect_summary_maps_exit_codes_to_status_buckets(tmp_path: Path) -> None:
    meta = tmp_path / "slug_service.py.meta"
    meta.write_text(
        """
{
  "exit_code_by_key": {
    "m1": 1,
    "m2": 0,
    "m3": 36,
    "m4": 35,
    "m5": 5,
    "m6": 34,
    "m7": null,
    "m8": -11,
    "m9": 2
  },
  "hash_by_function_name": {},
  "durations_by_key": {},
  "estimated_durations_by_key": {}
}
""".strip(),
        encoding="utf-8",
    )

    summary, failures = collect_summary([meta])

    assert summary.killed == 1
    assert summary.survived == 1
    assert summary.timeout == 1
    assert summary.suspicious == 1
    assert summary.no_tests == 1
    assert summary.skipped == 1
    assert summary.not_checked == 1
    assert summary.segfault == 1
    assert summary.interrupted == 1
    assert summary.total == 9
    assert len(failures) == 6


def test_mutation_summary_strict_score_excludes_skipped_and_not_checked() -> None:
    summary = MutationSummary(
        total=10,
        killed=6,
        survived=2,
        timeout=0,
        suspicious=0,
        no_tests=0,
        skipped=1,
        not_checked=1,
        segfault=0,
        interrupted=0,
    )

    assert summary.strict_denominator == 8
    assert summary.strict_score_percent == 75.0


def test_evaluate_gate_reports_threshold_and_budget_failures() -> None:
    summary = MutationSummary(
        total=12,
        killed=8,
        survived=2,
        timeout=1,
        suspicious=0,
        no_tests=1,
        skipped=0,
        not_checked=0,
        segfault=0,
        interrupted=0,
    )

    profile = BackendMutationProfile(
        key="test",
        description="test profile",
        paths_to_mutate=("backend",),
        tests=("tests",),
        min_strict_score_percent=90.0,
        max_survived=0,
        max_timeout=0,
        max_suspicious=0,
        max_no_tests=0,
        max_segfault=0,
        max_interrupted=0,
    )

    failures = evaluate_gate(summary, profile)

    assert any("strict score" in message for message in failures)
    assert any("survived" in message for message in failures)
    assert any("timeout" in message for message in failures)
    assert any("no tests" in message for message in failures)


def test_evaluate_gate_accepts_clean_summary() -> None:
    summary = MutationSummary(
        total=8,
        killed=8,
        survived=0,
        timeout=0,
        suspicious=0,
        no_tests=0,
        skipped=0,
        not_checked=0,
        segfault=0,
        interrupted=0,
    )

    profile = BackendMutationProfile(
        key="test",
        description="test profile",
        paths_to_mutate=("backend",),
        tests=("tests",),
        min_strict_score_percent=90.0,
        max_survived=0,
        max_timeout=0,
        max_suspicious=0,
        max_no_tests=0,
        max_segfault=0,
        max_interrupted=0,
    )

    failures = evaluate_gate(summary, profile)

    assert failures == []


class TestBackendMutationProfileValidation:
    def test_min_strict_score_percent_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="min_strict_score_percent"):
            BackendMutationProfile(
                key="test",
                description="test",
                paths_to_mutate=("backend",),
                tests=("tests",),
                min_strict_score_percent=150.0,
                max_survived=0,
                max_timeout=0,
                max_suspicious=0,
                max_no_tests=0,
                max_segfault=0,
                max_interrupted=0,
            )

    def test_max_survived_negative(self) -> None:
        with pytest.raises(ValueError, match="max_survived"):
            BackendMutationProfile(
                key="test",
                description="test",
                paths_to_mutate=("backend",),
                tests=("tests",),
                min_strict_score_percent=90.0,
                max_survived=-1,
                max_timeout=0,
                max_suspicious=0,
                max_no_tests=0,
                max_segfault=0,
                max_interrupted=0,
            )


class TestMutationSummaryValidation:
    def test_total_does_not_equal_sum(self) -> None:
        with pytest.raises(ValueError, match="total"):
            MutationSummary(
                total=5,
                killed=10,
                survived=0,
                timeout=0,
                suspicious=0,
                no_tests=0,
                skipped=0,
                not_checked=0,
                segfault=0,
                interrupted=0,
            )

    def test_negative_count(self) -> None:
        with pytest.raises(ValueError, match="killed"):
            MutationSummary(
                total=0,
                killed=-1,
                survived=0,
                timeout=0,
                suspicious=0,
                no_tests=0,
                skipped=0,
                not_checked=0,
                segfault=0,
                interrupted=0,
            )


class TestRunProfileValidation:
    def test_invalid_max_children_does_not_create_report_dir(self, tmp_path: Path) -> None:
        """Validation must happen before any side effects like directory creation."""
        report_dir = tmp_path / "reports" / "mutation"
        assert not report_dir.exists()
        with pytest.raises(ValueError, match="--max-children must be greater than zero"):
            run_profile(
                PROFILE_BACKEND,
                repo_root=tmp_path,
                max_children=0,
                keep_artifacts=False,
            )
        assert not report_dir.exists(), "reports/mutation/ should not be created for invalid input"


class TestWriteReport:
    def test_report_includes_all_profile_fields(self, tmp_path: Path) -> None:
        """All BackendMutationProfile fields should appear in the report."""
        profile = BackendMutationProfile(
            key="test",
            description="test profile",
            paths_to_mutate=("backend/main.py",),
            tests=("tests/",),
            min_strict_score_percent=90.0,
            max_survived=0,
            max_timeout=0,
            max_suspicious=0,
            max_no_tests=0,
            max_segfault=0,
            max_interrupted=0,
            mutate_only_covered_lines=True,
            max_stack_depth=12,
            extra_pytest_add_cli_args=("--foo",),
            do_not_mutate=("backend/migrations",),
        )
        summary = MutationSummary(
            total=10,
            killed=8,
            survived=1,
            timeout=0,
            suspicious=0,
            no_tests=1,
            skipped=0,
            not_checked=0,
            segfault=0,
            interrupted=0,
        )
        report_path = tmp_path / "report.json"
        _write_report(
            report_path=report_path,
            profile=profile,
            command=["test"],
            returncode=0,
            summary=summary,
            gate_failures=[],
            failing_mutants=[],
        )
        data = json.loads(report_path.read_text())
        profile_data = data["profile"]
        expected_fields = {f.name for f in dataclass_fields(BackendMutationProfile)}
        actual_fields = set(profile_data.keys())
        assert expected_fields == actual_fields, (
            f"Missing fields: {expected_fields - actual_fields}"
        )
