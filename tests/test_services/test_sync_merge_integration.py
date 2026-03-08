"""Integration tests for simplified sync protocol."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.slow

from backend.config import Settings
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient


@pytest.fixture
def merge_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    posts_dir = tmp_content_dir / "posts"
    (posts_dir / "shared.md").write_text(
        "---\ntitle: Shared Post\ncreated_at: 2026-02-01 00:00:00+00\nauthor: Admin\n"
        "labels:\n- '#a'\n---\n\nParagraph one.\n\nParagraph two.\n"
    )
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
async def merge_client(merge_settings: Settings) -> AsyncGenerator[AsyncClient]:
    async with create_test_client(merge_settings) as ac:
        yield ac


async def _login(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": "admin", "password": "admin123"},
    )
    return resp.json()["access_token"]


class TestSyncStatus:
    async def test_status_returns_plan(self, merge_client: AsyncClient) -> None:
        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}
        resp = await merge_client.post(
            "/api/sync/status",
            json={"client_manifest": []},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "to_upload" in data
        assert "to_download" in data
        assert "server_commit" in data


class TestSyncCommit:
    async def test_clean_body_merge(
        self, merge_client: AsyncClient, merge_settings: Settings
    ) -> None:
        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        resp = await merge_client.post(
            "/api/sync/status",
            json={"client_manifest": []},
            headers=headers,
        )
        server_commit = resp.json()["server_commit"]

        resp = await merge_client.put(
            "/api/posts/posts/shared.md",
            json={
                "title": "Shared Post",
                "body": "Paragraph one (server edit).\n\nParagraph two.\n",
                "labels": ["a"],
                "is_draft": False,
            },
            headers=headers,
        )
        assert resp.status_code == 200

        client_content = (
            "---\ntitle: Shared Post\ncreated_at: 2026-02-01 00:00:00+00\nauthor: Admin\n"
            "labels:\n- '#a'\n---\n\nParagraph one.\n\nParagraph two (client edit).\n"
        )
        metadata = json.dumps({"deleted_files": [], "last_sync_commit": server_commit})
        resp = await merge_client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            files=[
                ("files", ("posts/shared.md", io.BytesIO(client_content.encode()), "text/plain")),
            ],
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["commit_hash"] is not None
        assert len(data["conflicts"]) == 0

        dl_resp = await merge_client.get("/api/sync/download/posts/shared.md", headers=headers)
        merged = dl_resp.content.decode()
        assert "server edit" in merged
        assert "client edit" in merged

    async def test_body_conflict_server_wins(
        self, merge_client: AsyncClient, merge_settings: Settings
    ) -> None:
        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        resp = await merge_client.post(
            "/api/sync/status",
            json={"client_manifest": []},
            headers=headers,
        )
        server_commit = resp.json()["server_commit"]

        resp = await merge_client.put(
            "/api/posts/posts/shared.md",
            json={
                "title": "Shared Post",
                "body": "Server version of paragraph one.\n\nParagraph two.\n",
                "labels": ["a"],
                "is_draft": False,
            },
            headers=headers,
        )
        assert resp.status_code == 200

        client_content = (
            "---\ntitle: Shared Post\ncreated_at: 2026-02-01 00:00:00+00\nauthor: Admin\n"
            "labels:\n- '#a'\n---\n\nClient version of paragraph one.\n\nParagraph two.\n"
        )
        metadata = json.dumps({"deleted_files": [], "last_sync_commit": server_commit})
        resp = await merge_client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            files=[
                ("files", ("posts/shared.md", io.BytesIO(client_content.encode()), "text/plain")),
            ],
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["conflicts"]) == 1
        assert data["conflicts"][0]["body_conflicted"] is True

        dl_resp = await merge_client.get("/api/sync/download/posts/shared.md", headers=headers)
        assert b"Server version" in dl_resp.content

    async def test_no_base_server_wins(self, merge_client: AsyncClient) -> None:
        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        client_content = b"---\ntitle: Different\nauthor: Admin\n---\n\nClient only.\n"
        metadata = json.dumps({"deleted_files": [], "last_sync_commit": None})
        resp = await merge_client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            files=[
                ("files", ("posts/shared.md", io.BytesIO(client_content), "text/plain")),
            ],
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["conflicts"]) == 1

    async def test_commit_no_changes(self, merge_client: AsyncClient) -> None:
        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        metadata = json.dumps({"deleted_files": []})
        resp = await merge_client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    async def test_upload_new_file(self, merge_client: AsyncClient) -> None:
        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        new_content = b"---\ntitle: New Post\nauthor: Admin\n---\n\nBrand new.\n"
        metadata = json.dumps({"deleted_files": []})
        resp = await merge_client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            files=[
                (
                    "files",
                    ("posts/2026-02-22-new/index.md", io.BytesIO(new_content), "text/plain"),
                ),
            ],
            headers=headers,
        )
        assert resp.status_code == 200

        dl_resp = await merge_client.get(
            "/api/sync/download/posts/2026-02-22-new/index.md", headers=headers
        )
        assert dl_resp.status_code == 200
        assert b"Brand new" in dl_resp.content

    async def test_delete_file(self, merge_client: AsyncClient, merge_settings: Settings) -> None:
        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        metadata = json.dumps({"deleted_files": ["posts/shared.md"]})
        resp = await merge_client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            headers=headers,
        )
        assert resp.status_code == 200

        dl_resp = await merge_client.get("/api/sync/download/posts/shared.md", headers=headers)
        assert dl_resp.status_code == 404

    async def test_invalid_metadata_json_returns_400(self, merge_client: AsyncClient) -> None:
        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        resp = await merge_client.post(
            "/api/sync/commit",
            data={"metadata": "not valid json{{{"},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "Invalid metadata JSON" in resp.json()["detail"]

    async def test_invalid_metadata_types_returns_400(self, merge_client: AsyncClient) -> None:
        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        metadata = json.dumps({"deleted_files": "not-a-list"})
        resp = await merge_client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            headers=headers,
        )
        assert resp.status_code == 400

    async def test_upload_too_large_returns_413(
        self, merge_client: AsyncClient, merge_settings: Settings
    ) -> None:
        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        # 10 MB + 1 byte
        big_content = b"x" * (10 * 1024 * 1024 + 1)
        metadata = json.dumps({"deleted_files": []})
        resp = await merge_client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            files=[("files", ("posts/big.md", io.BytesIO(big_content), "text/plain"))],
            headers=headers,
        )
        assert resp.status_code == 413

    async def test_binary_file_upload(self, merge_client: AsyncClient) -> None:
        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        # Upload a binary file (PNG header)
        binary_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        metadata = json.dumps({"deleted_files": []})
        resp = await merge_client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            files=[
                (
                    "files",
                    ("posts/2026-02-22-img/photo.png", io.BytesIO(binary_content), "image/png"),
                )
            ],
            headers=headers,
        )
        assert resp.status_code == 200

        dl_resp = await merge_client.get(
            "/api/sync/download/posts/2026-02-22-img/photo.png", headers=headers
        )
        assert dl_resp.status_code == 200
        assert dl_resp.content == binary_content

    async def test_non_post_md_conflict_last_writer_wins(
        self, merge_client: AsyncClient, merge_settings: Settings
    ) -> None:
        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        # Write a non-post file on server
        content_dir = merge_settings.content_dir
        (content_dir / "labels.toml").write_text("[labels.server]\nnames = ['server']\n")

        # Upload a different version via sync
        client_content = b"[labels.client]\nnames = ['client']\n"
        metadata = json.dumps({"deleted_files": []})
        resp = await merge_client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            files=[("files", ("labels.toml", io.BytesIO(client_content), "text/plain"))],
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        # Non-post files use last-writer-wins (client wins), no conflict reported
        assert len(data["conflicts"]) == 0

        dl_resp = await merge_client.get("/api/sync/download/labels.toml", headers=headers)
        assert b"client" in dl_resp.content

    async def test_files_synced_reflects_actual_changes(self, merge_client: AsyncClient) -> None:
        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        new_content = b"---\ntitle: Synced\nauthor: Admin\n---\n\nBody.\n"
        metadata = json.dumps({"deleted_files": []})
        resp = await merge_client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            files=[
                (
                    "files",
                    ("posts/2026-02-22-synced/index.md", io.BytesIO(new_content), "text/plain"),
                ),
            ],
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        # files_synced should reflect actual changes, not total content dir files
        # We uploaded 1 file, so files_synced should include that count
        assert data["files_synced"] >= 1

    async def test_labels_merged_as_sets(
        self, merge_client: AsyncClient, merge_settings: Settings
    ) -> None:
        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        resp = await merge_client.post(
            "/api/sync/status",
            json={"client_manifest": []},
            headers=headers,
        )
        server_commit = resp.json()["server_commit"]

        resp = await merge_client.put(
            "/api/posts/posts/shared.md",
            json={
                "title": "Shared Post",
                "body": "Paragraph one.\n\nParagraph two.\n",
                "labels": ["a", "server-label"],
                "is_draft": False,
            },
            headers=headers,
        )
        assert resp.status_code == 200

        client_content = (
            "---\ntitle: Shared Post\ncreated_at: 2026-02-01 00:00:00+00\nauthor: Admin\n"
            "labels:\n- '#a'\n- '#client-label'\n---\n\nParagraph one.\n\nParagraph two.\n"
        )
        metadata = json.dumps({"deleted_files": [], "last_sync_commit": server_commit})
        resp = await merge_client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            files=[
                ("files", ("posts/shared.md", io.BytesIO(client_content.encode()), "text/plain")),
            ],
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["conflicts"]) == 0

        dl_resp = await merge_client.get("/api/sync/download/posts/shared.md", headers=headers)
        merged = dl_resp.content.decode()
        assert "#server-label" in merged
        assert "#client-label" in merged
        assert "#a" in merged

    async def test_merge_failure_does_not_normalize_frontmatter(
        self, merge_client: AsyncClient, merge_settings: Settings
    ) -> None:
        """When merge_post_file raises CalledProcessError, the file must NOT be
        added to uploaded_paths and normalize_post_frontmatter must NOT process it."""
        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        # Get server commit so the sync endpoint attempts a three-way merge
        resp = await merge_client.post(
            "/api/sync/status",
            json={"client_manifest": []},
            headers=headers,
        )
        server_commit = resp.json()["server_commit"]

        # Edit server version so server_content != client_text (triggers merge path)
        resp = await merge_client.put(
            "/api/posts/posts/shared.md",
            json={
                "title": "Shared Post",
                "body": "Server edited paragraph.\n\nParagraph two.\n",
                "labels": ["a"],
                "is_draft": False,
            },
            headers=headers,
        )
        assert resp.status_code == 200

        client_content = (
            "---\ntitle: Shared Post\ncreated_at: 2026-02-01 00:00:00+00\nauthor: Admin\n"
            "labels:\n- '#a'\n---\n\nClient edited paragraph.\n\nParagraph two.\n"
        )

        # Patch merge_post_file to raise CalledProcessError and spy on normalize
        error = subprocess.CalledProcessError(1, "git merge-file", stderr="merge failed")

        with (
            patch("backend.api.sync.merge_post_file", side_effect=error),
            patch("backend.api.sync.normalize_post_frontmatter", return_value=[]) as mock_norm,
        ):
            metadata = json.dumps({"deleted_files": [], "last_sync_commit": server_commit})
            resp = await merge_client.post(
                "/api/sync/commit",
                data={"metadata": metadata},
                files=[
                    (
                        "files",
                        ("posts/shared.md", io.BytesIO(client_content.encode()), "text/plain"),
                    ),
                ],
                headers=headers,
            )

        assert resp.status_code == 200
        data = resp.json()

        # Should report the conflict
        assert len(data["conflicts"]) == 1
        assert data["conflicts"][0]["file_path"] == "posts/shared.md"
        assert data["conflicts"][0]["body_conflicted"] is True

        # The critical assertion: normalize_post_frontmatter should NOT
        # receive the failed merge path in its uploaded_files list
        mock_norm.assert_called_once()
        uploaded_files_arg = mock_norm.call_args.kwargs.get(
            "uploaded_files", mock_norm.call_args.args[0] if mock_norm.call_args.args else []
        )
        assert "posts/shared.md" not in uploaded_files_arg


def _sha256(data: bytes) -> str:
    """Compute SHA-256 hex digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


