"""Backend mutation-testing orchestration and CI gating."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

from cli import repo_root

if TYPE_CHECKING:
    from collections.abc import Iterator

_STATUS_BY_EXIT_CODE: Final[dict[int | None, str]] = {
    1: "killed",
    3: "killed",
    0: "survived",
    5: "no tests",
    2: "check was interrupted by user",
    None: "not checked",
    33: "no tests",
    34: "skipped",
    35: "suspicious",
    36: "timeout",
    -24: "timeout",
    24: "timeout",
    152: "timeout",
    255: "timeout",
    -11: "segfault",
    -9: "segfault",
}
_FAILURE_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "survived",
        "timeout",
        "suspicious",
        "no tests",
        "segfault",
        "check was interrupted by user",
    }
)
_STAGED_ENTRIES: Final[tuple[str, ...]] = (
    "backend",
    "cli",
    "tests",
    "pyproject.toml",
    "uv.lock",
    ".python-version",
)


@dataclass(frozen=True)
class BackendMutationProfile:
    """Mutation-test profile with scope and quality budgets."""

    key: str
    description: str
    paths_to_mutate: tuple[str, ...]
    tests: tuple[str, ...]
    min_strict_score_percent: float
    max_survived: int
    max_timeout: int
    max_suspicious: int
    max_no_tests: int
    max_segfault: int
    max_interrupted: int
    mutate_only_covered_lines: bool = True
    max_stack_depth: int = 12
    extra_pytest_add_cli_args: tuple[str, ...] = ()
    do_not_mutate: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not (0 <= self.min_strict_score_percent <= 100):
            msg = f"min_strict_score_percent must be 0-100, got {self.min_strict_score_percent}"
            raise ValueError(msg)
        for field_name in (
            "max_survived",
            "max_timeout",
            "max_suspicious",
            "max_no_tests",
            "max_segfault",
            "max_interrupted",
        ):
            if getattr(self, field_name) < 0:
                msg = f"{field_name} must be >= 0, got {getattr(self, field_name)}"
                raise ValueError(msg)


PROFILE_BACKEND = BackendMutationProfile(
    key="backend",
    description="Targeted backend mutation gate for highest-risk logic paths",
    paths_to_mutate=(
        "backend/services/auth_service.py",
        "backend/services/sync_service.py",
        "backend/filesystem/frontmatter.py",
        "backend/services/slug_service.py",
        "backend/crosspost/ssrf.py",
        "backend/services/rate_limit_service.py",
    ),
    tests=(
        "tests/test_services/test_auth_service.py",
        "tests/test_services/test_auth_edge_cases.py",
        "tests/test_services/test_sync_service.py",
        "tests/test_services/test_sync_normalization.py",
        "tests/test_services/test_slug_service.py",
        "tests/test_services/test_ssrf.py",
        "tests/test_services/test_rate_limiter.py",
        "tests/test_rendering/test_frontmatter.py",
        "tests/test_sync/test_normalize_frontmatter.py",
        "tests/test_api/test_auth_hardening.py",
        "tests/test_api/test_security_regressions.py",
    ),
    min_strict_score_percent=90.0,
    max_survived=0,
    max_timeout=0,
    max_suspicious=0,
    max_no_tests=0,
    max_segfault=0,
    max_interrupted=0,
    mutate_only_covered_lines=False,
)

PROFILE_BACKEND_FULL = BackendMutationProfile(
    key="backend-full",
    description="Full backend+CLI mutation sweep",
    paths_to_mutate=(
        "backend",
        "cli",
    ),
    tests=(
        "tests/test_services",
        "tests/test_cli",
        "tests/test_sync",
        "tests/test_labels",
        "tests/test_rendering",
    ),
    min_strict_score_percent=85.0,
    max_survived=0,
    max_timeout=0,
    max_suspicious=0,
    max_no_tests=0,
    max_segfault=0,
    max_interrupted=0,
    mutate_only_covered_lines=False,
    max_stack_depth=16,
    extra_pytest_add_cli_args=(
        "--ignore=tests/test_services/test_sync_merge_integration.py",
        "--ignore=tests/test_rendering/test_renderer_no_dead_code.py",
        "--deselect=tests/test_services/test_atproto_oauth.py::TestIsSafeUrlAsync::test_is_safe_url_is_async",
    ),
    do_not_mutate=("backend/main.py", "*/backend/main.py", "**/backend/main.py"),
)

PROFILES: Final[dict[str, BackendMutationProfile]] = {
    PROFILE_BACKEND.key: PROFILE_BACKEND,
    PROFILE_BACKEND_FULL.key: PROFILE_BACKEND_FULL,
}


@dataclass(frozen=True)
class MutationSummary:
    """Aggregated mutmut status counts."""

    total: int
    killed: int
    survived: int
    timeout: int
    suspicious: int
    no_tests: int
    skipped: int
    not_checked: int
    segfault: int
    interrupted: int

    def __post_init__(self) -> None:
        for field_name in (
            "total",
            "killed",
            "survived",
            "timeout",
            "suspicious",
            "no_tests",
            "skipped",
            "not_checked",
            "segfault",
            "interrupted",
        ):
            if getattr(self, field_name) < 0:
                msg = f"{field_name} must be >= 0, got {getattr(self, field_name)}"
                raise ValueError(msg)
        component_sum = (
            self.killed
            + self.survived
            + self.timeout
            + self.suspicious
            + self.no_tests
            + self.skipped
            + self.not_checked
            + self.segfault
            + self.interrupted
        )
        if self.total != component_sum:
            msg = f"total ({self.total}) != sum of components ({component_sum})"
            raise ValueError(msg)

    @property
    def strict_denominator(self) -> int:
        return self.total - self.skipped - self.not_checked

    @property
    def strict_score_percent(self) -> float:
        denominator = self.strict_denominator
        if denominator <= 0:
            return 0.0
        return (self.killed / denominator) * 100.0


def render_setup_cfg(profile: BackendMutationProfile) -> str:
    """Render a temporary mutmut setup.cfg for a profile."""

    def render_multiline(key: str, values: tuple[str, ...]) -> str:
        rendered = [f"{key} ="]
        rendered.extend(f"    {value}" for value in values)
        return "\n".join(rendered)

    pytest_add_cli_args = (
        "-W",
        "ignore::pytest.PytestUnraisableExceptionWarning",
        *profile.extra_pytest_add_cli_args,
    )

    lines = [
        "[mutmut]",
        render_multiline("paths_to_mutate", profile.paths_to_mutate),
        *(
            [render_multiline("do_not_mutate", profile.do_not_mutate)]
            if profile.do_not_mutate
            else []
        ),
        render_multiline("also_copy", ("backend", "cli", "tests")),
        render_multiline("tests_dir", profile.tests),
        render_multiline("pytest_add_cli_args", pytest_add_cli_args),
        f"mutate_only_covered_lines = {'true' if profile.mutate_only_covered_lines else 'false'}",
        f"max_stack_depth = {profile.max_stack_depth}",
        "debug = false",
    ]
    return "\n".join(lines) + "\n"


def _status_for_exit_code(raw_exit_code: object) -> str:
    if raw_exit_code is None:
        return _STATUS_BY_EXIT_CODE[None]
    if not isinstance(raw_exit_code, int):
        return "suspicious"
    return _STATUS_BY_EXIT_CODE.get(raw_exit_code, "suspicious")


def collect_summary(meta_paths: list[Path]) -> tuple[MutationSummary, list[dict[str, str]]]:
    """Collect summary and failing mutants from mutmut *.meta files."""

    counts = {
        "killed": 0,
        "survived": 0,
        "timeout": 0,
        "suspicious": 0,
        "no tests": 0,
        "skipped": 0,
        "not checked": 0,
        "segfault": 0,
        "check was interrupted by user": 0,
    }
    failing_mutants: list[dict[str, str]] = []

    for meta_path in meta_paths:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        raw_exit_code_by_key = data.get("exit_code_by_key")
        if not isinstance(raw_exit_code_by_key, dict):
            raise ValueError(f"Invalid meta file format (exit_code_by_key): {meta_path}")

        for mutant_name, raw_exit_code in raw_exit_code_by_key.items():
            status = _status_for_exit_code(raw_exit_code)
            counts[status] += 1
            if status in _FAILURE_STATUSES:
                failing_mutants.append(
                    {
                        "mutant": str(mutant_name),
                        "status": status,
                        "meta_file": str(meta_path),
                    }
                )

    total = sum(counts.values())
    summary = MutationSummary(
        total=total,
        killed=counts["killed"],
        survived=counts["survived"],
        timeout=counts["timeout"],
        suspicious=counts["suspicious"],
        no_tests=counts["no tests"],
        skipped=counts["skipped"],
        not_checked=counts["not checked"],
        segfault=counts["segfault"],
        interrupted=counts["check was interrupted by user"],
    )
    return summary, failing_mutants


def evaluate_gate(
    summary: MutationSummary,
    profile: BackendMutationProfile,
) -> list[str]:
    """Evaluate mutation quality budgets and return failing conditions."""

    failures: list[str] = []

    if summary.strict_denominator <= 0:
        failures.append("no actionable mutants produced; strict score cannot be evaluated")

    if summary.strict_score_percent < profile.min_strict_score_percent:
        failures.append(
            "strict score "
            f"{summary.strict_score_percent:.2f}% is below "
            f"required {profile.min_strict_score_percent:.2f}%"
        )

    budgets = (
        ("survived", summary.survived, profile.max_survived),
        ("timeout", summary.timeout, profile.max_timeout),
        ("suspicious", summary.suspicious, profile.max_suspicious),
        ("no tests", summary.no_tests, profile.max_no_tests),
        ("segfault", summary.segfault, profile.max_segfault),
        ("interrupted", summary.interrupted, profile.max_interrupted),
    )
    for name, actual, maximum in budgets:
        if actual > maximum:
            failures.append(f"{name} mutants {actual} exceed budget {maximum}")

    return failures


def _mutation_report_path(repo_root: Path, profile: BackendMutationProfile) -> Path:
    report_dir = repo_root / "reports" / "mutation"
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir / f"{profile.key}.json"


def _prepare_workspace(repo_root: Path, workspace: Path) -> None:
    for entry in _STAGED_ENTRIES:
        source = repo_root / entry
        if not source.exists():
            continue
        destination = workspace / entry
        try:
            destination.symlink_to(source, target_is_directory=source.is_dir())
        except OSError:
            if source.is_dir():
                shutil.copytree(source, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(source, destination)


@contextmanager
def _change_cwd(path: Path) -> Iterator[None]:
    previous_cwd = Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(previous_cwd)


def _run_mutmut(*, workspace: Path, max_children: int | None) -> int:
    try:
        mutmut_main = importlib.import_module("mutmut.__main__")
    except ImportError as exc:  # pragma: no cover - environment/setup failure
        raise RuntimeError(
            "mutmut is not installed. Run `uv sync --extra dev` before mutation checks."
        ) from exc

    run_mutmut = getattr(mutmut_main, "_run", None)
    if run_mutmut is None:  # pragma: no cover - compatibility safety check
        raise RuntimeError("mutmut internals changed: _run function is unavailable")

    with _change_cwd(workspace):
        try:
            run_mutmut([], max_children)
        except SystemExit as exc:
            if isinstance(exc.code, int):
                return exc.code
            return 1
    return 0


def _print_summary(summary: MutationSummary) -> None:
    print("Mutation summary")
    print(f"  total: {summary.total}")
    print(f"  killed: {summary.killed}")
    print(f"  survived: {summary.survived}")
    print(f"  timeout: {summary.timeout}")
    print(f"  suspicious: {summary.suspicious}")
    print(f"  no tests: {summary.no_tests}")
    print(f"  skipped: {summary.skipped}")
    print(f"  not checked: {summary.not_checked}")
    print(f"  segfault: {summary.segfault}")
    print(f"  interrupted: {summary.interrupted}")
    print(f"  strict score: {summary.strict_score_percent:.2f}%")


def _write_report(
    *,
    report_path: Path,
    profile: BackendMutationProfile,
    command: list[str],
    returncode: int,
    summary: MutationSummary,
    gate_failures: list[str],
    failing_mutants: list[dict[str, str]],
) -> None:
    payload = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "profile": asdict(profile),
        "command": command,
        "mutmut_returncode": returncode,
        "summary": asdict(summary),
        "strict_score_percent": summary.strict_score_percent,
        "gate_failures": gate_failures,
        "failing_mutants": failing_mutants,
    }
    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


@contextmanager
def _workspace(profile_key: str, *, keep_artifacts: bool, repo_root: Path) -> Iterator[Path]:
    if keep_artifacts:
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        workspace_path = (
            repo_root / "reports" / "mutation" / "artifacts" / f"{profile_key}-{timestamp}"
        )
        workspace_path.mkdir(parents=True, exist_ok=False)
        yield workspace_path
        return

    with tempfile.TemporaryDirectory(prefix=f"agblogger-mutation-{profile_key}-") as raw_path:
        yield Path(raw_path)


def run_profile(
    profile: BackendMutationProfile,
    *,
    repo_root: Path,
    max_children: int | None,
    keep_artifacts: bool,
) -> int:
    """Run one backend mutation profile and enforce quality gates."""

    if max_children is not None and max_children <= 0:
        raise ValueError("--max-children must be greater than zero")
    report_path = _mutation_report_path(repo_root, profile)

    with _workspace(profile.key, keep_artifacts=keep_artifacts, repo_root=repo_root) as workspace:
        _prepare_workspace(repo_root, workspace)
        setup_cfg = workspace / "setup.cfg"
        setup_cfg.write_text(render_setup_cfg(profile), encoding="utf-8")

        command = [
            "python",
            "-m",
            "mutmut",
            "run",
            *([] if max_children is None else ["--max-children", str(max_children)]),
        ]
        mutmut_returncode = _run_mutmut(workspace=workspace, max_children=max_children)

        meta_paths = sorted((workspace / "mutants").rglob("*.meta"))
        if meta_paths:
            summary, failing_mutants = collect_summary(meta_paths)
        else:
            summary = MutationSummary(
                total=0,
                killed=0,
                survived=0,
                timeout=0,
                suspicious=0,
                no_tests=0,
                skipped=0,
                not_checked=0,
                segfault=0,
                interrupted=0,
            )
            failing_mutants = []

        gate_failures: list[str] = []
        if mutmut_returncode != 0:
            gate_failures.append(f"mutmut exited with code {mutmut_returncode}")
        gate_failures.extend(evaluate_gate(summary, profile))

        _write_report(
            report_path=report_path,
            profile=profile,
            command=command,
            returncode=mutmut_returncode,
            summary=summary,
            gate_failures=gate_failures,
            failing_mutants=failing_mutants,
        )

        _print_summary(summary)
        print(f"Report written to {report_path}")

        if gate_failures:
            print("Mutation gate failures")
            for failure in gate_failures:
                print(f"  - {failure}")
            if failing_mutants:
                print("Failing mutants (first 20)")
                for mutant in failing_mutants[:20]:
                    print(f"  - {mutant['mutant']} ({mutant['status']})")
            return 1

        print(f"Mutation profile {profile.key} passed")
        return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run backend mutation-testing profiles")
    parser.add_argument(
        "profile",
        choices=tuple(PROFILES.keys()),
        help="Mutation profile to run",
    )
    parser.add_argument(
        "--max-children",
        type=int,
        default=None,
        help="Override mutmut worker process count",
    )
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Persist mutmut working directory under reports/mutation/artifacts/",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    profile = PROFILES[args.profile]
    return run_profile(
        profile,
        repo_root=repo_root(),
        max_children=args.max_children,
        keep_artifacts=args.keep_artifacts,
    )


if __name__ == "__main__":
    raise SystemExit(main())
