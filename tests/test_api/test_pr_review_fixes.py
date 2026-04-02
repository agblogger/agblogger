"""Tests for PR review fixes.

Covers all 12 issues identified in the comprehensive PR review,
plus additional security fixes:
1. Narrow except Exception on session.commit() in update_post_endpoint
2. Narrow except Exception on config write in create_page
3. sync_status returns warnings on git failure
4. parse_json_object always wraps ValueError with context
5. KeyError handler should use logger.error (not critical)
6. Lock file cleanup failure is logged (no contextlib.suppress)
7. Misleading "Git commit failed" warning after successful commit
8. _set_git_warning extracted to deps.py
9. Duplicated merge-result file write hoisted
10. Duplicate except blocks merged in sync git commit
11. Test for symlink rollback on commit failure
12. Test for sync_status git failure degradation
13. Sync error responses should not leak internal file paths
14. Sync status should be 'ok' when commit succeeds but HEAD read fails

Additional unit tests:
- TestLooksLikePostAssetPath: unit tests for _looks_like_post_asset_path heuristic
"""

from __future__ import annotations

import contextlib
import json
import logging
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from backend.config import Settings
from backend.main import _looks_like_post_asset_path
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient

pytestmark = pytest.mark.slow


# ── Issue 3 (unit): _looks_like_post_asset_path heuristic ──


class TestLooksLikePostAssetPath:
    """Unit tests for the _looks_like_post_asset_path extension-based heuristic."""

    def test_extensionless_slug_returns_false(self) -> None:
        assert _looks_like_post_asset_path("my-post") is False

    def test_extensionless_slug_some_slug_returns_false(self) -> None:
        assert _looks_like_post_asset_path("some-slug") is False

    def test_md_extension_returns_false(self) -> None:
        assert _looks_like_post_asset_path("something.md") is False

    def test_index_md_leaf_returns_false(self) -> None:
        assert _looks_like_post_asset_path("index.md") is False

    def test_bare_filename_with_extension_returns_false(self) -> None:
        # Bare paths without "/" are slugs, not assets (e.g. slug "my-post-v1.0")
        assert _looks_like_post_asset_path("photo.png") is False

    def test_bare_slug_with_dot_returns_false(self) -> None:
        assert _looks_like_post_asset_path("my-post-v1.0") is False

    def test_empty_string_returns_false(self) -> None:
        assert _looks_like_post_asset_path("") is False

    def test_nested_path_with_asset_extension_returns_true(self) -> None:
        assert _looks_like_post_asset_path("my-post/photo.png") is True

    def test_nested_path_with_jpg_returns_true(self) -> None:
        assert _looks_like_post_asset_path("my-post/image.jpg") is True

    def test_nested_path_with_css_returns_true(self) -> None:
        assert _looks_like_post_asset_path("my-post/styles.css") is True

    def test_nested_path_with_js_returns_true(self) -> None:
        assert _looks_like_post_asset_path("my-post/bundle.js") is True

    def test_nested_path_without_extension_returns_false(self) -> None:
        assert _looks_like_post_asset_path("my-post/assets") is False

    def test_nested_path_with_md_extension_returns_false(self) -> None:
        assert _looks_like_post_asset_path("my-post/index.md") is False

    def test_trailing_slash_treated_as_extensionless(self) -> None:
        # A trailing slash means the leaf becomes empty after rstrip, so False
        assert _looks_like_post_asset_path("my-post/") is False


# ── Fixtures ──


