"""Integration tests for simplified sync protocol."""

from __future__ import annotations

import hashlib
import io
import json
import pathlib
import subprocess
import tomllib
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
import tomli_w

from backend.config import Settings
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient


@pytest.fixture
def merge_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    posts_dir = tmp_content_dir / "posts"
    shared_dir = posts_dir / "shared"
    shared_dir.mkdir()
    (shared_dir / "index.md").write_text(
        "---\ntitle: Shared Post\ncreated_at: 2026-02-01 00:00:00+00\nauthor: admin\n"
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
            "/api/posts/posts/shared/index.md",
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
            "---\ntitle: Shared Post\ncreated_at: 2026-02-01 00:00:00+00\nauthor: admin\n"
            "labels:\n- '#a'\n---\n\nParagraph one.\n\nParagraph two (client edit).\n"
        )
        metadata = json.dumps({"deleted_files": [], "last_sync_commit": server_commit})
        resp = await merge_client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            files=[
                (
                    "files",
                    (
                        "posts/shared/index.md",
                        io.BytesIO(client_content.encode()),
                        "text/plain",
                    ),
                ),
            ],
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["commit_hash"] is not None
        assert len(data["conflicts"]) == 0

        dl_resp = await merge_client.get(
            "/api/sync/download/posts/shared/index.md",
            headers=headers,
        )
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
            "/api/posts/posts/shared/index.md",
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
            "---\ntitle: Shared Post\ncreated_at: 2026-02-01 00:00:00+00\nauthor: admin\n"
            "labels:\n- '#a'\n---\n\nClient version of paragraph one.\n\nParagraph two.\n"
        )
        metadata = json.dumps({"deleted_files": [], "last_sync_commit": server_commit})
        resp = await merge_client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            files=[
                (
                    "files",
                    (
                        "posts/shared/index.md",
                        io.BytesIO(client_content.encode()),
                        "text/plain",
                    ),
                ),
            ],
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["conflicts"]) == 1
        assert data["conflicts"][0]["body_conflicted"] is True

        dl_resp = await merge_client.get(
            "/api/sync/download/posts/shared/index.md",
            headers=headers,
        )
        assert b"Server version" in dl_resp.content

    async def test_no_base_server_wins(self, merge_client: AsyncClient) -> None:
        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        client_content = b"---\ntitle: Different\nauthor: admin\n---\n\nClient only.\n"
        metadata = json.dumps({"deleted_files": [], "last_sync_commit": None})
        resp = await merge_client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            files=[
                ("files", ("posts/shared/index.md", io.BytesIO(client_content), "text/plain")),
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

        new_content = b"---\ntitle: New Post\nauthor: admin\n---\n\nBrand new.\n"
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

        metadata = json.dumps({"deleted_files": ["posts/shared/index.md"]})
        resp = await merge_client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            headers=headers,
        )
        assert resp.status_code == 200

        dl_resp = await merge_client.get(
            "/api/sync/download/posts/shared/index.md",
            headers=headers,
        )
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
            files=[("files", ("posts/big/index.md", io.BytesIO(big_content), "text/plain"))],
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

    async def test_non_post_non_labels_conflict_last_writer_wins(
        self, merge_client: AsyncClient, merge_settings: Settings
    ) -> None:
        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        # Write a non-post, non-labels file on server
        content_dir = merge_settings.content_dir
        (content_dir / "index.toml").write_text('[site]\ntitle = "Server Title"\n')

        # Upload a different version via sync
        client_content = b'[site]\ntitle = "Client Title"\n'
        metadata = json.dumps({"deleted_files": []})
        resp = await merge_client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            files=[("files", ("index.toml", io.BytesIO(client_content), "text/plain"))],
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        # Non-post, non-labels files use last-writer-wins (client wins)
        assert len(data["conflicts"]) == 0

        dl_resp = await merge_client.get("/api/sync/download/index.toml", headers=headers)
        assert b"Client Title" in dl_resp.content

    async def test_labels_toml_three_way_merge(
        self, merge_client: AsyncClient, merge_settings: Settings
    ) -> None:
        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}
        content_dir = merge_settings.content_dir

        # Step 1: Create an initial labels.toml on the server
        initial_labels = tomli_w.dumps({"labels": {"swe": {"names": ["software engineering"]}}})
        (content_dir / "labels.toml").write_text(initial_labels, encoding="utf-8")

        # Step 2: Perform an initial sync commit so the client has a baseline
        # (this causes the server to create a git commit containing labels.toml)
        metadata = json.dumps({"deleted_files": []})
        resp = await merge_client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            files=[
                (
                    "files",
                    ("labels.toml", io.BytesIO(initial_labels.encode()), "text/plain"),
                ),
            ],
            headers=headers,
        )
        assert resp.status_code == 200
        last_sync_commit = resp.json()["commit_hash"]
        assert last_sync_commit is not None

        # Step 3: Modify labels.toml on the server (add "SWE" to the names)
        server_labels = tomli_w.dumps(
            {"labels": {"swe": {"names": ["software engineering", "SWE"]}}}
        )
        (content_dir / "labels.toml").write_text(server_labels, encoding="utf-8")

        # Step 4: Upload a different client version (add "coding" instead)
        client_labels = tomli_w.dumps(
            {"labels": {"swe": {"names": ["software engineering", "coding"]}}}
        )
        metadata = json.dumps({"deleted_files": [], "last_sync_commit": last_sync_commit})
        resp = await merge_client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            files=[
                (
                    "files",
                    ("labels.toml", io.BytesIO(client_labels.encode()), "text/plain"),
                ),
            ],
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()

        # Step 5: Assert 0 conflicts — set merge auto-resolves
        assert len(data["conflicts"]) == 0

        # Step 6: Assert labels.toml appears in to_download (server wrote merged version)
        assert "labels.toml" in data["to_download"]

        # Step 7: Download and assert merged content contains names from BOTH sides
        dl_resp = await merge_client.get("/api/sync/download/labels.toml", headers=headers)
        assert dl_resp.status_code == 200
        merged = tomllib.loads(dl_resp.content.decode())
        merged_names = set(merged["labels"]["swe"]["names"])
        assert "software engineering" in merged_names
        assert "SWE" in merged_names
        assert "coding" in merged_names

    async def test_files_synced_reflects_actual_changes(self, merge_client: AsyncClient) -> None:
        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        new_content = b"---\ntitle: Synced\nauthor: admin\n---\n\nBody.\n"
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
            "/api/posts/posts/shared/index.md",
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
            "---\ntitle: Shared Post\ncreated_at: 2026-02-01 00:00:00+00\nauthor: admin\n"
            "labels:\n- '#a'\n- '#client-label'\n---\n\nParagraph one.\n\nParagraph two.\n"
        )
        metadata = json.dumps({"deleted_files": [], "last_sync_commit": server_commit})
        resp = await merge_client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            files=[
                (
                    "files",
                    (
                        "posts/shared/index.md",
                        io.BytesIO(client_content.encode()),
                        "text/plain",
                    ),
                ),
            ],
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["conflicts"]) == 0

        dl_resp = await merge_client.get(
            "/api/sync/download/posts/shared/index.md",
            headers=headers,
        )
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
            "/api/posts/posts/shared/index.md",
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
            "---\ntitle: Shared Post\ncreated_at: 2026-02-01 00:00:00+00\nauthor: admin\n"
            "labels:\n- '#a'\n---\n\nClient edited paragraph.\n\nParagraph two.\n"
        )

        # Patch merge_post_file to raise CalledProcessError and spy on normalize
        error = subprocess.CalledProcessError(1, "git merge-file", stderr="merge failed")

        with (
            patch("backend.api.sync.merge_post_file", side_effect=error),
            patch(
                "backend.api.sync.normalize_post_frontmatter", return_value=([], [])
            ) as mock_norm,
        ):
            metadata = json.dumps({"deleted_files": [], "last_sync_commit": server_commit})
            resp = await merge_client.post(
                "/api/sync/commit",
                data={"metadata": metadata},
                files=[
                    (
                        "files",
                        (
                            "posts/shared/index.md",
                            io.BytesIO(client_content.encode()),
                            "text/plain",
                        ),
                    ),
                ],
                headers=headers,
            )

        assert resp.status_code == 200
        data = resp.json()

        # Should report the conflict
        assert len(data["conflicts"]) == 1
        assert data["conflicts"][0]["file_path"] == "posts/shared/index.md"
        assert data["conflicts"][0]["body_conflicted"] is True

        # The critical assertion: normalize_post_frontmatter should NOT
        # receive the failed merge path in its uploaded_files list
        mock_norm.assert_called_once()
        uploaded_files_arg = mock_norm.call_args.kwargs.get(
            "uploaded_files", mock_norm.call_args.args[0] if mock_norm.call_args.args else []
        )
        assert "posts/shared/index.md" not in uploaded_files_arg


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
        new_content = b"---\ntitle: Round Trip Post\nauthor: admin\n---\n\nOriginal content.\n"
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