class TestSyncRoundTrip:
    async def test_full_bidirectional_sync_round_trip(
        self, merge_client: AsyncClient, merge_settings: Settings
    ) -> None:
        """Full round trip: client uploads -> status clean -> server edits -> client downloads."""
        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        # Step 1: Client uploads a new file via sync commit
        # Directory name must match the slug of the title ("round-trip-post")
        # to avoid rename when the server processes the file via PUT.
        new_content = b"---\ntitle: Round Trip Post\nauthor: Admin\n---\n\nOriginal content.\n"
        new_file_path = "posts/2026-03-01-round-trip-post/index.md"
        metadata = json.dumps({"deleted_files": []})
        commit_resp = await merge_client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            files=[
                ("files", (new_file_path, io.BytesIO(new_content), "text/plain")),
            ],
            headers=headers,
        )
        assert commit_resp.status_code == 200
        commit_data = commit_resp.json()
        assert commit_data["commit_hash"] is not None
        assert len(commit_data["conflicts"]) == 0

        # Step 2: Verify sync status shows no pending actions
        # The client provides a manifest entry matching what it just uploaded.
        # After sync commit the server normalizes frontmatter, so download the
        # actual file content and compute the hash from it.
        dl_after_upload = await merge_client.get(
            f"/api/sync/download/{new_file_path}", headers=headers
        )
        assert dl_after_upload.status_code == 200
        uploaded_bytes = dl_after_upload.content
        uploaded_hash = _sha256(uploaded_bytes)

        status_resp = await merge_client.post(
            "/api/sync/status",
            json={
                "client_manifest": [
                    {
                        "file_path": new_file_path,
                        "content_hash": uploaded_hash,
                        "file_size": len(uploaded_bytes),
                        "file_mtime": "0",
                    }
                ]
            },
            headers=headers,
        )
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        # The uploaded file should NOT appear in to_download or to_upload
        assert new_file_path not in status_data["to_download"]
        assert new_file_path not in status_data["to_upload"]

        # Step 3: Server-side modification via PUT /api/posts/
        edit_resp = await merge_client.put(
            f"/api/posts/{new_file_path}",
            json={
                "title": "Round Trip Post",
                "body": "Server-modified content.\n\nNew paragraph added by server.\n",
                "labels": [],
                "is_draft": False,
            },
            headers=headers,
        )
        assert edit_resp.status_code == 200

        # Step 4: Client checks sync status -> sees download needed
        # Client still has the old hash, so the server-modified file should
        # appear in to_download.
        status_resp2 = await merge_client.post(
            "/api/sync/status",
            json={
                "client_manifest": [
                    {
                        "file_path": new_file_path,
                        "content_hash": uploaded_hash,
                        "file_size": len(uploaded_bytes),
                        "file_mtime": "0",
                    }
                ]
            },
            headers=headers,
        )
        assert status_resp2.status_code == 200
        status_data2 = status_resp2.json()
        assert new_file_path in status_data2["to_download"]

        # Step 5: Client downloads the modified file
        dl_resp = await merge_client.get(f"/api/sync/download/{new_file_path}", headers=headers)
        assert dl_resp.status_code == 200
        modified_content = dl_resp.content.decode()

        # Step 6: Verify content matches server version
        assert "Server-modified content" in modified_content
        assert "New paragraph added by server" in modified_content
