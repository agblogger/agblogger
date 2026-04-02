"""Tests for created_at update on draft-to-publish transition."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backend.config import Settings
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient

pytestmark = pytest.mark.slow


@pytest.fixture
def app_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Create settings for publish transition tests."""
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
    """Create test HTTP client with lifespan triggered."""
    async with create_test_client(app_settings) as ac:
        yield ac


async def _login(client: AsyncClient) -> str:
    """Login as admin and return access token."""
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


class TestPublishTransition:
    """Tests for created_at behaviour during draft/publish transitions."""

    @pytest.mark.asyncio
    async def test_publish_updates_created_at(self, client: AsyncClient) -> None:
        """Publishing a draft should update created_at to the publish time."""
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        # Create a draft post
        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Draft To Publish",
                "body": "Content.\n",
                "is_draft": True,
                "labels": [],
            },
            headers=headers,
        )
        assert create_resp.status_code == 201
        created = create_resp.json()
        file_path = created["file_path"]
        original_created_at = created["created_at"]

        # Publish the draft (is_draft=False)
        publish_resp = await client.put(
            f"/api/posts/{file_path}",
            json={
                "title": "Draft To Publish",
                "body": "Content.\n",
                "is_draft": False,
                "labels": [],
            },
            headers=headers,
        )
        assert publish_resp.status_code == 200
        published = publish_resp.json()

        assert published["created_at"] != original_created_at, (
            "created_at should change when a draft is published"
        )

    @pytest.mark.asyncio
    async def test_non_transition_update_preserves_created_at(self, client: AsyncClient) -> None:
        """Updating a published post without changing draft status should preserve created_at."""
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        # Create a published post directly
        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Already Published",
                "body": "Original content.\n",
                "is_draft": False,
                "labels": [],
            },
            headers=headers,
        )
        assert create_resp.status_code == 201
        created = create_resp.json()
        file_path = created["file_path"]
        original_created_at = created["created_at"]

        # Update content without changing draft status
        update_resp = await client.put(
            f"/api/posts/{file_path}",
            json={
                "title": "Already Published",
                "body": "Updated content.\n",
                "is_draft": False,
                "labels": [],
            },
            headers=headers,
        )
        assert update_resp.status_code == 200
        updated = update_resp.json()

        assert updated["created_at"] == original_created_at, (
            "created_at should NOT change when a published post is updated without draft transition"
        )

    @pytest.mark.asyncio
    async def test_redraft_and_republish_updates_created_at(self, client: AsyncClient) -> None:
        """Re-drafting then re-publishing should update created_at on the second publish."""
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        # Create a draft
        create_resp = await client.post(
            "/api/posts",
            json={
                "title": "Redraft Test",
                "body": "Content.\n",
                "is_draft": True,
                "labels": [],
            },
            headers=headers,
        )
        assert create_resp.status_code == 201
        created = create_resp.json()
        file_path = created["file_path"]

        # First publish
        publish1_resp = await client.put(
            f"/api/posts/{file_path}",
            json={
                "title": "Redraft Test",
                "body": "Content.\n",
                "is_draft": False,
                "labels": [],
            },
            headers=headers,
        )
        assert publish1_resp.status_code == 200
        first_publish_created_at = publish1_resp.json()["created_at"]

        # Re-draft
        redraft_resp = await client.put(
            f"/api/posts/{file_path}",
            json={
                "title": "Redraft Test",
                "body": "Revised content.\n",
                "is_draft": True,
                "labels": [],
            },
            headers=headers,
        )
        assert redraft_resp.status_code == 200

        # Re-publish
        publish2_resp = await client.put(
            f"/api/posts/{file_path}",
            json={
                "title": "Redraft Test",
                "body": "Revised content.\n",
                "is_draft": False,
                "labels": [],
            },
            headers=headers,
        )
        assert publish2_resp.status_code == 200
        second_publish_created_at = publish2_resp.json()["created_at"]

        assert second_publish_created_at != first_publish_created_at, (
            "created_at should change on second publish after re-drafting"
        )
