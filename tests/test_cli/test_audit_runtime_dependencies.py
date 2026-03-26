"""Tests for the backend runtime dependency audit recipe."""

from __future__ import annotations

from pathlib import Path


def test_justfile_backend_audit_exports_locked_runtime_requirements_only() -> None:
    justfile = Path(__file__).resolve().parents[2] / "justfile"
    content = justfile.read_text(encoding="utf-8")

    assert 'requirements_file="$(mktemp)"' in content
    assert (
        "uv export --format requirements.txt --no-dev --no-emit-project --frozen"
        ' -o "$requirements_file"' in content
    )
    assert "> /dev/null" in content
    assert 'uv run pip-audit --progress-spinner off --requirement "$requirements_file"' in content