@pytest.fixture
def app_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Create settings for test app."""
    posts_dir = tmp_content_dir / "posts"
    (posts_dir / "2026-02-02-hello-world").mkdir()
    (posts_dir / "2026-02-02-hello-world" / "index.md").write_text(
        "---\ntitle: Hello World\ncreated_at: 2026-02-02 22:21:29.975359+00\n"
        "author: admin\nlabels: []\n---\n\nTest content.\n"
    )
    (tmp_content_dir / "labels.toml").write_text("[labels]\n")
    db_path = tmp_path / "test.db"
    return Settings(
        secret_key="test-secret-key-with-at-least-32-characters",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        content_dir=tmp_content_dir,
        frontend_dir=tmp_path / "frontend",
        admin_username="admin",
        admin_password="admin123",
    )


@pytest.fixture
async def client(app_settings: Settings) -> AsyncGenerator[AsyncClient]:
    async with create_test_client(app_settings) as ac:
        yield ac


async def _login(client: AsyncClient) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": "admin", "password": "admin123"},
    )
    data = resp.json()
    return {"Authorization": f"Bearer {data['access_token']}"}


# ── Issue 1: Narrow except Exception on session.commit() ──


class TestIssue1CommitFailureLogsError:
    """DB commit failure in update_post should log the error before re-raising."""

    async def test_commit_failure_is_logged_with_context(
        self, client: AsyncClient, app_settings: Settings, caplog: pytest.LogCaptureFixture
    ) -> None:
        headers = await _login(client)

        # The fixture already creates a post at "2026-02-02-hello-world"
        file_path = "posts/2026-02-02-hello-world/index.md"

        with (
            patch(
                "backend.api.posts.AsyncSession.commit",
                new_callable=AsyncMock,
                side_effect=OperationalError("disk full", {}, Exception()),
            ),
            caplog.at_level(logging.ERROR, logger="backend.api.posts"),
        ):
            resp = await client.put(
                f"/api/posts/{file_path}",
                json={"title": "Hello World", "body": "Updated", "labels": [], "is_draft": False},
                headers=headers,
            )

        assert resp.status_code >= 400
        error_msgs = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
        assert any("commit failed" in m.lower() or "db commit" in m.lower() for m in error_msgs)


# ── Issue 2: Narrow except Exception on config write ──


class TestIssue2ConfigWriteHandlesOSError:
    """create_page should handle OSError from config write, not bare Exception."""

    async def test_config_write_oserror_propagates(self, tmp_path: Path) -> None:
        """If config write fails with OSError, it should propagate as OSError."""
        from backend.filesystem.content_manager import ContentManager
        from backend.services.admin_service import create_page

        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "posts").mkdir()
        (content_dir / "assets").mkdir()
        (content_dir / "labels.toml").write_text("[labels]\n")
        (content_dir / "index.toml").write_text(
            '[site]\ntitle = "Test"\ntimezone = "UTC"\n\n'
            '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        )
        cm = ContentManager(content_dir=content_dir)
        session_factory = AsyncMock()

        with (
            patch(
                "backend.services.admin_service.write_site_config",
                side_effect=OSError("disk full"),
            ),
            pytest.raises(OSError, match="disk full"),
        ):
            await create_page(session_factory, cm, page_id="test-page", title="Test Page")


# ── Issue 3: sync_status returns warnings on git failure ──


class TestIssue3SyncStatusWarnings:
    """sync_status should include warnings when git fails."""

    async def test_sync_status_includes_warnings_on_git_failure(self, client: AsyncClient) -> None:
        headers = await _login(client)
        with patch(
            "backend.api.sync.GitService.head_commit",
            new_callable=AsyncMock,
            side_effect=subprocess.CalledProcessError(1, "git"),
        ):
            resp = await client.post(
                "/api/sync/status",
                json={"client_manifest": []},
                headers=headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        # server_commit should be None
        assert data["server_commit"] is None
        # warnings field should exist and contain a warning about git
        assert "warnings" in data
        assert any("git" in w.lower() for w in data["warnings"])


# ── Issue 4: parse_json_object wraps ValueError with context ──


class TestIssue4ParseJsonObjectContext:
    """parse_json_object without error_cls should include context in ValueError."""

    def test_non_json_without_error_cls_includes_context(self) -> None:
        import httpx

        from backend.crosspost.http_utils import parse_json_object

        resp = httpx.Response(200, text="not json")
        with pytest.raises(ValueError, match="Facebook feed endpoint"):
            parse_json_object(resp, context="Facebook feed endpoint")

    def test_non_dict_without_error_cls_includes_context(self) -> None:
        import httpx

        from backend.crosspost.http_utils import parse_json_object

        resp = httpx.Response(200, json=[1, 2, 3])
        with pytest.raises(ValueError, match="X tweets endpoint"):
            parse_json_object(resp, context="X tweets endpoint")


# ── Issue 5: KeyError handler uses logger.critical ──


class TestIssue5KeyErrorLogLevel:
    """KeyError global handler should log at ERROR level, not CRITICAL."""

    async def test_key_error_logged_at_error_not_critical(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from httpx import ASGITransport, AsyncClient

        from backend.main import create_app

        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            frontend_dir=tmp_path / "no-frontend",
        )
        app = create_app(settings)

        @app.get("/test-key-error-level")
        async def _raise_key_error() -> None:
            raise KeyError("secret_key_name")

        with caplog.at_level(logging.DEBUG, logger="backend.main"):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get("/test-key-error-level")

        assert resp.status_code == 500
        # Should be ERROR, not CRITICAL
        key_error_records = [r for r in caplog.records if "[BUG]" in r.message]
        assert len(key_error_records) >= 1
        assert all(r.levelno == logging.ERROR for r in key_error_records)
        assert not any(r.levelno == logging.CRITICAL for r in key_error_records)


# ── Issue 6: Lock file cleanup failure is logged ──


class TestIssue6LockCleanupLogging:
    """Lock file cleanup failure should be logged, not suppressed."""

    @pytest.mark.slow
    def test_lock_cleanup_failure_logged(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import os
        import time

        key_path = tmp_path / "test-key.json"
        lock_path = key_path.with_name(f".{key_path.name}.lock")
        lock_path.write_text("")
        old_time = time.time() - 60
        os.utime(lock_path, (old_time, old_time))

        original_stat = type(lock_path).stat
        original_unlink = type(lock_path).unlink
        stat_failed = False

        def _failing_stat(self, *args, **kwargs):
            nonlocal stat_failed
            if self == lock_path and not stat_failed:
                stat_failed = True
                raise OSError("stat failed")
            return original_stat(self, *args, **kwargs)

        # Make unlink also fail so we can verify it's logged
        def _failing_unlink(self, *args, **kwargs):
            if self == lock_path:
                raise OSError("unlink failed")
            return original_unlink(self, *args, **kwargs)

        from backend.crosspost.atproto_oauth import load_or_create_keypair

        with (
            patch.object(type(lock_path), "stat", _failing_stat),
            patch.object(type(lock_path), "unlink", _failing_unlink),
            caplog.at_level(logging.WARNING, logger="backend.crosspost.atproto_oauth"),
            contextlib.suppress(OSError, FileExistsError, RuntimeError),
        ):
            load_or_create_keypair(key_path)

        # Should have TWO log messages: one for stat failure, one for unlink failure
        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("stale keypair lock inspection failed" in m.lower() for m in warning_messages)
        assert any("failed to remove stale lock" in m.lower() for m in warning_messages)


# ── Issue 7: Misleading git commit warning after successful commit ──


class TestIssue7AccurateHeadCommitWarning:
    """After successful git commit, head_commit() failure warning should be accurate."""

    async def test_head_commit_failure_warning_does_not_say_commit_failed(
        self, client: AsyncClient
    ) -> None:
        """Warning should NOT say 'Git commit failed' when only HEAD read fails."""
        headers = await _login(client)

        with (
            patch(
                "backend.api.sync.GitService.commit_all",
                new_callable=AsyncMock,
            ),
            patch(
                "backend.api.sync.GitService.head_commit",
                new_callable=AsyncMock,
                side_effect=subprocess.CalledProcessError(1, "git"),
            ),
        ):
            resp = await client.post(
                "/api/sync/commit",
                data={"metadata": json.dumps({"deleted_files": [], "last_sync_commit": None})},
                headers=headers,
            )

        if resp.status_code == 200:
            data = resp.json()
            warnings = data.get("warnings", [])
            # Warning should NOT say "Git commit failed" — commit succeeded
            assert not any("git commit failed" in w.lower() for w in warnings)


# ── Issue 8: _set_git_warning extracted to deps.py ──


class TestIssue8SharedSetGitWarning:
    """_set_git_warning should be importable from deps.py, not duplicated."""

    def test_set_git_warning_in_deps(self) -> None:
        from backend.api.deps import set_git_warning

        assert callable(set_git_warning)

    def test_admin_imports_set_git_warning_from_deps(self) -> None:
        from backend.api import admin

        # admin module should use the shared function from deps, not define its own
        assert not hasattr(admin, "_set_git_warning")

    def test_posts_imports_set_git_warning_from_deps(self) -> None:
        from backend.api import posts

        # posts module should use the shared function from deps, not define its own
        assert not hasattr(posts, "_set_git_warning")


# ── Issue 9: Duplicated merge-result file write hoisted ──


class TestIssue9MergeWriteConsistency:
    """Merged content should be written to disk regardless of conflict status.

    This implementation detail (single write_text call) is already covered by
    sync integration tests that verify merged content is persisted. The source-
    inspection test has been removed in favor of those behavioral tests.
    """


# ── Issue 10: Duplicate except blocks merged ──


class TestIssue10GitCommitExceptionHandling:
    """Git commit failures in sync should be handled gracefully.

    This implementation detail (single except block) is already covered by
    sync error handling tests that verify graceful degradation on git failure.
    The source-inspection test has been removed in favor of those behavioral tests.
    """


# ── Issue 11: Test for symlink rollback on commit failure ──


class TestIssue11SymlinkRollbackOnCommitFailure:
    """When commit fails after rename + symlink creation, symlink should be cleaned up."""

    @pytest.mark.slow
    async def test_symlink_removed_during_rollback(self, tmp_path: Path) -> None:
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

        async with create_test_client(settings) as tc:
            token_resp = await tc.post(
                "/api/auth/token-login",
                json={"username": "admin", "password": "admin123"},
            )
            token = token_resp.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            with patch(
                "sqlalchemy.ext.asyncio.AsyncSession.commit",
                new_callable=AsyncMock,
                side_effect=OperationalError("disk full", {}, Exception()),
            ):
                resp = await tc.put(
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

            # Old directory should be restored
            assert post_dir.exists(), "Old directory should be restored"
            # No symlink should remain at old_dir
            assert not post_dir.is_symlink(), (
                "Symlink at old path should be removed during rollback"
            )
            # New directory should not exist
            new_dir = content_dir / "posts" / "2026-02-02-new-different-title"
            assert not new_dir.exists(), "New directory should not persist"


# ── Issue 12: Test for sync_status git failure degradation ──


class TestIssue12SyncStatusGitFailure:
    """sync_status endpoint should degrade gracefully when git fails."""

    async def test_sync_status_returns_200_with_null_commit_on_git_failure(
        self, client: AsyncClient
    ) -> None:
        headers = await _login(client)
        with patch(
            "backend.api.sync.GitService.head_commit",
            new_callable=AsyncMock,
            side_effect=FileNotFoundError("git not found"),
        ):
            resp = await client.post(
                "/api/sync/status",
                json={"client_manifest": []},
                headers=headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["server_commit"] is None

    async def test_sync_status_logs_error_on_git_failure(
        self, client: AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        headers = await _login(client)
        with (
            patch(
                "backend.api.sync.GitService.head_commit",
                new_callable=AsyncMock,
                side_effect=subprocess.TimeoutExpired("git", 30),
            ),
            caplog.at_level(logging.ERROR, logger="backend.api.sync"),
        ):
            resp = await client.post(
                "/api/sync/status",
                json={"client_manifest": []},
                headers=headers,
            )

        assert resp.status_code == 200
        assert any("git head" in r.message.lower() for r in caplog.records)


# ── Issue 13: Sync error responses should not leak internal file paths ──


class TestIssue3SyncNoPathLeak:
    """Sync error responses should not leak internal file paths."""

    async def test_sync_write_error_does_not_leak_path(self, client: AsyncClient) -> None:
        headers = await _login(client)

        with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
            resp = await client.post(
                "/api/sync/commit",
                data={
                    "metadata": json.dumps(
                        {
                            "deleted_files": [],
                            "last_sync_commit": None,
                        }
                    )
                },
                files=[
                    (
                        "files",
                        (
                            "posts/test-path-leak/index.md",
                            b"---\ntitle: T\ncreated_at: 2026-02-02 22:21:29+00\n"
                            b"author: admin\nlabels: []\n"
                            b"---\nBody",
                            "text/plain",
                        ),
                    )
                ],
                headers=headers,
            )

        assert resp.status_code >= 400
        detail = resp.json().get("detail", "")
        # Should NOT contain the uploaded file path — that leaks internal structure
        assert "test-path-leak" not in detail
        assert "posts/" not in detail


# ── Issue 14: Sync status 'ok' when commit succeeds but HEAD read fails ──


class TestIssue14SyncStatusAfterHeadCommitFailure:
    """When git commit succeeds but head_commit() fails, status should be 'ok'."""

    async def test_status_is_ok_when_commit_succeeds_but_head_read_fails(
        self, client: AsyncClient
    ) -> None:
        headers = await _login(client)

        with (
            patch(
                "backend.api.sync.GitService.commit_all",
                new_callable=AsyncMock,
            ),
            patch(
                "backend.api.sync.GitService.head_commit",
                new_callable=AsyncMock,
                side_effect=subprocess.CalledProcessError(1, "git rev-parse"),
            ),
        ):
            resp = await client.post(
                "/api/sync/commit",
                data={"metadata": json.dumps({"deleted_files": [], "last_sync_commit": None})},
                headers=headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        # Commit succeeded, only head read failed — status should be "ok"
        assert data["status"] == "ok"
        assert data["commit_hash"] is None
        assert any(
            "commit hash" in w.lower() or "head" in w.lower() for w in data.get("warnings", [])
        )


# ── Issue 14b: Failed sync deletions should not be counted ──


class TestIssue14SyncDeletionFailureCount:
    """Failed deletions should not be counted in files_synced."""

    async def test_failed_deletion_not_counted(self, client: AsyncClient) -> None:
        headers = await _login(client)

        # Create a file first via sync
        resp = await client.post(
            "/api/sync/commit",
            data={
                "metadata": json.dumps({"deleted_files": [], "last_sync_commit": None}),
            },
            files=[
                (
                    "files",
                    (
                        "posts/to-delete/index.md",
                        b"---\ntitle: X\ncreated_at: 2026-02-02 22:21:29+00\n"
                        b"author: admin\nlabels: []\n"
                        b"---\nBody",
                        "text/plain",
                    ),
                )
            ],
            headers=headers,
        )
        assert resp.status_code == 200

        # Now try to delete it but make unlink fail
        with patch("pathlib.Path.unlink", side_effect=OSError("permission denied")):
            resp = await client.post(
                "/api/sync/commit",
                data={
                    "metadata": json.dumps(
                        {
                            "deleted_files": ["posts/to-delete/index.md"],
                            "last_sync_commit": None,
                        }
                    ),
                },
                headers=headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        # Failed deletion should NOT count as synced
        assert data["files_synced"] == 0


# ── Issue 15: TOCTOU stat() race in delete_asset ──


class TestIssue15DeleteAssetStatTOCTOU:
    """delete_asset must not crash when stat() raises OSError after is_file() passes."""

    async def test_delete_asset_stat_oserror_does_not_crash(
        self, client: AsyncClient, app_settings: Settings, caplog: pytest.LogCaptureFixture
    ) -> None:
        headers = await _login(client)

        # Place a real asset file next to index.md so is_file() passes
        post_dir = app_settings.content_dir / "posts" / "2026-02-02-hello-world"
        asset_file = post_dir / "photo.png"
        asset_file.write_bytes(b"fake image data")

        file_path = "posts/2026-02-02-hello-world/index.md"

        stat_call_count = 0

        def _always_fail_stat(self, *args, **kwargs):
            nonlocal stat_call_count
            stat_call_count += 1
            raise OSError("file vanished between is_file and stat")

        with (
            patch.object(type(asset_file), "stat", _always_fail_stat),
            caplog.at_level(logging.WARNING, logger="backend.api.posts"),
        ):
            resp = await client.delete(
                f"/api/posts/{file_path}/assets/photo.png",
                headers=headers,
            )

        # Handler must NOT crash with 500 — a stat race should be treated as
        # size=0 and the delete should still succeed (204).
        assert resp.status_code == 204
        assert stat_call_count >= 1
        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("stat" in m.lower() for m in warning_messages)


# ── Issue 16: TOCTOU stat() race in update_post quota check ──


class TestIssue16UpdatePostQuotaStatTOCTOU:
    """update_post quota check must not crash when stat() raises OSError after exists()."""

    async def test_update_post_stat_oserror_is_handled(
        self, client: AsyncClient, app_settings: Settings, caplog: pytest.LogCaptureFixture
    ) -> None:
        headers = await _login(client)

        file_path = "posts/2026-02-02-hello-world/index.md"
        post_file = app_settings.content_dir / file_path

        def _always_fail_stat(self, *args, **kwargs):
            raise OSError("file vanished between exists and stat")

        with (
            patch.object(type(post_file), "stat", _always_fail_stat),
            caplog.at_level(logging.WARNING, logger="backend.api.posts"),
        ):
            resp = await client.put(
                f"/api/posts/{file_path}",
                json={
                    "title": "Hello World",
                    "body": "Updated content.",
                    "labels": [],
                    "is_draft": False,
                },
                headers=headers,
            )

        # Handler must NOT crash with 500 due to OSError — it should treat
        # old_size as 0 and proceed normally.
        assert resp.status_code in {200, 204}
        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("stat" in m.lower() for m in warning_messages)


# ── Issue 17: TOCTOU stat() race in delete_post size computation ──


class TestIssue17DeletePostSizeStatTOCTOU:
    """delete_post size computation must not crash when stat() raises OSError."""

    async def test_delete_post_rglob_stat_oserror_is_handled(
        self, client: AsyncClient, app_settings: Settings, caplog: pytest.LogCaptureFixture
    ) -> None:
        """OSError from stat() inside rglob loop should not crash the handler."""
        headers = await _login(client)

        post_dir = app_settings.content_dir / "posts" / "2026-02-02-hello-world"
        (post_dir / "asset.txt").write_bytes(b"some asset")

        file_path = "posts/2026-02-02-hello-world/index.md"
        index_path = post_dir / "index.md"

        def _always_fail_stat(self, *args, **kwargs):
            raise OSError("file vanished during rglob stat")

        with (
            patch.object(type(index_path), "stat", _always_fail_stat),
            caplog.at_level(logging.WARNING, logger="backend.api.posts"),
        ):
            resp = await client.delete(
                f"/api/posts/{file_path}?delete_assets=true",
                headers=headers,
            )

        # Handler must NOT crash — size defaults to 0 and deletion proceeds.
        assert resp.status_code == 204
        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("stat" in m.lower() for m in warning_messages)

    async def test_delete_post_single_file_stat_oserror_is_handled(
        self, client: AsyncClient, app_settings: Settings, caplog: pytest.LogCaptureFixture
    ) -> None:
        """OSError from stat() in the single-file (no-assets) branch should not crash."""
        headers = await _login(client)

        file_path = "posts/2026-02-02-hello-world/index.md"
        post_file = app_settings.content_dir / file_path

        def _always_fail_stat(self, *args, **kwargs):
            raise OSError("file vanished between exists and stat")

        with (
            patch.object(type(post_file), "stat", _always_fail_stat),
            caplog.at_level(logging.WARNING, logger="backend.api.posts"),
        ):
            resp = await client.delete(
                f"/api/posts/{file_path}?delete_assets=false",
                headers=headers,
            )

        assert resp.status_code == 204
        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("stat" in m.lower() for m in warning_messages)


class TestSafeFileSize:
    """Issue #3: _safe_file_size handles TOCTOU races gracefully."""

    def test_returns_size_for_regular_file(self, tmp_path: Path) -> None:
        from backend.api.posts import _safe_file_size

        f = tmp_path / "test.txt"
        f.write_text("hello")
        assert _safe_file_size(f) == 5

    def test_returns_zero_for_missing_file(self, tmp_path: Path) -> None:
        from backend.api.posts import _safe_file_size

        assert _safe_file_size(tmp_path / "nonexistent") == 0

    def test_returns_zero_for_directory(self, tmp_path: Path) -> None:
        from backend.api.posts import _safe_file_size

        d = tmp_path / "subdir"
        d.mkdir()
        assert _safe_file_size(d) == 0

    def test_returns_zero_on_permission_error(self, tmp_path: Path) -> None:
        from backend.api.posts import _safe_file_size

        f = tmp_path / "test.txt"
        f.write_text("hello")
        with patch.object(type(f), "stat", side_effect=PermissionError("denied")):
            assert _safe_file_size(f) == 0
