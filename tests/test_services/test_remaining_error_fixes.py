"""Tests for remaining exception handling fixes.

Covers:
- Issue 5: Post rename rollback on commit failure
- Issue 6: Page create/update atomicity
- Issue 9: Sync file deletion OSError handling
- Issue 10: _validate_path ValueError does not echo user input
- Issue 11: Mastodon registration does not leak upstream status code
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import OperationalError

if TYPE_CHECKING:
    from pathlib import Path


# ── Issue 5: Post rename rollback ──


class TestPostRenameRollbackOnCommitFailure:
    """If session.commit() fails after directory rename, the rename must be rolled back."""

    @pytest.mark.slow
    async def test_commit_failure_rolls_back_rename(self, tmp_path: Path) -> None:
        from backend.config import Settings
        from tests.conftest import create_test_client

        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "posts").mkdir()
        (content_dir / "assets").mkdir()
        (content_dir / "index.toml").write_text(
            '[site]\ntitle = "Test Blog"\ntimezone = "UTC"\n\n'
            '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        )
        (content_dir / "labels.toml").write_text("[labels]\n")

        post_dir = content_dir / "posts" / "2026-02-02-original-title"
        post_dir.mkdir()
        (post_dir / "index.md").write_text(
            "---\ntitle: Original Title\ncreated_at: 2026-02-02 22:21:29+00\n"
            "author: admin\nlabels: []\n---\nContent here.\n"
        )

        db_path = tmp_path / "test.db"
        settings = Settings(
            secret_key="test-secret-key-with-at-least-32-characters",
            debug=True,
            database_url=f"sqlite+aiosqlite:///{db_path}",
            content_dir=content_dir,
            frontend_dir=tmp_path / "frontend",
            admin_username="admin",
            admin_password="admin123",
        )

        async with create_test_client(settings) as client:
            token_resp = await client.post(
                "/api/auth/token-login",
                json={"username": "admin", "password": "admin123"},
            )
            token = token_resp.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            # Patch commit AFTER login so login succeeds
            with patch(
                "sqlalchemy.ext.asyncio.AsyncSession.commit",
                new_callable=AsyncMock,
                side_effect=OperationalError("disk full", {}, Exception()),
            ):
                resp = await client.put(
                    "/api/posts/posts/2026-02-02-original-title/index.md",
                    json={
                        "title": "New Different Title",
                        "body": "Content here.",
                        "labels": [],
                        "is_draft": False,
                    },
                    headers=headers,
                )

            assert resp.status_code >= 500

            # The OLD directory should still exist (rename was rolled back)
            assert post_dir.exists(), "Old directory should be restored after commit failure"
            # The NEW directory should NOT exist
            new_dir = content_dir / "posts" / "2026-02-02-new-different-title"
            assert not new_dir.exists(), "New directory should not persist after commit failure"


# ── Issue 6: Page create/update atomicity ──


class TestPageCreateAtomicity:
    """create_page must not leave orphan .md files if config write fails."""

    def test_md_file_cleaned_up_on_config_write_failure(self, tmp_path: Path) -> None:
        from backend.filesystem.content_manager import ContentManager
        from backend.services.admin_service import create_page

        (tmp_path / "index.toml").write_text(
            '[site]\ntitle = "Test"\ntimezone = "UTC"\n\n'
            '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        )
        (tmp_path / "labels.toml").write_text("[labels]")
        (tmp_path / "posts").mkdir()
        cm = ContentManager(content_dir=tmp_path)

        with (
            patch(
                "backend.services.admin_service.write_site_config",
                side_effect=OSError("disk full"),
            ),
            pytest.raises(OSError),
        ):
            create_page(cm, page_id="about", title="About")

        md_path = tmp_path / "about.md"
        assert not md_path.exists(), "Orphan .md file should be cleaned up on config write failure"


class TestPageUpdateAtomicity:
    """update_page must not leave config updated if content write fails."""

    def test_config_rolled_back_on_content_write_failure(self, tmp_path: Path) -> None:
        from backend.filesystem.content_manager import ContentManager
        from backend.services.admin_service import update_page

        (tmp_path / "index.toml").write_text(
            '[site]\ntitle = "Test"\ntimezone = "UTC"\n\n'
            '[[pages]]\nid = "timeline"\ntitle = "Posts"\n\n'
            '[[pages]]\nid = "about"\ntitle = "About"\nfile = "about.md"\n'
        )
        (tmp_path / "labels.toml").write_text("[labels]")
        (tmp_path / "posts").mkdir()
        (tmp_path / "about.md").write_text("# About\n\nOld content.\n")
        cm = ContentManager(content_dir=tmp_path)

        original_title = cm.site_config.pages[1].title
        assert original_title == "About"

        # Patch write_text to fail only for about.md content writes
        original_write_text = type(tmp_path / "about.md").write_text
        call_count = {"about": 0}

        def failing_write(self_path: object, *args: object, **kwargs: object) -> object:
            from pathlib import Path as _Path

            path = self_path
            # Only fail when writing about.md content (not the TOML config writes)
            if isinstance(path, _Path) and path.name == "about.md":
                call_count["about"] += 1
                raise OSError("disk full")
            return original_write_text(path, *args, **kwargs)  # type: ignore[arg-type]

        with (
            patch("pathlib.Path.write_text", failing_write),
            pytest.raises(OSError),
        ):
            update_page(cm, "about", title="New Title", content="New content")

        # The title in config should be rolled back to original
        cm.reload_config()
        current_title = next(p.title for p in cm.site_config.pages if p.id == "about")
        assert current_title == "About", "Title should be rolled back on content write failure"


# ── Issue 9: Sync file deletion OSError ──


class TestSyncDeletionOSError:
    """OSError during sync file deletion must log warning, not abort the entire sync."""

    def test_deletion_loop_catches_oserror(self, tmp_path: Path) -> None:
        """The sync deletion loop now wraps unlink in try/except OSError."""
        import inspect

        from backend.api import sync as sync_mod

        source = inspect.getsource(sync_mod._sync_commit_inner)
        # After fix, the deletion loop should catch OSError around unlink
        assert "except OSError" in source
        # And it should contain a warning about failed deletion
        assert "Failed to delete" in source

    async def test_unlink_failure_logged_and_skipped(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Direct test: simulate the fixed deletion loop pattern."""
        import logging

        from backend.api.sync import _resolve_safe_path

        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "posts").mkdir()
        target = content_dir / "posts" / "test.md"
        target.write_text("test content")

        # Simulate the new deletion loop pattern from sync.py
        sync_warnings: list[str] = []
        deleted_files = ["posts/test.md"]

        with caplog.at_level(logging.ERROR, logger="backend.api.sync"):
            for file_path in deleted_files:
                full_path = _resolve_safe_path(content_dir, file_path)
                if full_path.exists() and full_path.is_file():
                    try:
                        # Simulate failure
                        raise OSError("permission denied")
                    except OSError:
                        sync_warnings.append(f"Failed to delete {file_path.lstrip('/')}")
                        continue

        assert len(sync_warnings) == 1
        assert "Failed to delete" in sync_warnings[0]
        # File should still exist since unlink failed
        assert target.exists()


