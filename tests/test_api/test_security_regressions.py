"""Regression tests for high-impact security issues."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backend.config import Settings
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient


@pytest.fixture
def app_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Create application settings for security regression tests."""
    posts_dir = tmp_content_dir / "posts"
    hello_post = posts_dir / "hello"
    hello_post.mkdir()
    (hello_post / "index.md").write_text(
        "---\n"
        "title: Hello World\n"
        "created_at: 2026-02-02 22:21:29.975359+00\n"
        "modified_at: 2026-02-02 22:21:29.975359+00\n"
        "author: admin\n"
        "labels: ['#swe']\n"
        "---\n"
        "Hello from fixture.\n",
        encoding="utf-8",
    )
    admin_draft = posts_dir / "admin-draft"
    admin_draft.mkdir()
    (admin_draft / "index.md").write_text(
        "---\n"
        "title: Admin Draft\n"
        "created_at: 2026-02-02 22:21:29.975359+00\n"
        "modified_at: 2026-02-02 22:21:29.975359+00\n"
        "author: admin\n"
        "labels: []\n"
        "draft: true\n"
        "---\n"
        "Top secret draft.\n",
        encoding="utf-8",
    )
    (tmp_content_dir / "labels.toml").write_text(
        "[labels]\n[labels.swe]\nnames = ['software engineering']\n",
        encoding="utf-8",
    )
    (tmp_content_dir / "about.md").write_text(
        "# About\n\nThis is the about page.\n",
        encoding="utf-8",
    )
    (tmp_content_dir / "index.toml").write_text(
        "[site]\n"
        'title = "Test Blog"\n'
        'timezone = "UTC"\n\n'
        "[[pages]]\n"
        'id = "timeline"\n'
        'title = "Posts"\n\n'
        "[[pages]]\n"
        'id = "about"\n'
        'title = "About"\n'
        'file = "about.md"\n',
        encoding="utf-8",
    )
    db_path = tmp_path / "test.db"
    return Settings(
        secret_key="test-secret-key-very-long-for-security",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        content_dir=tmp_content_dir,
        frontend_dir=tmp_path / "frontend",
        admin_username="admin",
        admin_password="admin123",
        auth_self_registration=True,
        auth_login_max_failures=2,
        auth_rate_limit_window_seconds=300,
    )


@pytest.fixture
async def client(app_settings: Settings) -> AsyncGenerator[AsyncClient]:
    """Create test HTTP client with initialized app state."""
    async with create_test_client(app_settings) as ac:
        yield ac


async def _login(client: AsyncClient, username: str, password: str) -> str:
    """Login helper returning the access token."""
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


