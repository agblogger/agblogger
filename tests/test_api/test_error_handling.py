"""Tests for targeted error handling in API endpoints.

Covers: H1 (pandoc failures), M1/M2 (upload validation), H10 (sync cache rebuild),
H8 (label commit recovery), H2 (OSError in rename), H11/M4 (admin OSError),
M3 (asset upload OSError), C1 (render before rename).
"""

from __future__ import annotations

import subprocess
import tomllib
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from backend.config import Settings
from backend.main import create_app
from backend.pandoc.renderer import RenderError
from tests.conftest import create_test_client

if TYPE_CHECKING:
    import asyncio
    from collections.abc import AsyncGenerator
    from pathlib import Path


@pytest.fixture
def app_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Create settings for test app."""
    posts_dir = tmp_content_dir / "posts"
    (posts_dir / "hello.md").write_text(
        "---\ncreated_at: 2026-02-02 22:21:29.975359+00\n"
        "author: admin\nlabels: ['#swe']\n---\n# Hello World\n\nTest content.\n"
    )
    (tmp_content_dir / "labels.toml").write_text(
        "[labels]\n[labels.swe]\nnames = ['software engineering']\n"
    )
    # Add about page
    index_toml = tmp_content_dir / "index.toml"
    index_toml.write_text(
        '[site]\ntitle = "Test Blog"\ntimezone = "UTC"\n\n'
        '[[pages]]\nid = "timeline"\ntitle = "Posts"\n\n'
        '[[pages]]\nid = "about"\ntitle = "About"\nfile = "about.md"\n'
    )
    (tmp_content_dir / "about.md").write_text("# About\n\nAbout page.\n")

    db_path = tmp_path / "test.db"
    return Settings(
        secret_key="test-secret-key-with-at-least-32-characters",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        content_dir=tmp_content_dir,
        frontend_dir=tmp_path / "frontend",
        admin_username="admin",
        admin_password="admin123",
        auth_self_registration=True,
        bluesky_client_url="http://test",
    )


@pytest.fixture
async def client(app_settings: Settings) -> AsyncGenerator[AsyncClient]:
    """Create test HTTP client."""
    async with create_test_client(app_settings) as ac:
        yield ac


async def login(client: AsyncClient) -> str:
    """Login as admin and return access token."""
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": "admin", "password": "admin123"},
    )
    return resp.json()["access_token"]


class TestLabelPersistNarrowedExceptions:
    """Labels persistence catches OSError specifically, not bare Exception."""

    @pytest.mark.asyncio
    async def test_label_toml_write_oserror_returns_500(self, client: AsyncClient) -> None:
        token = await login(client)
        with patch(
            "backend.api.labels.write_labels_config",
            side_effect=OSError("disk full"),
        ):
            resp = await client.post(
                "/api/labels",
                json={"id": "test-oserror", "names": ["test"], "parents": []},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_label_toml_write_type_error_propagates(self, client: AsyncClient) -> None:
        """TypeError (programming bug) should NOT be caught by the narrowed handler."""
        token = await login(client)
        with patch(
            "backend.api.labels.write_labels_config",
            side_effect=TypeError("bad argument"),
        ):
            resp = await client.post(
                "/api/labels",
                json={"id": "test-typeerror", "names": ["test"], "parents": []},
                headers={"Authorization": f"Bearer {token}"},
            )
        # Should hit the global TypeError handler (500 "Internal server error")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Internal server error"


class TestRenderEndpointPandocFailure:
    """H1: render endpoint handles pandoc failure."""

    @pytest.mark.asyncio
    async def test_preview_pandoc_failure_returns_502(self, client: AsyncClient) -> None:
        token = await login(client)
        with patch(
            "backend.api.render.render_markdown",
            new_callable=AsyncMock,
            side_effect=RenderError("pandoc not found"),
        ):
            resp = await client.post(
                "/api/render/preview",
                json={"markdown": "# Hello"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 502
        assert "render" in resp.json()["detail"].lower()


class TestPagePandocFailure:
    """Page service propagates RenderError to global handler (502)."""

    @pytest.mark.asyncio
    async def test_page_pandoc_failure_returns_502(self, client: AsyncClient) -> None:
        with patch(
            "backend.services.page_service.render_markdown",
            new_callable=AsyncMock,
            side_effect=RenderError("pandoc broken"),
        ):
            resp = await client.get("/api/pages/about")
        assert resp.status_code == 502
        assert "render" in resp.json()["detail"].lower()


class TestRuntimeErrorHandler:
    """Non-render RuntimeError returns 500 'Internal server error'."""

    @pytest.mark.asyncio
    async def test_non_render_runtime_error_returns_500(self, client: AsyncClient) -> None:
        token = await login(client)
        with patch(
            "backend.api.render.render_markdown",
            new_callable=AsyncMock,
            side_effect=RuntimeError("unexpected internal issue"),
        ):
            resp = await client.post(
                "/api/render/preview",
                json={"markdown": "# Hello"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 500
        assert "internal server error" in resp.json()["detail"].lower()


class TestRenderErrorHandler:
    """RenderError returns 502 via endpoint-level handler."""

    @pytest.mark.asyncio
    async def test_render_error_returns_502(self, client: AsyncClient) -> None:
        token = await login(client)
        with patch(
            "backend.api.render.render_markdown",
            new_callable=AsyncMock,
            side_effect=RenderError("pandoc server down"),
        ):
            resp = await client.post(
                "/api/render/preview",
                json={"markdown": "# Hello"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 502
        assert "render" in resp.json()["detail"].lower()


class TestUploadPostValidation:
    """M1/M2: upload_post validates encoding and YAML."""

    @pytest.mark.asyncio
    async def test_upload_invalid_utf8_returns_422(self, client: AsyncClient) -> None:
        token = await login(client)
        # Invalid UTF-8 bytes
        invalid_bytes = b"\x80\x81\x82\x83"
        resp = await client.post(
            "/api/posts/upload",
            files={"files": ("post.md", invalid_bytes, "text/markdown")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422
        assert "utf-8" in resp.json()["detail"].lower() or "decode" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_upload_invalid_yaml_returns_422(self, client: AsyncClient) -> None:
        token = await login(client)
        # Malformed YAML in front matter
        bad_yaml = "---\ntitle: [\ninvalid yaml\n---\n\nBody text.\n"
        resp = await client.post(
            "/api/posts/upload",
            files={"files": ("post.md", bad_yaml.encode(), "text/markdown")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"].lower()
        assert "front matter" in detail or "yaml" in detail or "parse" in detail


class TestPostCreatePandocFailure:
    """H1: create_post handles pandoc failure."""

    @pytest.mark.asyncio
    async def test_create_post_pandoc_failure_returns_502(self, client: AsyncClient) -> None:
        token = await login(client)
        with patch(
            "backend.api.posts.render_markdown",
            new_callable=AsyncMock,
            side_effect=RenderError("pandoc crashed"),
        ):
            resp = await client.post(
                "/api/posts",
                json={
                    "title": "Test Post",
                    "body": "Hello world",
                    "labels": [],
                    "is_draft": False,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 502
        assert "render" in resp.json()["detail"].lower()


class TestPostUpdatePandocFailure:
    """H1: update_post handles pandoc failure."""

    @pytest.mark.asyncio
    async def test_update_post_pandoc_failure_returns_502(self, client: AsyncClient) -> None:
        token = await login(client)
        with patch(
            "backend.api.posts.render_markdown",
            new_callable=AsyncMock,
            side_effect=RenderError("pandoc crashed"),
        ):
            resp = await client.put(
                "/api/posts/posts/hello.md",
                json={
                    "title": "Updated",
                    "body": "Updated content",
                    "labels": [],
                    "is_draft": False,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 502
        assert "render" in resp.json()["detail"].lower()


class TestUploadPostPandocFailure:
    """H1: upload_post handles pandoc failure."""

    @pytest.mark.asyncio
    async def test_upload_pandoc_failure_returns_502(self, client: AsyncClient) -> None:
        token = await login(client)
        with patch(
            "backend.api.posts.render_markdown",
            new_callable=AsyncMock,
            side_effect=RenderError("pandoc crashed"),
        ):
            md_content = "---\ntitle: Upload Test\n---\n\nContent.\n"
            resp = await client.post(
                "/api/posts/upload",
                files={"files": ("post.md", md_content.encode(), "text/markdown")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 502

    @pytest.mark.asyncio
    async def test_upload_pandoc_failure_cleans_up_assets(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        token = await login(client)
        with patch(
            "backend.api.posts.render_markdown",
            new_callable=AsyncMock,
            side_effect=RenderError("pandoc crashed"),
        ):
            md_content = "---\ntitle: Upload Cleanup Test\n---\n\nContent.\n"
            png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
            resp = await client.post(
                "/api/posts/upload",
                files=[
                    ("files", ("index.md", md_content.encode(), "text/markdown")),
                    ("files", ("photo.png", png_bytes, "image/png")),
                ],
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 502
        # Verify assets were cleaned up -- no directory with photo.png should remain
        posts_dir = app_settings.content_dir / "posts"
        for p in posts_dir.rglob("photo.png"):
            pytest.fail(f"Asset file should have been cleaned up but found: {p}")


class TestUpdatePostRenderBeforeRename:
    """C1: render happens BEFORE rename in title-change path."""

    @pytest.mark.asyncio
    async def test_render_failure_does_not_rename_directory(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        """If rendering fails during title change, the directory must NOT be renamed."""
        token = await login(client)
        # Create a directory-based post first
        md_content = "---\ntitle: Original Title\n---\n\nContent here.\n"
        resp = await client.post(
            "/api/posts/upload",
            files={"files": ("index.md", md_content.encode(), "text/markdown")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        original_path = resp.json()["file_path"]
        original_dir = (app_settings.content_dir / original_path).parent

        # Now update with a different title, but make render fail
        with patch(
            "backend.api.posts.render_markdown",
            new_callable=AsyncMock,
            side_effect=RenderError("pandoc crashed"),
        ):
            resp = await client.put(
                f"/api/posts/{original_path}",
                json={
                    "title": "New Different Title",
                    "body": "Updated content",
                    "labels": [],
                    "is_draft": False,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 502
        # The directory should NOT have been renamed
        assert original_dir.exists(), "Directory was renamed despite render failure"


class TestUpdatePostOSError:
    """H2: update_post handles OSError during shutil.move/os.symlink."""

    @pytest.mark.asyncio
    async def test_move_oserror_returns_500(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        token = await login(client)
        # Create a directory-based post
        md_content = "---\ntitle: Move Test\n---\n\nContent.\n"
        resp = await client.post(
            "/api/posts/upload",
            files={"files": ("index.md", md_content.encode(), "text/markdown")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        original_path = resp.json()["file_path"]

        with patch(
            "backend.api.posts.shutil.move",
            side_effect=OSError("disk full"),
        ):
            resp = await client.put(
                f"/api/posts/{original_path}",
                json={
                    "title": "New Move Title",
                    "body": "Updated content",
                    "labels": [],
                    "is_draft": False,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_symlink_oserror_rolls_back_move(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        token = await login(client)
        # Create a directory-based post
        md_content = "---\ntitle: Symlink Test\n---\n\nContent.\n"
        resp = await client.post(
            "/api/posts/upload",
            files={"files": ("index.md", md_content.encode(), "text/markdown")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        original_path = resp.json()["file_path"]
        original_dir = (app_settings.content_dir / original_path).parent

        with patch(
            "backend.api.posts.os.symlink",
            side_effect=OSError("permission denied"),
        ):
            resp = await client.put(
                f"/api/posts/{original_path}",
                json={
                    "title": "New Symlink Title",
                    "body": "Updated content",
                    "labels": [],
                    "is_draft": False,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        new_path = body["file_path"]
        new_dir = (app_settings.content_dir / new_path).parent
        # Directory rename should still succeed even if backward-compat symlink creation fails.
        assert new_dir.exists()
        assert not original_dir.exists()
        assert "X-Path-Compatibility-Warning" in resp.headers
        assert "warnings" in body
        assert any("symlink" in w.lower() for w in body["warnings"])


class TestAssetUploadOSError:
    """M3: asset upload handles OSError."""

    @pytest.mark.asyncio
    async def test_asset_write_oserror_returns_500(self, client: AsyncClient) -> None:
        token = await login(client)
        # Create a post first
        md_content = "---\ntitle: Asset Error Test\n---\nBody.\n"
        resp = await client.post(
            "/api/posts/upload",
            files={"files": ("index.md", md_content.encode(), "text/markdown")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        file_path = resp.json()["file_path"]

        with patch("pathlib.Path.write_bytes", side_effect=OSError("disk full")):
            resp = await client.post(
                f"/api/posts/{file_path}/assets",
                files={"files": ("photo.png", b"\x89PNG" + b"\x00" * 50, "image/png")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 500


class TestSyncMetadataJsonLeakage:
    """Sync metadata JSON error must not leak parse details."""

    @pytest.mark.asyncio
    async def test_invalid_metadata_returns_generic_message(self, client: AsyncClient) -> None:
        token = await login(client)
        resp = await client.post(
            "/api/sync/commit",
            data={"metadata": "{invalid json here"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail == "Invalid metadata JSON"
        # Must NOT contain json.JSONDecodeError details like line/column numbers
        assert "line" not in detail.lower()
        assert "column" not in detail.lower()
        assert "expecting" not in detail.lower()


class TestSyncCacheRebuildFailure:
    """H10: sync commit handles cache rebuild failure gracefully."""

    @pytest.mark.asyncio
    async def test_sync_commit_cache_failure_returns_warning(self, client: AsyncClient) -> None:
        token = await login(client)

        with patch(
            "backend.services.cache_service.rebuild_cache",
            new_callable=AsyncMock,
            side_effect=RuntimeError("cache rebuild exploded"),
        ):
            resp = await client.post(
                "/api/sync/commit",
                data={"metadata": '{"deleted_files": [], "last_sync_commit": null}'},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert any("cache" in w.lower() for w in data["warnings"])


class TestSyncGitFailure:
    """Sync should degrade gracefully when git commit operations fail."""

    @pytest.mark.asyncio
    async def test_sync_commit_git_timeout_returns_warning(self, client: AsyncClient) -> None:
        token = await login(client)
        timeout = subprocess.TimeoutExpired(cmd=["git", "commit"], timeout=30)
        with patch(
            "backend.api.sync.GitService.commit_all",
            new_callable=AsyncMock,
            side_effect=timeout,
        ):
            resp = await client.post(
                "/api/sync/commit",
                data={"metadata": '{"deleted_files": [], "last_sync_commit": null}'},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert any("git commit failed" in warning.lower() for warning in data["warnings"])

    @pytest.mark.asyncio
    async def test_sync_commit_git_missing_returns_warning(self, client: AsyncClient) -> None:
        token = await login(client)
        with patch(
            "backend.api.sync.GitService.commit_all",
            new_callable=AsyncMock,
            side_effect=FileNotFoundError("git not found"),
        ):
            resp = await client.post(
                "/api/sync/commit",
                data={"metadata": '{"deleted_files": [], "last_sync_commit": null}'},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert any("git commit failed" in warning.lower() for warning in data["warnings"])


class TestSyncConfigReloadFailure:
    """Sync commit handles config reload failure gracefully with a warning."""

    @pytest.mark.asyncio
    async def test_sync_commit_config_reload_oserror_returns_warning(
        self, client: AsyncClient
    ) -> None:
        token = await login(client)

        with patch(
            "backend.api.sync.ContentManager.reload_config",
            side_effect=OSError("permission denied"),
        ):
            resp = await client.post(
                "/api/sync/commit",
                data={"metadata": '{"deleted_files": [], "last_sync_commit": null}'},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert any("config reload failed" in w.lower() for w in data["warnings"])

    @pytest.mark.asyncio
    async def test_sync_commit_config_reload_value_error_returns_warning(
        self, client: AsyncClient
    ) -> None:
        token = await login(client)

        with patch(
            "backend.api.sync.ContentManager.reload_config",
            side_effect=ValueError("bad timezone data"),
        ):
            resp = await client.post(
                "/api/sync/commit",
                data={"metadata": '{"deleted_files": [], "last_sync_commit": null}'},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert any("config reload failed" in w.lower() for w in data["warnings"])


class TestTypeErrorHandler:
    """TypeError is a programming bug and should return 500, not propagate."""

    @pytest.mark.asyncio
    async def test_type_error_returns_500(self, client: AsyncClient) -> None:
        """TypeError should be caught by global handler and return 500."""
        token = await login(client)
        with patch(
            "backend.api.render.render_markdown",
            new_callable=AsyncMock,
            side_effect=TypeError("deliberate test error"),
        ):
            resp = await client.post(
                "/api/render/preview",
                json={"markdown": "# Hello"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Internal server error"


class TestLabelCommitRecovery:
    """H8: label commit failure recovers by restoring TOML."""

    @pytest.mark.asyncio
    async def test_label_create_commit_failure_restores_labels_toml(
        self,
        client: AsyncClient,
        tmp_content_dir: Path,
    ) -> None:
        token = await login(client)
        headers = {"Authorization": f"Bearer {token}"}
        labels_path = tmp_content_dir / "labels.toml"
        original_labels = tomllib.loads(labels_path.read_text())["labels"]
        with patch(
            "backend.api.labels.AsyncSession.commit",
            side_effect=OperationalError(
                "COMMIT",
                {},
                Exception("db commit failed"),
            ),
        ):
            resp = await client.post(
                "/api/labels",
                json={"id": "test-broken", "names": ["test broken"], "parents": []},
                headers=headers,
            )
        assert resp.status_code == 500

        restored_labels = tomllib.loads(labels_path.read_text())["labels"]
        assert restored_labels == original_labels

        missing_resp = await client.get("/api/labels/test-broken")
        assert missing_resp.status_code == 404

        recovery_resp = await client.post(
            "/api/labels",
            json={"id": "restored-ok", "names": ["restored ok"], "parents": []},
            headers=headers,
        )
        assert recovery_resp.status_code == 201

        labels = tomllib.loads(labels_path.read_text())["labels"]
        assert "restored-ok" in labels
        assert "test-broken" not in labels


class TestCrosspostPostNotFound:
    """Crosspost endpoint returns 404 for PostNotFoundError (type-based, not string-based)."""

    @pytest.mark.asyncio
    async def test_crosspost_missing_post_returns_404(self, client: AsyncClient) -> None:
        """When crosspost() raises PostNotFoundError, the API should return 404."""
        token = await login(client)
        from backend.exceptions import PostNotFoundError

        with patch(
            "backend.api.crosspost.crosspost",
            new_callable=AsyncMock,
            side_effect=PostNotFoundError("Post not found: posts/nonexistent.md"),
        ):
            resp = await client.post(
                "/api/crosspost/post",
                json={
                    "post_path": "posts/nonexistent.md",
                    "platforms": ["bluesky"],
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Post not found"

    @pytest.mark.asyncio
    async def test_crosspost_value_error_returns_400(self, client: AsyncClient) -> None:
        """Plain ValueError (not PostNotFoundError) should still return 400."""
        token = await login(client)
        with patch(
            "backend.api.crosspost.crosspost",
            new_callable=AsyncMock,
            side_effect=ValueError("Unknown platform: 'invalid'"),
        ):
            resp = await client.post(
                "/api/crosspost/post",
                json={
                    "post_path": "posts/hello.md",
                    "platforms": ["invalid"],
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 400


class TestConnectionErrorHandler:
    """ConnectionError and TimeoutError return proper HTTP responses, not crash."""

    @pytest.mark.asyncio
    async def test_connection_error_returns_502(self, client: AsyncClient) -> None:
        token = await login(client)
        with patch(
            "backend.api.render.render_markdown",
            new_callable=AsyncMock,
            side_effect=ConnectionError("Connection refused"),
        ):
            resp = await client.post(
                "/api/render/preview",
                json={"markdown": "# Hello"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 502
        assert resp.json()["detail"] == "External service connection failed"

    @pytest.mark.asyncio
    async def test_timeout_error_returns_504(self, client: AsyncClient) -> None:
        token = await login(client)
        with patch(
            "backend.api.render.render_markdown",
            new_callable=AsyncMock,
            side_effect=TimeoutError("timed out"),
        ):
            resp = await client.post(
                "/api/render/preview",
                json={"markdown": "# Hello"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 504
        assert resp.json()["detail"] == "Operation timed out"


class TestAdminOSError:
    """H11/M4: admin endpoints handle OSError."""

    @pytest.mark.asyncio
    async def test_update_settings_oserror_returns_500(self, client: AsyncClient) -> None:
        token = await login(client)
        with patch(
            "backend.api.admin.update_site_settings",
            side_effect=OSError("disk full"),
        ):
            resp = await client.put(
                "/api/admin/site",
                json={
                    "title": "New Title",
                    "description": "desc",
                    "timezone": "UTC",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_create_page_oserror_returns_500(self, client: AsyncClient) -> None:
        token = await login(client)
        with patch(
            "backend.api.admin.create_page",
            side_effect=OSError("disk full"),
        ):
            resp = await client.post(
                "/api/admin/pages",
                json={"id": "contact", "title": "Contact"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_update_page_oserror_returns_500(self, client: AsyncClient) -> None:
        token = await login(client)
        with patch(
            "backend.api.admin.update_page",
            side_effect=OSError("disk full"),
        ):
            resp = await client.put(
                "/api/admin/pages/about",
                json={"title": "About Us", "content": "# About\n\nUpdated."},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_delete_page_oserror_returns_500(self, client: AsyncClient) -> None:
        token = await login(client)
        with patch(
            "backend.api.admin.delete_page",
            side_effect=OSError("disk full"),
        ):
            resp = await client.delete(
                "/api/admin/pages/about",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_update_page_order_oserror_returns_500(self, client: AsyncClient) -> None:
        token = await login(client)
        with patch(
            "backend.api.admin.update_page_order",
            side_effect=OSError("disk full"),
        ):
            resp = await client.put(
                "/api/admin/pages/order",
                json={
                    "pages": [
                        {"id": "timeline", "title": "Posts", "file": None},
                        {"id": "about", "title": "About", "file": "about.md"},
                    ]
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 500


class TestDeleteBuiltinPageError:
    """Delete built-in page returns 400 with BuiltinPageError."""

    @pytest.mark.asyncio
    async def test_delete_builtin_page_returns_400(self, client: AsyncClient) -> None:
        token = await login(client)
        resp = await client.delete(
            "/api/admin/pages/timeline",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "built-in" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_page_returns_404(self, client: AsyncClient) -> None:
        token = await login(client)
        resp = await client.delete(
            "/api/admin/pages/nonexistent",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404


class TestPostWriteNarrowedExceptions:
    """Post write catches OSError specifically, not bare Exception."""

    @pytest.mark.asyncio
    async def test_create_post_write_oserror_returns_500(self, client: AsyncClient) -> None:
        token = await login(client)
        with patch(
            "backend.api.posts.ContentManager.write_post",
            side_effect=OSError("disk full"),
        ):
            resp = await client.post(
                "/api/posts",
                json={
                    "title": "Test Narrowed",
                    "body": "Content",
                    "labels": [],
                    "is_draft": False,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to write post file"

    @pytest.mark.asyncio
    async def test_create_post_type_error_propagates(self, client: AsyncClient) -> None:
        """TypeError should NOT be caught locally -- goes to global handler."""
        token = await login(client)
        with patch(
            "backend.api.posts.ContentManager.write_post",
            side_effect=TypeError("bad type"),
        ):
            resp = await client.post(
                "/api/posts",
                json={
                    "title": "Test TypeError",
                    "body": "Content",
                    "labels": [],
                    "is_draft": False,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Internal server error"

    @pytest.mark.asyncio
    async def test_update_post_write_oserror_returns_500(self, client: AsyncClient) -> None:
        token = await login(client)
        with patch(
            "backend.api.posts.ContentManager.write_post",
            side_effect=OSError("disk full"),
        ):
            resp = await client.put(
                "/api/posts/posts/hello.md",
                json={
                    "title": "Updated",
                    "body": "Updated content",
                    "labels": [],
                    "is_draft": False,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to write post file"

    @pytest.mark.asyncio
    async def test_update_post_type_error_propagates(self, client: AsyncClient) -> None:
        """TypeError should NOT be caught locally -- goes to global handler."""
        token = await login(client)
        with patch(
            "backend.api.posts.ContentManager.write_post",
            side_effect=TypeError("bad type"),
        ):
            resp = await client.put(
                "/api/posts/posts/hello.md",
                json={
                    "title": "Updated",
                    "body": "Updated content",
                    "labels": [],
                    "is_draft": False,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Internal server error"

    @pytest.mark.asyncio
    async def test_upload_post_write_oserror_returns_500(self, client: AsyncClient) -> None:
        token = await login(client)
        md_content = "---\ntitle: Upload OSError Test\n---\n\nContent.\n"
        with patch(
            "backend.api.posts.ContentManager.write_post",
            side_effect=OSError("disk full"),
        ):
            resp = await client.post(
                "/api/posts/upload",
                files={"files": ("index.md", md_content.encode(), "text/markdown")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to write post file"

    @pytest.mark.asyncio
    async def test_upload_post_type_error_propagates(self, client: AsyncClient) -> None:
        """TypeError should NOT be caught locally -- goes to global handler."""
        token = await login(client)
        md_content = "---\ntitle: Upload TypeError Test\n---\n\nContent.\n"
        with patch(
            "backend.api.posts.ContentManager.write_post",
            side_effect=TypeError("bad type"),
        ):
            resp = await client.post(
                "/api/posts/upload",
                files={"files": ("index.md", md_content.encode(), "text/markdown")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Internal server error"


class TestExternalServiceErrorHandler:
    """ExternalServiceError returns 502 with generic message."""

    @pytest.mark.asyncio
    async def test_external_service_error_returns_502(self, client: AsyncClient) -> None:
        from backend.exceptions import ExternalServiceError

        token = await login(client)
        with patch(
            "backend.api.render.render_markdown",
            new_callable=AsyncMock,
            side_effect=ExternalServiceError("secret internal details"),
        ):
            resp = await client.post(
                "/api/render/preview",
                json={"markdown": "# Hello"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 502
        detail = resp.json()["detail"]
        assert detail == "External service error"
        assert "secret" not in detail


class TestOAuthErrorLeakage:
    """OAuth errors must not leak internal details to clients."""

    @pytest.mark.asyncio
    async def test_bluesky_authorize_error_is_generic(self, client: AsyncClient) -> None:
        """Bluesky authorize ATProtoOAuthError must not leak PDS details."""
        from backend.crosspost.atproto_oauth import ATProtoOAuthError

        token = await login(client)
        with patch(
            "backend.crosspost.atproto_oauth.resolve_handle_to_did",
            new_callable=AsyncMock,
            side_effect=ATProtoOAuthError(
                "Internal: PDS at https://secret-pds.internal:8443 returned 500"
            ),
        ):
            resp = await client.post(
                "/api/crosspost/bluesky/authorize",
                json={"handle": "test.bsky.social"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 502
        detail = resp.json()["detail"]
        assert detail == "Bluesky authentication failed"
        assert "secret-pds" not in detail
        assert "8443" not in detail

    @pytest.mark.asyncio
    async def test_bluesky_callback_token_error_is_generic(self, client: AsyncClient) -> None:
        """Bluesky callback ATProtoOAuthError must not leak token exchange details."""
        from backend.crosspost.atproto_oauth import ATProtoOAuthError

        # The callback requires valid state in the store; we mock exchange_code_for_tokens
        with (
            patch(
                "backend.crosspost.atproto_oauth.exchange_code_for_tokens",
                new_callable=AsyncMock,
                side_effect=ATProtoOAuthError(
                    "Token endpoint https://auth.secret-server.com:9443/token returned 401"
                ),
            ),
            patch(
                "backend.crosspost.bluesky_oauth_state.OAuthStateStore.pop",
                return_value={
                    "pkce_verifier": "test",
                    "dpop_nonce": "test",
                    "user_id": 1,
                    "did": "did:plc:test",
                    "handle": "test.bsky.social",
                    "auth_server_meta": {
                        "issuer": "https://bsky.social",
                        "token_endpoint": "https://bsky.social/oauth/token",
                        "pds_url": "https://pds.bsky.social",
                    },
                },
            ),
        ):
            resp = await client.get(
                "/api/crosspost/bluesky/callback",
                params={"code": "test-code", "state": "test-state"},
            )
        assert resp.status_code == 502
        detail = resp.json()["detail"]
        assert detail == "Bluesky token exchange failed"
        assert "secret-server" not in detail

    @pytest.mark.asyncio
    async def test_mastodon_authorize_http_error_is_generic(self, client: AsyncClient) -> None:
        """Mastodon authorize httpx.HTTPError must not leak connection details."""
        import httpx

        token = await login(client)
        with patch(
            "backend.crosspost.ssrf.ssrf_safe_client",
        ) as mock_client_ctx:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(
                side_effect=httpx.ConnectError(
                    "Connection refused: https://mastodon.secret-internal.corp:3000"
                )
            )
            mock_client_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_client_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            resp = await client.post(
                "/api/crosspost/mastodon/authorize",
                json={"instance_url": "https://mastodon.social"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 502
        detail = resp.json()["detail"]
        assert detail == "Could not connect to Mastodon instance"
        assert "secret-internal" not in detail

    @pytest.mark.asyncio
    async def test_mastodon_callback_token_error_is_generic(self, client: AsyncClient) -> None:
        """Mastodon callback MastodonOAuthTokenError must not leak details."""
        from backend.crosspost.mastodon import MastodonOAuthTokenError

        with (
            patch(
                "backend.crosspost.mastodon.exchange_mastodon_oauth_token",
                new_callable=AsyncMock,
                side_effect=MastodonOAuthTokenError(
                    "Token error from https://mastodon.secret.internal:4430/oauth/token"
                ),
            ),
            patch(
                "backend.crosspost.bluesky_oauth_state.OAuthStateStore.pop",
                return_value={
                    "instance_url": "https://mastodon.social",
                    "client_id": "test-client-id",
                    "client_secret": "test-client-secret",
                    "pkce_verifier": "test-verifier",
                    "user_id": 1,
                    "redirect_uri": "http://test/api/crosspost/mastodon/callback",
                },
            ),
        ):
            resp = await client.get(
                "/api/crosspost/mastodon/callback",
                params={"code": "test-code", "state": "test-state"},
            )
        assert resp.status_code == 502
        detail = resp.json()["detail"]
        assert detail == "Mastodon token exchange failed"
        assert "secret" not in detail.lower()

    @pytest.mark.asyncio
    async def test_mastodon_callback_http_error_is_generic(self, client: AsyncClient) -> None:
        """Mastodon callback httpx.HTTPError must not leak details."""
        import httpx

        with (
            patch(
                "backend.crosspost.mastodon.exchange_mastodon_oauth_token",
                new_callable=AsyncMock,
                side_effect=httpx.ConnectError(
                    "Connection refused: https://mastodon.secret.corp:443"
                ),
            ),
            patch(
                "backend.crosspost.bluesky_oauth_state.OAuthStateStore.pop",
                return_value={
                    "instance_url": "https://mastodon.social",
                    "client_id": "test-client-id",
                    "client_secret": "test-client-secret",
                    "pkce_verifier": "test-verifier",
                    "user_id": 1,
                    "redirect_uri": "http://test/api/crosspost/mastodon/callback",
                },
            ),
        ):
            resp = await client.get(
                "/api/crosspost/mastodon/callback",
                params={"code": "test-code", "state": "test-state"},
            )
        assert resp.status_code == 502
        detail = resp.json()["detail"]
        assert detail == "Mastodon authentication failed"
        assert "secret" not in detail.lower()

    @pytest.mark.asyncio
    async def test_x_callback_token_error_is_generic(self, client: AsyncClient) -> None:
        """X callback XOAuthTokenError must not leak details."""
        from backend.crosspost.x import XOAuthTokenError

        with (
            patch(
                "backend.crosspost.x.exchange_x_oauth_token",
                new_callable=AsyncMock,
                side_effect=XOAuthTokenError(
                    "Token error: https://api.x.com/oauth2/token returned "
                    "invalid_grant for client_id=secret_client_123"
                ),
            ),
            patch(
                "backend.crosspost.bluesky_oauth_state.OAuthStateStore.pop",
                return_value={
                    "pkce_verifier": "test-verifier",
                    "user_id": 1,
                    "redirect_uri": "http://test/api/crosspost/x/callback",
                    "client_id": "test-client-id",
                    "client_secret": "test-client-secret",
                },
            ),
        ):
            resp = await client.get(
                "/api/crosspost/x/callback",
                params={"code": "test-code", "state": "test-state"},
            )
        assert resp.status_code == 502
        detail = resp.json()["detail"]
        assert detail == "X token exchange failed"
        assert "secret_client" not in detail

    @pytest.mark.asyncio
    async def test_x_callback_http_error_is_generic(self, client: AsyncClient) -> None:
        """X callback httpx.HTTPError must not leak details."""
        import httpx

        with (
            patch(
                "backend.crosspost.x.exchange_x_oauth_token",
                new_callable=AsyncMock,
                side_effect=httpx.ConnectError(
                    "Connection refused: https://api.x-internal.corp:8443"
                ),
            ),
            patch(
                "backend.crosspost.bluesky_oauth_state.OAuthStateStore.pop",
                return_value={
                    "pkce_verifier": "test-verifier",
                    "user_id": 1,
                    "redirect_uri": "http://test/api/crosspost/x/callback",
                    "client_id": "test-client-id",
                    "client_secret": "test-client-secret",
                },
            ),
        ):
            resp = await client.get(
                "/api/crosspost/x/callback",
                params={"code": "test-code", "state": "test-state"},
            )
        assert resp.status_code == 502
        detail = resp.json()["detail"]
        assert detail == "X authentication failed"
        assert "x-internal" not in detail

    @pytest.mark.asyncio
    async def test_facebook_callback_token_error_is_generic(self, client: AsyncClient) -> None:
        """Facebook callback FacebookOAuthTokenError must not leak details."""
        from backend.crosspost.facebook import FacebookOAuthTokenError

        with (
            patch(
                "backend.crosspost.facebook.exchange_facebook_oauth_token",
                new_callable=AsyncMock,
                side_effect=FacebookOAuthTokenError(
                    "Token error: app_secret=s3cr3t_app_key_12345 was rejected"
                ),
            ),
            patch(
                "backend.crosspost.bluesky_oauth_state.OAuthStateStore.pop",
                return_value={
                    "user_id": 1,
                    "redirect_uri": "http://test/api/crosspost/facebook/callback",
                    "app_id": "test-app-id",
                    "app_secret": "test-app-secret",
                },
            ),
        ):
            resp = await client.get(
                "/api/crosspost/facebook/callback",
                params={"code": "test-code", "state": "test-state"},
            )
        assert resp.status_code == 502
        detail = resp.json()["detail"]
        assert detail == "Facebook token exchange failed"
        assert "s3cr3t" not in detail

    @pytest.mark.asyncio
    async def test_facebook_callback_http_error_is_generic(self, client: AsyncClient) -> None:
        """Facebook callback httpx.HTTPError must not leak details."""
        import httpx

        with (
            patch(
                "backend.crosspost.facebook.exchange_facebook_oauth_token",
                new_callable=AsyncMock,
                side_effect=httpx.ConnectError(
                    "Connection refused: https://graph.facebook.internal:8443"
                ),
            ),
            patch(
                "backend.crosspost.bluesky_oauth_state.OAuthStateStore.pop",
                return_value={
                    "user_id": 1,
                    "redirect_uri": "http://test/api/crosspost/facebook/callback",
                    "app_id": "test-app-id",
                    "app_secret": "test-app-secret",
                },
            ),
        ):
            resp = await client.get(
                "/api/crosspost/facebook/callback",
                params={"code": "test-code", "state": "test-state"},
            )
        assert resp.status_code == 502
        detail = resp.json()["detail"]
        assert detail == "Facebook authentication failed"
        assert "facebook.internal" not in detail

    @pytest.mark.asyncio
    async def test_facebook_callback_multipage_store_full_returns_503(
        self, client: AsyncClient
    ) -> None:
        """Multi-page facebook callback must not crash if state store is full."""
        two_pages = [
            {"access_token": "tok1", "id": "111", "name": "Page One"},
            {"access_token": "tok2", "id": "222", "name": "Page Two"},
        ]
        with (
            patch(
                "backend.crosspost.facebook.exchange_facebook_oauth_token",
                new_callable=AsyncMock,
                return_value={"pages": two_pages},
            ),
            patch(
                "backend.crosspost.bluesky_oauth_state.OAuthStateStore.pop",
                return_value={
                    "user_id": 1,
                    "redirect_uri": "http://test/api/crosspost/facebook/callback",
                    "app_id": "test-app-id",
                    "app_secret": "test-app-secret",
                },
            ),
            patch(
                "backend.crosspost.bluesky_oauth_state.OAuthStateStore.set",
                side_effect=ValueError("OAuth state store is full"),
            ),
        ):
            resp = await client.get(
                "/api/crosspost/facebook/callback",
                params={"code": "test-code", "state": "test-state"},
                follow_redirects=False,
            )
        assert resp.status_code == 503
        assert "temporarily unavailable" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_facebook_callback_multipage_user_limit_returns_429(
        self, client: AsyncClient
    ) -> None:
        """Multi-page facebook callback must return 429 on per-user limit."""
        from backend.crosspost.bluesky_oauth_state import OAuthUserLimitError

        two_pages = [
            {"access_token": "tok1", "id": "111", "name": "Page One"},
            {"access_token": "tok2", "id": "222", "name": "Page Two"},
        ]
        with (
            patch(
                "backend.crosspost.facebook.exchange_facebook_oauth_token",
                new_callable=AsyncMock,
                return_value={"pages": two_pages},
            ),
            patch(
                "backend.crosspost.bluesky_oauth_state.OAuthStateStore.pop",
                return_value={
                    "user_id": 1,
                    "redirect_uri": "http://test/api/crosspost/facebook/callback",
                    "app_id": "test-app-id",
                    "app_secret": "test-app-secret",
                },
            ),
            patch(
                "backend.crosspost.bluesky_oauth_state.OAuthStateStore.set",
                side_effect=OAuthUserLimitError("Too many pending OAuth flows for this user"),
            ),
        ):
            resp = await client.get(
                "/api/crosspost/facebook/callback",
                params={"code": "test-code", "state": "test-state"},
                follow_redirects=False,
            )
        assert resp.status_code == 429
        assert "Too many pending OAuth flows" in resp.json()["detail"]


class TestDeletePostOSError:
    """Delete post endpoint handles OSError from filesystem operations."""

    @pytest.mark.asyncio
    async def test_delete_post_oserror_returns_500(self, client: AsyncClient) -> None:
        """When content_manager.delete_post raises OSError, return 500."""
        token = await login(client)
        headers = {"Authorization": f"Bearer {token}"}

        # Create a post to delete
        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Delete OSError Test",
                "body": "Content for delete error test.\n",
                "labels": [],
                "is_draft": False,
            },
            headers=headers,
        )
        assert create_resp.status_code == 201
        file_path = create_resp.json()["file_path"]

        # Mock delete_post to raise OSError
        with patch(
            "backend.api.posts.ContentManager.delete_post",
            side_effect=OSError("permission denied"),
        ):
            resp = await client.delete(
                f"/api/posts/{file_path}",
                headers=headers,
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to delete post file"


class TestGetSettings503:
    """get_settings should return 503 when settings is missing, like other deps."""

    @pytest.mark.asyncio
    async def test_get_settings_returns_503_when_missing(self) -> None:
        from fastapi import Depends, FastAPI

        from backend.api.deps import get_settings

        app = FastAPI()

        _settings_dep = Depends(get_settings)

        @app.get("/test-settings")
        async def _endpoint(s: Settings = _settings_dep) -> dict[str, bool]:
            return {"ok": True}

        # Don't set app.state.settings
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/test-settings")
        assert resp.status_code == 503


class TestMissingContentWriteLock:
    """Endpoints should return 503 when content_write_lock is not set."""

    @pytest.mark.asyncio
    async def test_endpoint_returns_503_without_lock(self) -> None:
        from fastapi import Depends, FastAPI

        from backend.api.deps import get_content_write_lock

        app = FastAPI()

        _lock_dep = Depends(get_content_write_lock)

        @app.get("/test-lock")
        async def _endpoint(lock: asyncio.Lock = _lock_dep) -> dict[str, bool]:
            return {"ok": True}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/test-lock")
        assert resp.status_code == 503


class TestMissingServiceDependencies:
    """Endpoints return 503 when required services are missing from app state."""

    @pytest.mark.asyncio
    async def test_missing_session_factory_returns_503(self, tmp_path: Path) -> None:
        """When session_factory is not on app.state, endpoints return 503."""
        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            frontend_dir=tmp_path / "no-frontend",
        )
        app = create_app(settings)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/health")
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_missing_content_manager_returns_503(self, tmp_path: Path) -> None:
        """When content_manager is not on app.state, endpoints return 503."""
        from sqlalchemy import text

        from backend.database import create_engine as create_db_engine
        from backend.models.base import Base

        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db",
            frontend_dir=tmp_path / "no-frontend",
        )
        app = create_app(settings)

        engine, session_factory = create_db_engine(settings)
        app.state.engine = engine
        app.state.session_factory = session_factory

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            await session.execute(
                text(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5("
                    "title, content, content='posts_cache', content_rowid='id')"
                )
            )
            await session.commit()

        from backend.services.auth_service import ensure_admin_user

        async with session_factory() as session:
            await ensure_admin_user(session, settings)

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                token_resp = await client.post(
                    "/api/auth/token-login",
                    json={"username": "admin", "password": "testpassword"},
                )
                assert token_resp.status_code == 200
                token = token_resp.json()["access_token"]

                resp = await client.get(
                    "/api/admin/site",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 503
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_missing_git_service_returns_503(self, tmp_path: Path) -> None:
        """When git_service is not on app.state, endpoints return 503."""
        from sqlalchemy import text

        from backend.database import create_engine as create_db_engine
        from backend.models.base import Base

        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db",
            content_dir=tmp_path / "content",
            frontend_dir=tmp_path / "no-frontend",
        )
        app = create_app(settings)

        engine, session_factory = create_db_engine(settings)
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.content_write_lock = __import__("asyncio").Lock()

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            await session.execute(
                text(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5("
                    "title, content, content='posts_cache', content_rowid='id')"
                )
            )
            await session.commit()

        from backend.filesystem.content_manager import ContentManager
        from backend.main import ensure_content_dir
        from backend.services.auth_service import ensure_admin_user

        ensure_content_dir(settings.content_dir)
        app.state.content_manager = ContentManager(content_dir=settings.content_dir)

        async with session_factory() as session:
            await ensure_admin_user(session, settings)

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                token_resp = await client.post(
                    "/api/auth/token-login",
                    json={"username": "admin", "password": "testpassword"},
                )
                assert token_resp.status_code == 200
                token = token_resp.json()["access_token"]

                resp = await client.post(
                    "/api/sync/status",
                    json={"client_manifest": []},
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 503
        finally:
            await engine.dispose()


class TestSyncStatusHeadCommitFailure:
    """sync_status returns server_commit=null when git head_commit fails."""

    @pytest.mark.asyncio
    async def test_sync_status_returns_null_server_commit_on_git_failure(
        self, client: AsyncClient
    ) -> None:
        token = await login(client)
        headers = {"Authorization": f"Bearer {token}"}

        with patch(
            "backend.api.sync.GitService.head_commit",
            new_callable=AsyncMock,
            side_effect=subprocess.CalledProcessError(128, "git rev-parse"),
        ):
            resp = await client.post(
                "/api/sync/status",
                json={"client_manifest": []},
                headers=headers,
            )
        assert resp.status_code == 200
        assert resp.json()["server_commit"] is None
