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
    from collections.abc import AsyncGenerator
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

    async def test_md_file_cleaned_up_on_config_write_failure(self, tmp_path: Path) -> None:
        from backend.filesystem.content_manager import ContentManager
        from backend.services.admin_service import create_page

        (tmp_path / "index.toml").write_text(
            '[site]\ntitle = "Test"\ntimezone = "UTC"\n\n'
            '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        )
        (tmp_path / "labels.toml").write_text("[labels]")
        (tmp_path / "posts").mkdir()
        cm = ContentManager(content_dir=tmp_path)
        session_factory = AsyncMock()

        with (
            patch(
                "backend.services.admin_service.write_site_config",
                side_effect=OSError("disk full"),
            ),
            pytest.raises(OSError),
        ):
            await create_page(session_factory, cm, page_id="about", title="About")

        md_path = tmp_path / "about.md"
        assert not md_path.exists(), "Orphan .md file should be cleaned up on config write failure"


class TestPageUpdateAtomicity:
    """update_page must not leave config updated if content write fails."""

    async def test_config_rolled_back_on_content_write_failure(self, tmp_path: Path) -> None:
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
        session_factory = AsyncMock()

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
            await update_page(
                session_factory, cm, "about", title="New Title", content="New content"
            )

        # The title in config should be rolled back to original
        cm.reload_config()
        current_title = next(p.title for p in cm.site_config.pages if p.id == "about")
        assert current_title == "About", "Title should be rolled back on content write failure"


# ── Issue 9: Sync file deletion OSError ──


class TestSyncDeletionOSError:
    """OSError during sync file deletion must log warning, not abort the entire sync."""

    async def test_unlink_oserror_logged_and_skipped(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Patch Path.unlink to raise OSError and call _sync_commit_inner.

        Verifies the real sync deletion loop logs a warning and continues
        instead of aborting.
        """
        import json
        import logging
        from pathlib import Path as _Path
        from unittest.mock import MagicMock

        from backend.api.sync import _sync_commit_inner
        from backend.filesystem.content_manager import ContentManager

        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "posts").mkdir()
        (content_dir / "assets").mkdir()
        (content_dir / "index.toml").write_text(
            '[site]\ntitle = "Test"\ntimezone = "UTC"\n\n'
            '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        )
        (content_dir / "labels.toml").write_text("[labels]\n")

        # Create a file that sync will try to delete
        target = content_dir / "posts" / "doomed" / "index.md"
        target.parent.mkdir()
        target.write_text("---\ntitle: Doomed\n---\nContent.\n")

        cm = ContentManager(content_dir=content_dir)

        # Mock git service and session objects
        mock_git = MagicMock()
        mock_git.commit_all = AsyncMock()
        mock_git.head_commit = AsyncMock(return_value="abc123")

        from backend.services.storage_quota import ContentSizeTracker

        mock_session = AsyncMock()
        mock_session_factory = MagicMock()
        mock_user = MagicMock(id=1, username="admin", display_name="Admin")
        mock_tracker = ContentSizeTracker(content_dir=content_dir, max_size=None)

        metadata = json.dumps({"deleted_files": ["posts/doomed/index.md"]})

        original_unlink = _Path.unlink

        def _failing_unlink(self: _Path, missing_ok: bool = False) -> None:
            if self.name == "index.md":
                raise OSError("permission denied")
            original_unlink(self, missing_ok=missing_ok)

        with (
            caplog.at_level(logging.ERROR, logger="backend.api.sync"),
            patch.object(_Path, "unlink", _failing_unlink),
            patch("backend.api.sync.get_server_manifest", new_callable=AsyncMock, return_value={}),
            patch("backend.api.sync.scan_content_files", return_value={}),
            patch("backend.api.sync.update_server_manifest", new_callable=AsyncMock),
            patch(
                "backend.services.cache_service.rebuild_cache",
                new_callable=AsyncMock,
                return_value=(0, []),
            ),
        ):
            result = await _sync_commit_inner(
                metadata_json=metadata,
                upload_files=[],
                session=mock_session,
                session_factory=mock_session_factory,
                content_manager=cm,
                git_service=mock_git,
                user=mock_user,
                content_size_tracker=mock_tracker,
            )

        # The file should still exist since unlink failed
        assert target.exists()

        # The sync should have continued (not aborted) and reported a warning
        assert any("Failed to delete" in w for w in result.warnings)

        # Verify it was logged
        assert any("failed to delete" in r.message.lower() for r in caplog.records)


class TestSyncPruneBoundaries:
    """Empty-directory pruning must stop at the canonical content root."""

    def test_prune_empty_directories_stops_at_resolved_symlink_root(self, tmp_path: Path) -> None:
        from backend.api.sync import _prune_empty_directories

        real_root_parent = tmp_path / "real-root-parent"
        real_root_parent.mkdir()
        real_content_dir = real_root_parent / "content-real"
        nested_dir = real_content_dir / "posts" / "hello"
        nested_dir.mkdir(parents=True)

        symlink_content_dir = tmp_path / "content-link"
        symlink_content_dir.symlink_to(real_content_dir, target_is_directory=True)

        _prune_empty_directories(nested_dir, stop_at=symlink_content_dir)

        assert real_content_dir.exists()
        assert real_root_parent.exists()
        assert not nested_dir.exists()
        assert not (real_content_dir / "posts").exists()


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

    @pytest.mark.slow
    async def test_registration_failure_does_not_leak_status_code(self, tmp_path: Path) -> None:
        """Mock Mastodon registration to return non-200 and verify the error detail is generic."""
        import httpx

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

        db_path = tmp_path / "test.db"
        settings = Settings(
            secret_key="test-secret-key-with-at-least-32-characters",
            debug=True,
            database_url=f"sqlite+aiosqlite:///{db_path}",
            content_dir=content_dir,
            frontend_dir=tmp_path / "frontend",
            admin_username="admin",
            admin_password="admin123",
            bluesky_client_url="https://myblog.example.com",
        )

        async with create_test_client(settings) as client:
            token_resp = await client.post(
                "/api/auth/token-login",
                json={"username": "admin", "password": "admin123"},
            )
            token = token_resp.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            # Mock the SSRF-safe HTTP client to return a non-200 response
            from contextlib import asynccontextmanager

            mock_response = httpx.Response(
                status_code=403,
                request=httpx.Request("POST", "https://mastodon.social/api/v1/apps"),
            )
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)

            @asynccontextmanager
            async def mock_ssrf_client(**_kw: object) -> AsyncGenerator[AsyncMock]:
                yield mock_http

            with patch(
                "backend.crosspost.ssrf.ssrf_safe_client",
                mock_ssrf_client,
            ):
                resp = await client.post(
                    "/api/crosspost/mastodon/authorize",
                    json={"instance_url": "https://mastodon.social"},
                    headers=headers,
                )

            assert resp.status_code == 502
            detail = resp.json()["detail"]
            # The detail must NOT contain the upstream numeric status code
            assert "403" not in detail
            # It should use a generic message
            assert "registration failed" in detail.lower()
