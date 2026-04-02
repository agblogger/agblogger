"""Tests for CLI managed sync path filtering."""

from __future__ import annotations

from typing import Any

from cli.sync_client import SyncClient
from tests.test_sync.test_sync_client import _DummyResponse, _RecordingHttpClient


class TestManagedPathFiltering:
    def test_status_excludes_unmanaged_local_files(self, tmp_path: Any) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "about.md").write_text("About\n", encoding="utf-8")
        (content_dir / "notes.txt").write_text("private\n", encoding="utf-8")

        http_client = _RecordingHttpClient(
            responses={
                "/api/sync/status": _DummyResponse(
                    json_data={
                        "to_upload": [],
                        "to_download": [],
                        "to_delete_local": [],
                        "to_delete_remote": [],
                        "conflicts": [],
                        "warnings": [],
                    }
                )
            }
        )
        client = SyncClient("http://example.com", content_dir)
        client.client = http_client  # type: ignore[assignment]

        client.status()

        manifest = http_client.post_calls[0][1]["json"]["client_manifest"]
        manifest_paths = {entry["file_path"] for entry in manifest}
        assert "about.md" in manifest_paths
        assert "notes.txt" not in manifest_paths