class TestSyncCommitRollback:
    """When a file write fails during sync commit, all previously written files
    must be restored to their pre-sync state."""

    async def test_write_failure_rolls_back_new_files(
        self, merge_client: AsyncClient, merge_settings: Settings
    ) -> None:
        """Upload two new files; second write fails.  The first (successfully
        written) file must be removed by rollback."""
        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}
        content_dir = merge_settings.content_dir

        first_content = b"---\ntitle: First Post\nauthor: admin\n---\nFirst body.\n"
        fail_content = b"---\ntitle: Fail Post\n---\nBody.\n"
        metadata = json.dumps({"deleted_files": [], "last_sync_commit": None})

        _orig_write_text = pathlib.Path.write_text

        def write_that_fails(
            self: pathlib.Path,
            data: str,
            encoding: str | None = None,
            errors: str | None = None,
            newline: str | None = None,
        ) -> None:
            if str(self).endswith("posts/fail-post/index.md"):
                raise OSError("Simulated disk failure")
            _orig_write_text(self, data, encoding=encoding, errors=errors, newline=newline)

        with patch.object(pathlib.Path, "write_text", write_that_fails):
            resp = await merge_client.post(
                "/api/sync/commit",
                data={"metadata": metadata},
                files=[
                    (
                        "files",
                        (
                            "posts/first-post/index.md",
                            io.BytesIO(first_content),
                            "text/plain",
                        ),
                    ),
                    (
                        "files",
                        (
                            "posts/fail-post/index.md",
                            io.BytesIO(fail_content),
                            "text/plain",
                        ),
                    ),
                ],
                headers=headers,
            )

        assert resp.status_code == 500

        # Rollback must remove the first file that was successfully written
        assert not (content_dir / "posts/first-post/index.md").exists()

    async def test_non_http_exception_triggers_rollback(
        self, merge_client: AsyncClient, merge_settings: Settings
    ) -> None:
        """A non-HTTPException (e.g. subprocess.TimeoutExpired from _get_base_content)
        during the mutation phase must trigger rollback and return HTTP 500, not
        propagate as an unhandled exception crashing the server."""
        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}
        content_dir = merge_settings.content_dir

        metadata = json.dumps({"deleted_files": [], "last_sync_commit": None})

        # Write the first file to disk so the server sees it as an existing file
        # and tries to do a three-way merge for the second upload (triggering _get_base_content)
        existing_dir = content_dir / "posts" / "good-post"
        existing_dir.mkdir(parents=True, exist_ok=True)
        (existing_dir / "index.md").write_text(
            "---\ntitle: Good Post\nauthor: admin\ncreated_at: 2026-01-01 00:00:00+00\n"
            "---\nOriginal body.\n",
            encoding="utf-8",
        )

        new_content = b"---\ntitle: Good Post\nauthor: admin\n---\nUpdated body.\n"
        fail_new_content = b"---\ntitle: Fail Post\nauthor: admin\n---\nBad body.\n"

        # The second file is new, and the first file is modified - when we patch
        # _get_base_content to raise TimeoutExpired (which is NOT caught by except HTTPException),
        # the mutation phase will raise a non-HTTP exception.
        timeout_error = subprocess.TimeoutExpired(cmd="git show", timeout=5.0)

        with patch("backend.api.sync._get_base_content", side_effect=timeout_error):
            resp = await merge_client.post(
                "/api/sync/commit",
                data={"metadata": metadata},
                files=[
                    (
                        "files",
                        (
                            "posts/good-post/index.md",
                            io.BytesIO(new_content),
                            "text/plain",
                        ),
                    ),
                    (
                        "files",
                        (
                            "posts/new-fail-post/index.md",
                            io.BytesIO(fail_new_content),
                            "text/plain",
                        ),
                    ),
                ],
                headers=headers,
            )

        # Must return 500, not crash the server (5xx family)
        assert resp.status_code == 500

        # Rollback must restore good-post/index.md to its original content
        existing_file = content_dir / "posts/good-post/index.md"
        assert existing_file.exists(), "Pre-existing file must still exist after rollback"
        restored = existing_file.read_text(encoding="utf-8")
        assert "Original body." in restored, (
            "Pre-existing file must be restored to original content"
        )

    async def test_rollback_restores_pre_existing_file_content(
        self, merge_client: AsyncClient, merge_settings: Settings
    ) -> None:
        """When the first upload overwrites an existing file but the second write
        fails, rollback must restore the first file to its ORIGINAL content (not
        delete it, since it existed before the sync)."""
        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}
        content_dir = merge_settings.content_dir

        # Create a pre-existing post that will be overwritten in the first upload
        existing_dir = content_dir / "posts" / "existing-post"
        existing_dir.mkdir(parents=True, exist_ok=True)
        original_content = (
            "---\ntitle: Existing Post\nauthor: admin\n"
            "created_at: 2026-01-01 00:00:00+00\n---\nOriginal content.\n"
        )
        (existing_dir / "index.md").write_text(original_content, encoding="utf-8")

        overwrite_content = b"---\ntitle: Existing Post\nauthor: admin\n---\nOverwritten content.\n"
        fail_content = b"---\ntitle: Fail Post\nauthor: admin\n---\nBody.\n"
        metadata = json.dumps({"deleted_files": [], "last_sync_commit": None})

        _orig_write_text = pathlib.Path.write_text

        def write_that_fails_on_second(
            self: pathlib.Path,
            data: str,
            encoding: str | None = None,
            errors: str | None = None,
            newline: str | None = None,
        ) -> None:
            if str(self).endswith("posts/new-fail-post/index.md"):
                raise OSError("Simulated disk failure on new post")
            _orig_write_text(self, data, encoding=encoding, errors=errors, newline=newline)

        with patch.object(pathlib.Path, "write_text", write_that_fails_on_second):
            resp = await merge_client.post(
                "/api/sync/commit",
                data={"metadata": metadata},
                files=[
                    (
                        "files",
                        (
                            "posts/existing-post/index.md",
                            io.BytesIO(overwrite_content),
                            "text/plain",
                        ),
                    ),
                    (
                        "files",
                        (
                            "posts/new-fail-post/index.md",
                            io.BytesIO(fail_content),
                            "text/plain",
                        ),
                    ),
                ],
                headers=headers,
            )

        assert resp.status_code == 500

        # The pre-existing file must be restored to its ORIGINAL content, not deleted
        existing_file = content_dir / "posts/existing-post/index.md"
        assert existing_file.exists(), "Pre-existing file must still exist after rollback"
        restored_content = existing_file.read_text(encoding="utf-8")
        assert "Original content." in restored_content, (
            "Pre-existing file must be restored to original content, not overwritten content"
        )

    async def test_read_text_oserror_returns_500_without_silent_overwrite(
        self, merge_client: AsyncClient, merge_settings: Settings
    ) -> None:
        """OSError from read_text when reading server content must return HTTP 500,
        not silently treat server content as absent (which would cause data loss)."""
        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        # Use the pre-existing shared post from the fixture
        client_content = (
            b"---\ntitle: Shared Post\nauthor: admin\n"
            b"created_at: 2026-02-01 00:00:00+00\n---\nClient version.\n"
        )
        metadata = json.dumps({"deleted_files": [], "last_sync_commit": None})

        _orig_read_text = pathlib.Path.read_text

        def read_text_that_raises(
            self: pathlib.Path,
            encoding: str | None = None,
            errors: str | None = None,
        ) -> str:
            if str(self).endswith("posts/shared/index.md"):
                raise OSError("Permission denied reading server file")
            return _orig_read_text(self, encoding=encoding, errors=errors)

        with patch.object(pathlib.Path, "read_text", read_text_that_raises):
            resp = await merge_client.post(
                "/api/sync/commit",
                data={"metadata": metadata},
                files=[
                    (
                        "files",
                        (
                            "posts/shared/index.md",
                            io.BytesIO(client_content),
                            "text/plain",
                        ),
                    ),
                ],
                headers=headers,
            )

        # Must return 500, not silently overwrite the server file
        assert resp.status_code == 500


