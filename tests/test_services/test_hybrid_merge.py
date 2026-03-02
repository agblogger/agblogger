"""Tests for hybrid merge: semantic front matter + git merge-file body."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import frontmatter

from backend.services.git_service import GitService
from backend.services.sync_service import PostMergeResult, merge_post_file

if TYPE_CHECKING:
    from pathlib import Path


class TestMergePostFile:
    def _make_post(self, meta: dict[str, Any], body: str) -> str:
        post = frontmatter.Post(body, **meta)
        return frontmatter.dumps(post) + "\n"

    async def test_clean_body_merge(self, tmp_path: Path) -> None:
        git = GitService(tmp_path)
        await git.init_repo()
        meta = {"title": "T", "author": "A", "labels": ["#a"]}
        base = self._make_post(meta, "Para one.\n\nPara two.\n")
        server = self._make_post(meta, "Para one (server).\n\nPara two.\n")
        client = self._make_post(meta, "Para one.\n\nPara two (client).\n")
        result = await merge_post_file(base, server, client, git)
        assert isinstance(result, PostMergeResult)
        assert not result.body_conflicted
        assert result.field_conflicts == []
        parsed = frontmatter.loads(result.merged_content)
        assert "server" in parsed.content
        assert "client" in parsed.content

    async def test_body_conflict_server_wins(self, tmp_path: Path) -> None:
        git = GitService(tmp_path)
        await git.init_repo()
        meta = {"title": "T"}
        base = self._make_post(meta, "original line\n")
        server = self._make_post(meta, "server version\n")
        client = self._make_post(meta, "client version\n")
        result = await merge_post_file(base, server, client, git)
        assert result.body_conflicted
        parsed = frontmatter.loads(result.merged_content)
        assert "server version" in parsed.content

    async def test_labels_merged_as_sets(self, tmp_path: Path) -> None:
        git = GitService(tmp_path)
        await git.init_repo()
        base = self._make_post({"title": "T", "labels": ["#a"]}, "body\n")
        server = self._make_post({"title": "T", "labels": ["#a", "#b"]}, "body\n")
        client = self._make_post({"title": "T", "labels": ["#a", "#c"]}, "body\n")
        result = await merge_post_file(base, server, client, git)
        parsed = frontmatter.loads(result.merged_content)
        assert set(parsed["labels"]) == {"#a", "#b", "#c"}

    async def test_modified_at_stripped(self, tmp_path: Path) -> None:
        git = GitService(tmp_path)
        await git.init_repo()
        base = self._make_post({"title": "T", "modified_at": "2026-01-01"}, "body\n")
        server = self._make_post({"title": "T", "modified_at": "2026-01-02"}, "body\n")
        client = self._make_post({"title": "T", "modified_at": "2026-01-03"}, "body\n")
        result = await merge_post_file(base, server, client, git)
        parsed = frontmatter.loads(result.merged_content)
        assert "modified_at" not in parsed.metadata

    async def test_title_conflict_reported(self, tmp_path: Path) -> None:
        git = GitService(tmp_path)
        await git.init_repo()
        base = self._make_post({"title": "Original"}, "body\n")
        server = self._make_post({"title": "Server Title"}, "body\n")
        client = self._make_post({"title": "Client Title"}, "body\n")
        result = await merge_post_file(base, server, client, git)
        assert "title" in result.field_conflicts
        parsed = frontmatter.loads(result.merged_content)
        assert parsed["title"] == "Server Title"

    async def test_no_base_server_wins(self, tmp_path: Path) -> None:
        git = GitService(tmp_path)
        await git.init_repo()
        server = self._make_post({"title": "Server"}, "server body\n")
        client = self._make_post({"title": "Client"}, "client body\n")
        result = await merge_post_file(None, server, client, git)
        assert result.body_conflicted
        assert "title" in result.field_conflicts
        parsed = frontmatter.loads(result.merged_content)
        assert parsed["title"] == "Server"
        assert "server body" in parsed.content

    async def test_malformed_yaml_in_client_returns_conflict(self, tmp_path: Path) -> None:
        """Malformed YAML front matter should not crash; should return as conflict."""
        git = GitService(tmp_path)
        await git.init_repo()
        server = self._make_post({"title": "Server"}, "body\n")
        malformed_client = "---\ntitle: [unclosed bracket\n---\n\nbody\n"
        result = await merge_post_file(None, server, malformed_client, git)
        # Should not crash; server wins as conflict
        assert result.body_conflicted
        assert result.merged_content == server

    async def test_malformed_yaml_in_server_returns_conflict(self, tmp_path: Path) -> None:
        """Malformed server YAML should not crash."""
        git = GitService(tmp_path)
        await git.init_repo()
        malformed_server = "---\ntitle: {bad yaml\n---\n\nserver body\n"
        client = self._make_post({"title": "Client"}, "client body\n")
        result = await merge_post_file(None, malformed_server, client, git)
        assert result.body_conflicted
        assert result.merged_content == malformed_server
