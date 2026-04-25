"""Tests for the ``write_managed_block`` bash helper in setup.sh.

The helper merges deploy-script-managed content into a file while preserving
operator customizations outside the marker block. We exercise the function by
piping its source into ``bash`` and asserting the resulting file state, so the
critical bash logic is covered (not just the Python wrapper).
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from cli.deploy_production import (
    SHARED_MANAGED_BEGIN_MARKER,
    SHARED_MANAGED_END_MARKER,
    SHARED_MANAGED_FOOTER_HINT,
    build_write_managed_block_function,
)

if TYPE_CHECKING:
    from pathlib import Path

if shutil.which("bash") is None:
    pytest.skip("bash not available in this environment", allow_module_level=True)


def _run_with_helper(
    *,
    target: Path,
    new_content: str,
    script: str,
) -> subprocess.CompletedProcess[str]:
    """Run ``script`` with ``write_managed_block`` defined and ``new_content`` on stdin."""
    helper = build_write_managed_block_function()
    full_script = (
        "set -euo pipefail\n"
        f"{helper}\n"
        # The caller's snippet sees $TARGET as the file under test.
        f"TARGET={target!s}\n"
        f"{script}\n"
    )
    return subprocess.run(
        ["bash", "-c", full_script],
        input=new_content,
        capture_output=True,
        text=True,
        check=False,
    )


def _read(target: Path) -> str:
    return target.read_text(encoding="utf-8")


def test_first_install_creates_file_with_markers(tmp_path: Path) -> None:
    target = tmp_path / "Caddyfile"
    new = "managed line 1\nmanaged line 2"

    result = _run_with_helper(
        target=target,
        new_content=new,
        script='write_managed_block "$TARGET"',
    )

    assert result.returncode == 0, result.stderr
    body = _read(target)
    assert SHARED_MANAGED_BEGIN_MARKER in body
    assert SHARED_MANAGED_END_MARKER in body
    assert "managed line 1" in body
    assert "managed line 2" in body
    assert SHARED_MANAGED_FOOTER_HINT in body


def test_subsequent_deploy_replaces_only_managed_region(tmp_path: Path) -> None:
    """Existing file with markers: managed region updated, custom region kept."""
    target = tmp_path / "Caddyfile"
    target.write_text(
        f"{SHARED_MANAGED_BEGIN_MARKER}\n"
        "old managed content\n"
        f"{SHARED_MANAGED_END_MARKER}\n"
        "\n"
        "# Operator customization below\n"
        "(common) {\n"
        "    log\n"
        "}\n",
        encoding="utf-8",
    )

    result = _run_with_helper(
        target=target,
        new_content="new managed content",
        script='write_managed_block "$TARGET"',
    )

    assert result.returncode == 0, result.stderr
    body = _read(target)
    # Managed region was updated.
    assert "new managed content" in body
    assert "old managed content" not in body
    # Customizations outside the markers are preserved verbatim.
    assert "# Operator customization below" in body
    assert "(common) {" in body
    assert "    log" in body
    # No backup was created — markers were present, so no legacy migration ran.
    backups = list(tmp_path.glob("Caddyfile.bak.*"))
    assert backups == []


def test_legacy_file_without_markers_is_backed_up_and_rewritten(tmp_path: Path) -> None:
    target = tmp_path / "Caddyfile"
    legacy = "{\n    email old@example.com\n}\n\nimport /etc/caddy/sites/*.caddy\n"
    target.write_text(legacy, encoding="utf-8")

    result = _run_with_helper(
        target=target,
        new_content="fresh managed content",
        script='write_managed_block "$TARGET"',
    )

    assert result.returncode == 0, result.stderr
    # The new file is the managed template.
    body = _read(target)
    assert SHARED_MANAGED_BEGIN_MARKER in body
    assert "fresh managed content" in body
    # The original legacy content was backed up, not lost.
    backups = list(tmp_path.glob("Caddyfile.bak.*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == legacy
    # Operator gets a heads-up on stderr.
    assert "backed up" in result.stderr


def test_round_trip_preserves_custom_content_across_two_deploys(tmp_path: Path) -> None:
    target = tmp_path / "Caddyfile"

    # First install.
    first = _run_with_helper(
        target=target,
        new_content="v1 managed",
        script='write_managed_block "$TARGET"',
    )
    assert first.returncode == 0, first.stderr

    # Operator appends customization.
    target.write_text(
        _read(target) + "\n# operator note\nlog_extra_directive\n",
        encoding="utf-8",
    )

    # Second deploy with new managed content.
    second = _run_with_helper(
        target=target,
        new_content="v2 managed updated",
        script='write_managed_block "$TARGET"',
    )
    assert second.returncode == 0, second.stderr

    body = _read(target)
    assert "v2 managed updated" in body
    assert "v1 managed" not in body
    assert "# operator note" in body
    assert "log_extra_directive" in body


def test_managed_content_with_special_chars_is_preserved(tmp_path: Path) -> None:
    """Brackets, quotes, dollar signs in the new content must round-trip cleanly."""
    target = tmp_path / "Caddyfile"
    tricky = (
        "{\n"
        "    servers { protocols h1 h2 h3 }\n"
        '    email "admin@example.com"\n'
        "}\n"
        "\n"
        '@m path "/api/*"\n'
    )

    result = _run_with_helper(
        target=target,
        new_content=tricky,
        script='write_managed_block "$TARGET"',
    )

    assert result.returncode == 0, result.stderr
    body = _read(target)
    assert tricky.strip() in body