async def _register(client: AsyncClient, username: str, email: str, password: str) -> None:
    """Register a non-admin user."""
    resp = await client.post(
        "/api/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    assert resp.status_code == 201
    assert resp.json()["is_admin"] is False


class TestSyncAuthorizationBoundary:
    @pytest.mark.asyncio
    async def test_non_admin_cannot_initialize_sync(self, client: AsyncClient) -> None:
        await _register(client, "writer", "writer@test.com", "writer-password")
        token = await _login(client, "writer", "writer-password")

        resp = await client.post(
            "/api/sync/status",
            json={"client_manifest": []},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_cannot_download_hidden_sync_secret_file(self, client: AsyncClient) -> None:
        token = await _login(client, "admin", "admin123")

        resp = await client.get(
            "/api/sync/download/.atproto-oauth-key.json",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_cannot_overwrite_hidden_sync_secret_file(
        self, client: AsyncClient
    ) -> None:
        token = await _login(client, "admin", "admin123")

        resp = await client.post(
            "/api/sync/commit",
            data={"metadata": '{"deleted_files": [], "last_sync_commit": null}'},
            files={
                "files": (
                    ".atproto-oauth-key.json",
                    b'{"private_key_pem":"attacker","jwk":{"kid":"evil"}}',
                    "application/json",
                )
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 403


class TestRenderedHtmlSanitization:
    @pytest.mark.asyncio
    async def test_render_preview_strips_script_and_javascript_links(
        self,
        client: AsyncClient,
    ) -> None:
        token = await _login(client, "admin", "admin123")
        resp = await client.post(
            "/api/render/preview",
            json={
                "markdown": (
                    "[click](javascript:alert('xss'))\n\n"
                    "<script>alert('owned')</script>\n\n"
                    "safe text"
                )
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        html = resp.json()["html"].lower()
        assert "<script" not in html
        assert 'href="javascript:' not in html


class TestRenderPreviewAuthorization:
    @pytest.mark.asyncio
    async def test_render_preview_rejects_non_admin_users(self, client: AsyncClient) -> None:
        await _register(client, "writer", "writer@test.com", "writer-password")
        token = await _login(client, "writer", "writer-password")

        resp = await client.post(
            "/api/render/preview",
            json={"markdown": "# Private preview"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 403


class TestDraftVisibility:
    @pytest.mark.asyncio
    async def test_draft_post_not_publicly_readable(self, client: AsyncClient) -> None:
        token = await _login(client, "admin", "admin123")
        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Private Draft",
                "body": "Top secret.",
                "labels": [],
                "is_draft": True,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert create_resp.status_code == 201
        file_path = create_resp.json()["file_path"]

        client.cookies.clear()
        unauth_resp = await client.get(f"/api/posts/{file_path}")
        assert unauth_resp.status_code == 404

        auth_resp = await client.get(
            f"/api/posts/{file_path}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert auth_resp.status_code == 200
        assert auth_resp.json()["is_draft"] is True


class TestCrosspostHistoryIsolation:
    @pytest.mark.asyncio
    async def test_crosspost_history_isolated_per_user(self, client: AsyncClient) -> None:
        admin_token = await _login(client, "admin", "admin123")
        trigger_resp = await client.post(
            "/api/crosspost/post",
            json={"post_path": "posts/hello/index.md", "platforms": ["bluesky"]},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert trigger_resp.status_code == 200
        assert trigger_resp.json()[0]["status"] == "failed"

        client.cookies.clear()
        await _register(client, "reader", "reader@test.com", "reader-password")
        reader_token = await _login(client, "reader", "reader-password")
        history_resp = await client.get(
            "/api/crosspost/history/posts/hello/index.md",
            headers={"Authorization": f"Bearer {reader_token}"},
        )
        assert history_resp.status_code == 200
        assert history_resp.json()["items"] == []


class TestDraftContentVisibility:
    @pytest.mark.asyncio
    async def test_draft_markdown_returns_404_for_unauthenticated(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get("/api/content/posts/admin-draft/index.md")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_draft_markdown_returns_404_for_wrong_user(self, client: AsyncClient) -> None:
        await _register(client, "reader2", "reader2@test.com", "reader2-password")
        reader_token = await _login(client, "reader2", "reader2-password")
        resp = await client.get(
            "/api/content/posts/admin-draft/index.md",
            headers={"Authorization": f"Bearer {reader_token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_draft_markdown_returns_200_for_author(self, client: AsyncClient) -> None:
        admin_token = await _login(client, "admin", "admin123")
        resp = await client.get(
            "/api/content/posts/admin-draft/index.md",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert b"Top secret draft" in resp.content


class TestCrosspostDraftIsolation:
    @pytest.mark.asyncio
    async def test_non_author_cannot_crosspost_another_users_draft(
        self, client: AsyncClient
    ) -> None:
        await _register(client, "reader3", "reader3@test.com", "reader3-password")
        reader_token = await _login(client, "reader3", "reader3-password")
        resp = await client.post(
            "/api/crosspost/post",
            json={"post_path": "posts/admin-draft/index.md", "platforms": ["bluesky"]},
            headers={"Authorization": f"Bearer {reader_token}"},
        )
        assert resp.status_code == 404


class TestDraftDisplayNameImpersonation:
    @pytest.mark.asyncio
    async def test_matching_authors_display_name_does_not_grant_draft_access(
        self, client: AsyncClient
    ) -> None:
        register_resp = await client.post(
            "/api/auth/register",
            json={
                "username": "imposter",
                "email": "imposter@test.com",
                "password": "imposter-password",
                "display_name": "Admin",
            },
        )
        assert register_resp.status_code == 201

        imposter_token = await _login(client, "imposter", "imposter-password")
        headers = {"Authorization": f"Bearer {imposter_token}"}

        listing_resp = await client.get("/api/posts", headers=headers)
        assert listing_resp.status_code == 200
        titles = [post["title"] for post in listing_resp.json()["posts"]]
        assert "Admin Draft" not in titles

        detail_resp = await client.get("/api/posts/posts/admin-draft/index.md", headers=headers)
        assert detail_resp.status_code == 404

        content_resp = await client.get("/api/content/posts/admin-draft/index.md", headers=headers)
        assert content_resp.status_code == 404

        crosspost_resp = await client.post(
            "/api/crosspost/post",
            json={"post_path": "posts/admin-draft/index.md", "platforms": ["bluesky"]},
            headers=headers,
        )
        assert crosspost_resp.status_code == 404


class TestPostMutationAuthorization:
    @pytest.mark.asyncio
    async def test_non_admin_cannot_create_update_delete_posts(self, client: AsyncClient) -> None:
        await _register(client, "writer2", "writer2@test.com", "writer2-password")
        token = await _login(client, "writer2", "writer2-password")
        headers = {"Authorization": f"Bearer {token}"}

        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Non-admin Create",
                "body": "nope",
                "labels": [],
                "is_draft": False,
            },
            headers=headers,
        )
        assert create_resp.status_code == 403

        update_resp = await client.put(
            "/api/posts/posts/hello/index.md",
            json={
                "title": "Updated",
                "body": "changed",
                "labels": [],
                "is_draft": False,
            },
            headers=headers,
        )
        assert update_resp.status_code == 403

        delete_resp = await client.delete("/api/posts/posts/hello/index.md", headers=headers)
        assert delete_resp.status_code == 403

    @pytest.mark.asyncio
    async def test_non_admin_cannot_mutate_labels(self, client: AsyncClient) -> None:
        await _register(client, "writer4", "writer4@test.com", "writer4-password")
        token_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "writer4", "password": "writer4-password"},
        )
        token = token_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        create_resp = await client.post(
            "/api/labels",
            json={"id": "locked-down", "names": ["Locked Down"]},
            headers=headers,
        )
        assert create_resp.status_code == 403

    @pytest.mark.asyncio
    async def test_non_admin_cannot_upload_posts_or_assets_or_edit_payload(
        self, client: AsyncClient
    ) -> None:
        await _register(client, "writer3", "writer3@test.com", "writer3-password")
        token = await _login(client, "writer3", "writer3-password")
        headers = {"Authorization": f"Bearer {token}"}

        upload_resp = await client.post(
            "/api/posts/upload",
            files={"files": ("test.md", b"---\ntitle: Upload\n---\nbody", "text/markdown")},
            headers=headers,
        )
        assert upload_resp.status_code == 403

        assets_resp = await client.post(
            "/api/posts/posts/hello/index.md/assets",
            files={"files": ("a.txt", b"x", "text/plain")},
            headers=headers,
        )
        assert assets_resp.status_code == 403

        edit_resp = await client.get("/api/posts/posts/hello/index.md/edit", headers=headers)
        assert edit_resp.status_code == 403


class TestRegistrationPasswordPolicy:
    @pytest.mark.asyncio
    async def test_registration_rejects_password_shorter_than_8(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/auth/register",
            json={
                "username": "weakpw",
                "email": "weakpw@test.com",
                "password": "short7x",
            },
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_registration_accepts_password_of_length_8(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/auth/register",
            json={
                "username": "strongpw",
                "email": "strongpw@test.com",
                "password": "exactly8",
            },
        )
        assert resp.status_code == 201


class TestAdminPasswordPolicy:
    @pytest.mark.asyncio
    async def test_admin_password_change_rejects_password_shorter_than_8(
        self, client: AsyncClient
    ) -> None:
        token_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = token_resp.json()["access_token"]

        resp = await client.put(
            "/api/admin/password",
            json={
                "current_password": "admin123",
                "new_password": "short7x",
                "confirm_password": "short7x",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_admin_password_change_accepts_password_of_length_8(
        self, client: AsyncClient
    ) -> None:
        token_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        token = token_resp.json()["access_token"]

        resp = await client.put(
            "/api/admin/password",
            json={
                "current_password": "admin123",
                "new_password": "exactly8",
                "confirm_password": "exactly8",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200


class TestPageTraversalGuard:
    @pytest.mark.asyncio
    async def test_page_file_path_cannot_escape_content_dir(self, tmp_path: Path) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "posts").mkdir()
        (content_dir / "labels.toml").write_text("[labels]\n", encoding="utf-8")
        (tmp_path / "secret.md").write_text("# Secret\n\nsensitive", encoding="utf-8")
        (content_dir / "index.toml").write_text(
            "[site]\n"
            'title = "Traversal Test"\n'
            'timezone = "UTC"\n\n'
            "[[pages]]\n"
            'id = "timeline"\n'
            'title = "Posts"\n\n'
            "[[pages]]\n"
            'id = "leak"\n'
            'title = "Leak"\n'
            'file = "../secret.md"\n',
            encoding="utf-8",
        )
        settings = Settings(
            secret_key="test-secret-key-very-long-for-security",
            debug=True,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
            content_dir=content_dir,
            frontend_dir=tmp_path / "frontend",
            admin_username="admin",
            admin_password="admin123",
            auth_self_registration=True,
        )

        async with create_test_client(settings) as local_client:
            resp = await local_client.get("/api/pages/leak")
            assert resp.status_code == 404


class TestLoginOriginValidation:
    @pytest.mark.asyncio
    async def test_login_rejects_untrusted_origin(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
            headers={"Origin": "http://evil.example"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_login_succeeds_behind_tls_terminating_proxy(
        self, tmp_content_dir: Path, tmp_path: Path
    ) -> None:
        """Login must work when a reverse proxy terminates TLS.

        The browser sends Origin: https://blog.example.com but the proxy
        forwards over HTTP with X-Forwarded-Proto: https.  The origin check
        must reconstruct the public URL from forwarded headers so it matches
        the browser Origin.
        """
        settings = Settings(
            secret_key="test-secret-key-long-enough-here",
            debug=False,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'proxy.db'}",
            content_dir=tmp_content_dir,
            frontend_dir=tmp_path / "frontend",
            admin_username="admin",
            admin_password="admin123",
            trusted_hosts=["blog.example.com"],
            trusted_proxy_ips=["127.0.0.1"],
        )

        async with create_test_client(settings) as local_client:
            resp = await local_client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "admin123"},
                headers={
                    "Host": "blog.example.com",
                    "Origin": "https://blog.example.com",
                    "X-Forwarded-Proto": "https",
                },
            )
            assert resp.status_code == 200, resp.text

    @pytest.mark.asyncio
    async def test_untrusted_proxy_cannot_forge_forwarded_proto(self, client: AsyncClient) -> None:
        """X-Forwarded-Proto from non-trusted clients must be ignored."""
        resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
            headers={
                "Origin": "https://test",
                "X-Forwarded-Proto": "https",
            },
        )
        # The test fixture has no trusted_proxy_ips, so the header is ignored
        # and Origin https://test doesn't match request base http://test → 403
        assert resp.status_code == 403


class TestRateLimitClientIpHandling:
    @pytest.mark.asyncio
    async def test_untrusted_forwarded_for_does_not_bypass_login_rate_limit(
        self, client: AsyncClient
    ) -> None:
        first = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong"},
            headers={"X-Forwarded-For": "203.0.113.10"},
        )
        second = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong"},
            headers={"X-Forwarded-For": "198.51.100.42"},
        )

        assert first.status_code == 401
        assert second.status_code == 429


class TestProductionHardeningDefaults:
    @pytest.mark.asyncio
    async def test_docs_disabled_headers_set_and_untrusted_host_rejected(
        self,
        tmp_path: Path,
    ) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "posts").mkdir()
        (content_dir / "index.toml").write_text(
            "[site]\n"
            'title = "Hardening Test"\n'
            'timezone = "UTC"\n\n'
            "[[pages]]\n"
            'id = "timeline"\n'
            'title = "Posts"\n',
            encoding="utf-8",
        )
        (content_dir / "labels.toml").write_text("[labels]\n", encoding="utf-8")

        settings = Settings(
            secret_key="this-is-a-long-production-like-secret-key",
            debug=False,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'prod.db'}",
            content_dir=content_dir,
            frontend_dir=tmp_path / "frontend",
            admin_username="admin",
            admin_password="this-is-a-long-admin-password",
            trusted_hosts=["test"],
        )

        async with create_test_client(settings) as local_client:
            docs_resp = await local_client.get("/docs")
            assert docs_resp.status_code == 404

            health_resp = await local_client.get("/api/health")
            assert health_resp.status_code == 200

            # 127.0.0.1 is always trusted for container health checks
            loopback_resp = await local_client.get("/api/health", headers={"host": "127.0.0.1"})
            assert loopback_resp.status_code == 200

            assert health_resp.headers.get("x-content-type-options") == "nosniff"
            assert health_resp.headers.get("x-frame-options") == "DENY"
            assert health_resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
            assert "content-security-policy" in health_resp.headers
            assert health_resp.headers.get("cross-origin-opener-policy") == "same-origin"
            assert health_resp.headers.get("cross-origin-resource-policy") == "same-origin"
            permissions_policy = health_resp.headers.get("permissions-policy")
            assert permissions_policy is not None
            assert "clipboard-write=(self)" in permissions_policy
            assert "fullscreen=(self)" in permissions_policy
            assert "web-share=(self)" in permissions_policy

            bad_host_resp = await local_client.get("/api/health", headers={"Host": "evil.example"})
            assert bad_host_resp.status_code == 400


class TestRefererOriginEnforcement:
    @pytest.mark.asyncio
    async def test_login_rejects_untrusted_referer_when_origin_absent(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
            headers={"Referer": "http://evil.example/page"},
        )
        assert resp.status_code == 403


class TestRegistrationDisabled:
    @pytest.fixture
    def disabled_settings(self, tmp_content_dir: Path, tmp_path: Path) -> Settings:
        posts_dir = tmp_content_dir / "posts"
        hello_post = posts_dir / "hello"
        hello_post.mkdir()
        (hello_post / "index.md").write_text("# Hello\n", encoding="utf-8")
        (tmp_content_dir / "labels.toml").write_text("[labels]\n", encoding="utf-8")
        db_path = tmp_path / "test_disabled.db"
        return Settings(
            secret_key="test-secret-key-very-long-for-security",
            debug=True,
            database_url=f"sqlite+aiosqlite:///{db_path}",
            content_dir=tmp_content_dir,
            frontend_dir=tmp_path / "frontend",
            admin_username="admin",
            admin_password="admin123",
            auth_self_registration=False,
            auth_invites_enabled=False,
        )

    @pytest.mark.asyncio
    async def test_register_returns_403_when_registration_fully_disabled(
        self, disabled_settings: Settings
    ) -> None:
        async with create_test_client(disabled_settings) as local_client:
            resp = await local_client.post(
                "/api/auth/register",
                json={
                    "username": "newuser",
                    "email": "new@test.com",
                    "password": "password1234",
                },
            )
            assert resp.status_code == 403
            assert "Registration is disabled" in resp.json()["detail"]


class TestIsTrustedProxy:
    def test_exact_ip_match(self) -> None:
        from backend.api.auth import _is_trusted_proxy

        assert _is_trusted_proxy("127.0.0.1", ["127.0.0.1"]) is True
        assert _is_trusted_proxy("10.0.0.1", ["127.0.0.1"]) is False

    def test_cidr_match(self) -> None:
        from backend.api.auth import _is_trusted_proxy

        assert _is_trusted_proxy("172.30.0.2", ["172.30.0.0/24"]) is True
        assert _is_trusted_proxy("172.30.0.99", ["172.30.0.0/24"]) is True
        assert _is_trusted_proxy("172.31.0.2", ["172.30.0.0/24"]) is False

    def test_invalid_client_ip(self) -> None:
        from backend.api.auth import _is_trusted_proxy

        assert _is_trusted_proxy("not-an-ip", ["127.0.0.1"]) is False

    def test_invalid_trusted_entry_is_skipped(self) -> None:
        from backend.api.auth import _is_trusted_proxy

        assert _is_trusted_proxy("127.0.0.1", ["bad-entry", "127.0.0.1"]) is True

    def test_invalid_trusted_entry_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        from backend.api.auth import _is_trusted_proxy

        with caplog.at_level(logging.WARNING, logger="backend.net_utils"):
            _is_trusted_proxy("127.0.0.1", ["not-valid-cidr/33", "127.0.0.1"])
        assert any("not-valid-cidr/33" in msg for msg in caplog.messages)

    def test_empty_list(self) -> None:
        from backend.api.auth import _is_trusted_proxy

        assert _is_trusted_proxy("127.0.0.1", []) is False


class TestSharedIsTrustedFunction:
    """Issue #1 and #6: Shared is_trusted_proxy in backend.net_utils."""

    def test_shared_function_exists_in_net_utils(self) -> None:
        from backend.net_utils import is_trusted_proxy

        assert callable(is_trusted_proxy)

    def test_auth_uses_shared_function(self) -> None:
        """_is_trusted_proxy in auth.py should delegate to the shared function."""
        from backend.api.auth import _is_trusted_proxy
        from backend.net_utils import is_trusted_proxy

        # Both should return the same result for identical inputs
        assert _is_trusted_proxy("127.0.0.1", ["127.0.0.1"]) == is_trusted_proxy(
            "127.0.0.1", ["127.0.0.1"]
        )
        assert _is_trusted_proxy("10.0.0.2", ["127.0.0.1"]) == is_trusted_proxy(
            "10.0.0.2", ["127.0.0.1"]
        )

    def test_middleware_uses_shared_function(self) -> None:
        """_ProxyHeadersMiddleware._is_trusted should delegate to the shared function."""
        from backend.main import _ProxyHeadersMiddleware
        from backend.net_utils import is_trusted_proxy

        mw = _ProxyHeadersMiddleware(app=None, trusted_ips=["127.0.0.1"])  # type: ignore[arg-type]
        assert mw._is_trusted("127.0.0.1") == is_trusted_proxy("127.0.0.1", ["127.0.0.1"])
        assert mw._is_trusted("10.0.0.2") == is_trusted_proxy("10.0.0.2", ["127.0.0.1"])

    def test_exact_ip_match(self) -> None:
        from backend.net_utils import is_trusted_proxy

        assert is_trusted_proxy("127.0.0.1", ["127.0.0.1"]) is True
        assert is_trusted_proxy("10.0.0.1", ["127.0.0.1"]) is False

    def test_cidr_match(self) -> None:
        from backend.net_utils import is_trusted_proxy

        assert is_trusted_proxy("172.30.0.2", ["172.30.0.0/24"]) is True
        assert is_trusted_proxy("172.30.0.99", ["172.30.0.0/24"]) is True
        assert is_trusted_proxy("172.31.0.2", ["172.30.0.0/24"]) is False

    def test_ipv6_exact_match(self) -> None:
        from backend.net_utils import is_trusted_proxy

        assert is_trusted_proxy("::1", ["::1"]) is True
        assert is_trusted_proxy("::2", ["::1"]) is False

    def test_ipv6_cidr_match(self) -> None:
        from backend.net_utils import is_trusted_proxy

        assert is_trusted_proxy("fd00::1", ["fd00::/8"]) is True
        assert is_trusted_proxy("fe80::1", ["fd00::/8"]) is False

    def test_ipv6_equivalent_representations(self) -> None:
        """Equivalent IPv6 representations should match (parsed objects, not raw strings)."""
        from backend.net_utils import is_trusted_proxy

        # "::1" and "0:0:0:0:0:0:0:1" are the same address
        assert is_trusted_proxy("0:0:0:0:0:0:0:1", ["::1"]) is True
        assert is_trusted_proxy("::1", ["0:0:0:0:0:0:0:1"]) is True

    def test_malformed_entry_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        from backend.net_utils import is_trusted_proxy

        with caplog.at_level(logging.WARNING, logger="backend.net_utils"):
            result = is_trusted_proxy("127.0.0.1", ["not-valid/33", "127.0.0.1"])
        assert result is True
        assert any("not-valid/33" in msg for msg in caplog.messages)

    def test_invalid_client_ip(self) -> None:
        from backend.net_utils import is_trusted_proxy

        assert is_trusted_proxy("not-an-ip", ["127.0.0.1"]) is False

    def test_empty_trusted_list(self) -> None:
        from backend.net_utils import is_trusted_proxy

        assert is_trusted_proxy("127.0.0.1", []) is False

    def test_middleware_malformed_entry_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Middleware _is_trusted should log warnings for malformed entries."""
        import logging

        from backend.main import _ProxyHeadersMiddleware

        mw = _ProxyHeadersMiddleware(app=None, trusted_ips=["bad-entry/999"])  # type: ignore[arg-type]
        with caplog.at_level(logging.WARNING, logger="backend.net_utils"):
            result = mw._is_trusted("127.0.0.1")
        assert result is False
        assert any("bad-entry/999" in msg for msg in caplog.messages)


class TestDuplicateXForwardedForHeaders:
    """Issue #3: dict(scope['headers']) drops duplicate headers — first occurrence must be used."""

    @pytest.fixture
    def proxy_settings(self, tmp_content_dir: Path, tmp_path: Path) -> Settings:
        """Settings with 127.0.0.1 as trusted proxy."""
        (tmp_content_dir / "posts").mkdir(exist_ok=True)
        (tmp_content_dir / "labels.toml").write_text("[labels]\n", encoding="utf-8")
        return Settings(
            secret_key="test-secret-key-very-long-for-security",
            debug=True,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'dup_xff.db'}",
            content_dir=tmp_content_dir,
            frontend_dir=tmp_path / "frontend",
            admin_username="admin",
            admin_password="admin123",
            auth_login_max_failures=5,
            auth_rate_limit_window_seconds=300,
            trusted_proxy_ips=["127.0.0.1"],
        )

    @pytest.mark.asyncio
    async def test_duplicate_xff_first_occurrence_used(self, proxy_settings: Settings) -> None:
        """When multiple X-Forwarded-For headers are present, the FIRST must be used."""
        import ipaddress

        from backend.main import _ProxyHeadersMiddleware

        seen_clients: list[str] = []

        async def capture_app(scope, receive, send):
            if scope["type"] == "http":
                client = scope.get("client")
                if client:
                    seen_clients.append(client[0])
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/plain")],
                }
            )
            await send({"type": "http.response.body", "body": b"ok"})

        mw = _ProxyHeadersMiddleware(app=capture_app, trusted_ips=["127.0.0.1"])

        # Simulate ASGI with duplicate X-Forwarded-For headers
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [
                (b"x-forwarded-for", b"203.0.113.10"),
                (b"x-forwarded-for", b"198.51.100.42"),
            ],
            "client": ("127.0.0.1", 12345),
        }

        messages: list[dict[str, object]] = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        await mw(scope, receive, send)

        assert len(seen_clients) == 1
        # Should use the FIRST X-Forwarded-For value, not the second
        assert seen_clients[0] == "203.0.113.10"
        # Extra safety: confirm it is a valid IP
        ipaddress.ip_address(seen_clients[0])


class TestXForwardedProtoValidation:
    """Issue #4: X-Forwarded-Proto must be restricted to 'http'/'https'."""

    @pytest.fixture
    def proxy_settings(self, tmp_content_dir: Path, tmp_path: Path) -> Settings:
        (tmp_content_dir / "posts").mkdir(exist_ok=True)
        (tmp_content_dir / "labels.toml").write_text("[labels]\n", encoding="utf-8")
        return Settings(
            secret_key="test-secret-key-very-long-for-security",
            debug=True,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'xfp_test.db'}",
            content_dir=tmp_content_dir,
            frontend_dir=tmp_path / "frontend",
            admin_username="admin",
            admin_password="admin123",
            trusted_proxy_ips=["127.0.0.1"],
        )

    @pytest.mark.asyncio
    async def test_valid_https_proto_is_accepted(self) -> None:
        from backend.main import _ProxyHeadersMiddleware

        seen_schemes: list[str] = []

        async def capture_app(scope, receive, send):
            seen_schemes.append(scope.get("scheme", ""))
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/plain")],
                }
            )
            await send({"type": "http.response.body", "body": b"ok"})

        mw = _ProxyHeadersMiddleware(app=capture_app, trusted_ips=["127.0.0.1"])
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [(b"x-forwarded-proto", b"https")],
            "client": ("127.0.0.1", 12345),
            "scheme": "http",
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            pass

        await mw(scope, receive, send)
        assert scope["scheme"] == "https"

    @pytest.mark.asyncio
    async def test_valid_http_proto_is_accepted(self) -> None:
        from backend.main import _ProxyHeadersMiddleware

        async def dummy_app(scope, receive, send):
            pass

        mw_with_app = _ProxyHeadersMiddleware(app=dummy_app, trusted_ips=["127.0.0.1"])
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [(b"x-forwarded-proto", b"http")],
            "client": ("127.0.0.1", 12345),
            "scheme": "https",
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            pass

        await mw_with_app(scope, receive, send)
        assert scope["scheme"] == "http"

    @pytest.mark.asyncio
    async def test_unexpected_proto_is_rejected_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        from backend.main import _ProxyHeadersMiddleware

        async def dummy_app(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/plain")],
                }
            )
            await send({"type": "http.response.body", "body": b"ok"})

        mw = _ProxyHeadersMiddleware(app=dummy_app, trusted_ips=["127.0.0.1"])
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [(b"x-forwarded-proto", b"ftp")],
            "client": ("127.0.0.1", 12345),
            "scheme": "http",
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            pass

        with caplog.at_level(logging.WARNING, logger="backend.main"):
            await mw(scope, receive, send)

        # Unexpected proto should NOT be applied to the scope
        assert scope["scheme"] == "http"
        # A warning should be logged
        assert any(
            "ftp" in msg.lower() or "forwarded-proto" in msg.lower() for msg in caplog.messages
        )


class TestMiddlewareOrderingComment:
    """Issue #16: Middleware ordering comment should clarify request-time inversion."""

    def test_ordering_comment_explains_inversion(self) -> None:
        """The middleware ordering comment must mention request-time inversion."""
        import inspect

        from backend import main

        source = inspect.getsource(main.create_app)
        # The comment near add_middleware calls should explain that Starlette
        # wraps middleware in reverse order (outermost = last added = first at request time)
        assert "invert" in source.lower() or "wrap" in source.lower() or "last" in source.lower()


class TestTrustedProxyForwarding:
    @pytest.fixture
    def trusted_proxy_settings(self, tmp_content_dir: Path, tmp_path: Path) -> Settings:
        """Settings with 127.0.0.1 as a trusted proxy."""
        posts_dir = tmp_content_dir / "posts"
        hello_post = posts_dir / "hello"
        hello_post.mkdir()
        (hello_post / "index.md").write_text(
            "---\n"
            "title: Hello World\n"
            "created_at: 2026-02-02 22:21:29.975359+00\n"
            "author: admin\n"
            "labels: []\n"
            "---\nHello.\n",
            encoding="utf-8",
        )
        (tmp_content_dir / "labels.toml").write_text("[labels]\n", encoding="utf-8")
        db_path = tmp_path / "test_proxy.db"
        return Settings(
            secret_key="test-secret-key-very-long-for-security",
            debug=True,
            database_url=f"sqlite+aiosqlite:///{db_path}",
            content_dir=tmp_content_dir,
            frontend_dir=tmp_path / "frontend",
            admin_username="admin",
            admin_password="admin123",
            auth_login_max_failures=2,
            auth_rate_limit_window_seconds=300,
            trusted_proxy_ips=["127.0.0.1"],
        )

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_trusted_proxy_separates_forwarded_ips(
        self, trusted_proxy_settings: Settings
    ) -> None:
        """With a trusted proxy, different X-Forwarded-For IPs are treated as separate clients."""
        async with create_test_client(trusted_proxy_settings) as proxy_client:
            first = await proxy_client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "wrong"},
                headers={"X-Forwarded-For": "203.0.113.10"},
            )
            second = await proxy_client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "wrong"},
                headers={"X-Forwarded-For": "198.51.100.42"},
            )

            # Both should get 401 (not 429) because they are different clients
            assert first.status_code == 401
            assert second.status_code == 401

    @pytest.mark.asyncio
    async def test_untrusted_proxy_shares_rate_limit(self, client: AsyncClient) -> None:
        """Without trusted proxy, different X-Forwarded-For headers share the same rate limit."""
        first = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong"},
            headers={"X-Forwarded-For": "203.0.113.10"},
        )
        second = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong"},
            headers={"X-Forwarded-For": "198.51.100.42"},
        )

        # Both use the actual client IP → shared rate limit → second is 429
        assert first.status_code == 401
        assert second.status_code == 429

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_cidr_trusted_proxy_separates_forwarded_ips(
        self, tmp_content_dir: Path, tmp_path: Path
    ) -> None:
        """CIDR-based trusted proxy entries correctly separate forwarded client IPs."""
        posts_dir = tmp_content_dir / "posts"
        hello_post = posts_dir / "hello"
        hello_post.mkdir()
        (hello_post / "index.md").write_text(
            "---\n"
            "title: Hello World\n"
            "created_at: 2026-02-02 22:21:29.975359+00\n"
            "author: admin\n"
            "labels: []\n"
            "---\nHello.\n",
            encoding="utf-8",
        )
        (tmp_content_dir / "labels.toml").write_text("[labels]\n", encoding="utf-8")
        db_path = tmp_path / "test_cidr_proxy.db"
        cidr_settings = Settings(
            secret_key="test-secret-key-very-long-for-security",
            debug=True,
            database_url=f"sqlite+aiosqlite:///{db_path}",
            content_dir=tmp_content_dir,
            frontend_dir=tmp_path / "frontend",
            admin_username="admin",
            admin_password="admin123",
            auth_login_max_failures=2,
            auth_rate_limit_window_seconds=300,
            trusted_proxy_ips=["127.0.0.0/8"],
        )
        async with create_test_client(cidr_settings) as cidr_client:
            first = await cidr_client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "wrong"},
                headers={"X-Forwarded-For": "203.0.113.10"},
            )
            second = await cidr_client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "wrong"},
                headers={"X-Forwarded-For": "198.51.100.42"},
            )
            assert first.status_code == 401
            assert second.status_code == 401


class TestProductionStartupValidation:
    @pytest.mark.asyncio
    async def test_production_rejects_insecure_default_secrets(self, tmp_path: Path) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "posts").mkdir()
        (content_dir / "index.toml").write_text(
            "[site]\n"
            'title = "Hardening Test"\n'
            'timezone = "UTC"\n\n'
            "[[pages]]\n"
            'id = "timeline"\n'
            'title = "Posts"\n',
            encoding="utf-8",
        )
        (content_dir / "labels.toml").write_text("[labels]\n", encoding="utf-8")
        settings = Settings(
            secret_key="change-me-in-production",
            debug=False,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'prod.db'}",
            content_dir=content_dir,
            frontend_dir=tmp_path / "frontend",
            admin_username="admin",
            admin_password="admin",
            trusted_hosts=["test"],
        )

        from backend.exceptions import InternalServerError

        with pytest.raises(InternalServerError):
            async with create_test_client(settings):
                pass