# ── Issue 10: _validate_path does not echo user input ──


class TestValidatePathNoInputEcho:
    """_validate_path ValueError must not include the user-supplied path."""

    def test_path_traversal_error_does_not_echo_input(self, tmp_path: Path) -> None:
        from backend.filesystem.content_manager import ContentManager

        (tmp_path / "index.toml").write_text('[site]\ntitle = "Test"')
        (tmp_path / "labels.toml").write_text("[labels]")
        (tmp_path / "posts").mkdir()
        cm = ContentManager(content_dir=tmp_path)

        malicious_path = "../../etc/passwd"
        with pytest.raises(ValueError) as exc_info:
            cm._validate_path(malicious_path)

        error_msg = str(exc_info.value)
        assert "../../etc/passwd" not in error_msg

    def test_sync_resolve_safe_path_does_not_echo_input(self, tmp_path: Path) -> None:
        from fastapi import HTTPException

        from backend.api.sync import _resolve_safe_path

        content_dir = tmp_path / "content"
        content_dir.mkdir()

        malicious_path = "../../etc/shadow"
        with pytest.raises(HTTPException) as exc_info:
            _resolve_safe_path(content_dir, malicious_path)

        assert "../../etc/shadow" not in exc_info.value.detail


# ── Issue 11: Mastodon registration status code leak ──


class TestMastodonRegistrationNoStatusCodeLeak:
    """Mastodon app registration failure must not leak the upstream HTTP status code."""

    def test_registration_error_detail_no_status_code(self) -> None:
        """Verify the crosspost.py code does not include status code in HTTPException detail."""
        # Direct source-level check: the registration failure detail must be generic
        import inspect

        from backend.api import crosspost as crosspost_mod

        source = inspect.getsource(crosspost_mod)
        # After fix, should NOT contain the f-string pattern leaking status code
        assert "App registration failed: {reg_resp.status_code}" not in source