class TestSyncDeletePrunesDirectories:
    """Deleting a post via sync should also remove empty parent directories."""

    async def test_delete_prunes_empty_parent_directory(
        self, merge_client: AsyncClient, merge_settings: Settings
    ) -> None:
        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}
        content_dir = merge_settings.content_dir

        # Create a post to be deleted
        post_dir = content_dir / "posts" / "deleteme"
        post_dir.mkdir(parents=True, exist_ok=True)
        (post_dir / "index.md").write_text("---\ntitle: Delete Me\n---\nBody.\n", encoding="utf-8")

        metadata = json.dumps({"deleted_files": ["posts/deleteme/index.md"]})
        resp = await merge_client.post(
            "/api/sync/commit",
            data={"metadata": metadata},
            headers=headers,
        )
        assert resp.status_code == 200

        # File must be deleted
        assert not (post_dir / "index.md").exists()
        # Empty parent directory must also be pruned
        assert not post_dir.exists()
        # But the posts/ directory should still exist (it has other content)
        assert (content_dir / "posts").exists()


class TestGetBaseContentGitErrors:
    """When commit_exists raises OSError, sync degrades gracefully with a warning."""

    async def test_commit_exists_oserror_returns_200(
        self, merge_client: AsyncClient
    ) -> None:
        """Sync returns 200 (not 500) when commit_exists raises OSError."""
        from backend.services.git_service import GitService

        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        with patch.object(
            GitService,
            "commit_exists",
            new_callable=AsyncMock,
            side_effect=OSError("permission denied"),
        ):
            resp = await merge_client.post(
                "/api/sync/commit",
                data={
                    "metadata": json.dumps({
                        "deleted_files": [],
                        "last_sync_commit": "a" * 40,
                        "files": [],
                    })
                },
                headers=headers,
            )

        assert resp.status_code == 200

    async def test_commit_exists_oserror_during_merge_adds_warning(
        self, merge_client: AsyncClient, merge_settings: Settings
    ) -> None:
        """When commit_exists raises OSError during a merge, a sync warning is added."""
        from backend.services.git_service import GitService

        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        # The fixture creates posts/shared/index.md — client sends a different version
        # to trigger the three-way merge code path
        client_content = (
            "---\ntitle: Shared Post\ncreated_at: 2026-02-01 00:00:00+00\nauthor: admin\n"
            "labels:\n- '#a'\n---\n\nClient edited body.\n"
        )
        checksum = hashlib.sha256(client_content.encode()).hexdigest()
        file_path = "posts/shared/index.md"
        metadata = {
            "deleted_files": [],
            "last_sync_commit": "a" * 40,
            "files": [{"path": file_path, "checksum": checksum}],
        }

        with patch.object(
            GitService,
            "commit_exists",
            new_callable=AsyncMock,
            side_effect=OSError("permission denied"),
        ):
            resp = await merge_client.post(
                "/api/sync/commit",
                data={"metadata": json.dumps(metadata)},
                files=[
                    (
                        "files",
                        (
                            "posts/shared/index.md",
                            io.BytesIO(client_content.encode()),
                            "text/plain",
                        ),
                    ),
                ],
                headers=headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert any(
            "merge base" in w.lower() or "three-way" in w.lower()
            for w in data.get("warnings", [])
        ), f"Expected merge base warning; got: {data.get('warnings')}"


class TestLabelsTomlParseErrorSentinel:
    """_parse_error sentinel must not appear in the API response field_conflicts."""

    async def test_parse_error_sentinel_not_in_api_response(
        self, merge_client: AsyncClient, merge_settings: Settings
    ) -> None:
        """When labels.toml merge returns _parse_error, it must not appear in conflicts."""
        from backend.services.sync_service import LabelsMergeResult

        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        # Write a server-side labels.toml so the merge branch is triggered
        content_dir = merge_settings.content_dir
        (content_dir / "labels.toml").write_text(
            "[labels]\n[labels.foo]\nnames = ['foo']\n", encoding="utf-8"
        )
        client_labels = "[labels]\n[labels.bar]\nnames = ['bar']\n"

        with patch(
            "backend.api.sync.merge_labels_toml",
            return_value=LabelsMergeResult(
                merged_content="[labels]\n", field_conflicts=["_parse_error"]
            ),
        ):
            resp = await merge_client.post(
                "/api/sync/commit",
                data={"metadata": json.dumps({"deleted_files": [], "last_sync_commit": None})},
                files=[
                    (
                        "files",
                        ("labels.toml", io.BytesIO(client_labels.encode()), "text/plain"),
                    ),
                ],
                headers=headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        for conflict in data.get("conflicts", []):
            assert "_parse_error" not in conflict.get("field_conflicts", []), (
                "_parse_error is an internal sentinel and must not appear in API response"
            )

    async def test_parse_error_adds_sync_warning(
        self, merge_client: AsyncClient, merge_settings: Settings
    ) -> None:
        """When _parse_error occurs, a human-readable warning appears in the response."""
        from backend.services.sync_service import LabelsMergeResult

        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        # Write a server-side labels.toml so the merge branch is triggered
        content_dir = merge_settings.content_dir
        (content_dir / "labels.toml").write_text(
            "[labels]\n[labels.foo]\nnames = ['foo']\n", encoding="utf-8"
        )
        client_labels = "[labels]\n[labels.bar]\nnames = ['bar']\n"

        with patch(
            "backend.api.sync.merge_labels_toml",
            return_value=LabelsMergeResult(
                merged_content="[labels]\n", field_conflicts=["_parse_error"]
            ),
        ):
            resp = await merge_client.post(
                "/api/sync/commit",
                data={"metadata": json.dumps({"deleted_files": [], "last_sync_commit": None})},
                files=[
                    (
                        "files",
                        ("labels.toml", io.BytesIO(client_labels.encode()), "text/plain"),
                    ),
                ],
                headers=headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert any(
            "labels" in w.lower() and ("parse" in w.lower() or "corrupt" in w.lower())
            for w in data.get("warnings", [])
        ), f"Expected labels parse warning; got warnings: {data.get('warnings')}"
