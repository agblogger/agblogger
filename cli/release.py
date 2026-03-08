"""Release automation for AgBlogger."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from cli import repo_root


class ReleaseError(RuntimeError):
    """Raised when release automation cannot proceed safely."""


@dataclass(frozen=True)
class ReleaseResult:
    """Metadata for a completed release."""

    old_version: str
    new_version: str
    tag: str
    tarball_path: Path


SEMVER_RE = re.compile(r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)$")
PROJECT_VERSION_RE = re.compile(
    r'(?ms)(?P<prefix>^\[project\]\n.*?^version = ")(?P<version>[^"]+)(?P<suffix>")',
)
APP_VERSION_RE = re.compile(r'(?P<prefix>version=")(?P<version>[^"]+)(?P<suffix>")')
TEST_VERSION_RE = re.compile(
    r'(?P<prefix>assert data\["version"\] == ")(?P<version>[^"]+)(?P<suffix>")'
)
UV_LOCK_RE = re.compile(
    r'(?ms)(?P<prefix>^\[\[package\]\]\nname = "agblogger"\nversion = ")'
    r'(?P<version>[^"]+)(?P<suffix>")',
)


def read_repo_version(project_dir: Path) -> str:
    """Read the source-of-truth version from the VERSION file."""
    version_path = project_dir / "VERSION"
    if not version_path.exists():
        raise ReleaseError(f"Missing VERSION file: {version_path}")
    return version_path.read_text(encoding="utf-8").strip()


def bump_version(version: str, level: str) -> str:
    """Increment a semantic version string by the selected level."""
    match = SEMVER_RE.fullmatch(version)
    if match is None:
        raise ReleaseError(
            f"Expected semantic version in MAJOR.MINOR.PATCH format, got {version!r}"
        )

    major = int(match.group("major"))
    minor = int(match.group("minor"))
    patch = int(match.group("patch"))

    if level == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    if level == "major":
        return f"{major + 1}.0.0"
    raise ReleaseError(f"Unsupported release level: {level}")


def _run_git(
    project_dir: Path,
    args: list[str],
    *,
    check: bool = True,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=project_dir,
        check=check,
        capture_output=capture_output,
        text=True,
    )


def _run_gh(
    project_dir: Path,
    args: list[str],
    *,
    check: bool = True,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *args],
        cwd=project_dir,
        check=check,
        capture_output=capture_output,
        text=True,
    )


def _require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise ReleaseError(f"Required tool {name!r} is not installed or not available on PATH")


def _read_current_version(project_dir: Path) -> str:
    return read_repo_version(project_dir)


def _replace_with_regex(
    path: Path,
    pattern: re.Pattern[str],
    current_version: str,
    new_version: str,
) -> None:
    content = path.read_text(encoding="utf-8")
    match = pattern.search(content)
    if match is None:
        raise ReleaseError(f"Could not locate version field in {path}")
    if match.group("version") != current_version:
        raise ReleaseError(
            f"Expected current version {current_version} in {path}, found {match.group('version')}"
        )
    updated = pattern.sub(
        lambda matched: f"{matched.group('prefix')}{new_version}{matched.group('suffix')}",
        content,
        count=1,
    )
    path.write_text(updated, encoding="utf-8")


def _update_json_version(
    path: Path,
    current_version: str,
    new_version: str,
    *,
    update_lock_root: bool = False,
) -> None:
    content = json.loads(path.read_text(encoding="utf-8"))
    if content.get("version") != current_version:
        raise ReleaseError(
            f"Expected current version {current_version} in {path}, "
            f"found {content.get('version')!r}"
        )
    content["version"] = new_version
    if update_lock_root:
        packages = content.get("packages")
        if not isinstance(packages, dict):
            raise ReleaseError(f"Expected packages object in {path}")
        root_package = packages.get("")
        if not isinstance(root_package, dict):
            raise ReleaseError(f"Expected root package metadata in {path}")
        if root_package.get("version") != current_version:
            raise ReleaseError(
                f"Expected current version {current_version} in {path} root package, "
                f"found {root_package.get('version')!r}"
            )
        root_package["version"] = new_version
    path.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")


def update_version_files(project_dir: Path, current_version: str, new_version: str) -> list[Path]:
    """Rewrite all release-version surfaces to the new version."""
    updated_paths: list[Path] = []

    version_path = project_dir / "VERSION"
    existing_version = version_path.read_text(encoding="utf-8").strip()
    if existing_version != current_version:
        raise ReleaseError(
            f"Expected current version {current_version} in {version_path}, "
            f"found {existing_version}"
        )
    version_path.write_text(f"{new_version}\n", encoding="utf-8")
    updated_paths.append(Path("VERSION"))

    regex_files: list[tuple[Path, re.Pattern[str]]] = [
        (Path("pyproject.toml"), PROJECT_VERSION_RE),
        (Path("packaging/server/pyproject.toml"), PROJECT_VERSION_RE),
    ]
    for rel_path, pattern in regex_files:
        _replace_with_regex(project_dir / rel_path, pattern, current_version, new_version)
        updated_paths.append(rel_path)

    _update_json_version(project_dir / "frontend/package.json", current_version, new_version)
    updated_paths.append(Path("frontend/package.json"))
    _update_json_version(
        project_dir / "frontend/package-lock.json",
        current_version,
        new_version,
        update_lock_root=True,
    )
    updated_paths.append(Path("frontend/package-lock.json"))

    remaining_regex_files: list[tuple[Path, re.Pattern[str]]] = [(Path("uv.lock"), UV_LOCK_RE)]
    for rel_path, pattern in remaining_regex_files:
        _replace_with_regex(project_dir / rel_path, pattern, current_version, new_version)
        updated_paths.append(rel_path)

    return updated_paths


def _ensure_clean_worktree(project_dir: Path) -> None:
    result = _run_git(project_dir, ["status", "--short"], capture_output=True)
    if result.stdout.strip():
        raise ReleaseError("Release requires a clean git worktree")


def _ensure_tag_absent(project_dir: Path, tag: str) -> None:
    result = _run_git(
        project_dir,
        ["rev-parse", "--verify", f"refs/tags/{tag}"],
        check=False,
        capture_output=True,
    )
    if result.returncode == 0:
        raise ReleaseError(f"Git tag {tag} already exists")


def _ensure_release_absent(project_dir: Path, tag: str) -> None:
    result = _run_gh(
        project_dir,
        ["release", "view", tag],
        check=False,
        capture_output=True,
    )
    if result.returncode == 0:
        raise ReleaseError(f"GitHub release {tag} already exists")


def run_release(project_dir: Path, level: str, *, remote: str = "origin") -> ReleaseResult:
    """Perform a release bump, tag, archive, push, and GitHub release creation."""
    _require_tool("git")
    _require_tool("gh")
    _ensure_clean_worktree(project_dir)

    old_version = _read_current_version(project_dir)
    new_version = bump_version(old_version, level)
    tag = f"v{new_version}"
    _ensure_tag_absent(project_dir, tag)
    _ensure_release_absent(project_dir, tag)

    updated_paths = update_version_files(project_dir, old_version, new_version)
    _run_git(project_dir, ["add", *(path.as_posix() for path in updated_paths)])
    _run_git(project_dir, ["commit", "-m", f"release: {tag}"])
    _run_git(project_dir, ["tag", "-a", tag, "-m", f"Release {tag}"])

    tarball_path = project_dir / "dist" / "releases" / f"agblogger-{new_version}.tar.gz"
    tarball_path.parent.mkdir(parents=True, exist_ok=True)
    _run_git(
        project_dir,
        [
            "archive",
            "--format=tar.gz",
            f"--prefix=agblogger-{new_version}/",
            "-o",
            str(tarball_path),
            tag,
        ],
    )
    _run_git(project_dir, ["push", remote, "HEAD"])
    _run_git(project_dir, ["push", remote, tag])
    _run_gh(
        project_dir,
        [
            "release",
            "create",
            tag,
            str(tarball_path),
            "--title",
            tag,
            "--generate-notes",
        ],
    )
    return ReleaseResult(
        old_version=old_version,
        new_version=new_version,
        tag=tag,
        tarball_path=tarball_path,
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(description="Create a versioned AgBlogger GitHub release.")
    parser.add_argument("level", choices=["major", "minor", "patch"], help="Semantic version bump.")
    parser.add_argument(
        "--remote",
        default="origin",
        help="Git remote to push the release commit and tag to (default: origin).",
    )
    return parser


def main() -> None:
    """Run the release workflow."""
    args = build_parser().parse_args()
    try:
        result = run_release(repo_root(), args.level, remote=args.remote)
    except ReleaseError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        print(f"Error: Command failed: {exc}", file=sys.stderr)
        sys.exit(1)
    print(
        f"Released {result.tag}: {result.old_version} -> {result.new_version} "
        f"({result.tarball_path})"
    )


if __name__ == "__main__":
    main()
