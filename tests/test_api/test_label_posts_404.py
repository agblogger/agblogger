"""Regression test: GET /api/labels/{nonexistent}/posts should return 404."""

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


class TestLabelPosts404:
    async def test_nonexistent_label_posts_returns_404(self, client: AsyncClient) -> None:
        """GET /api/labels/{nonexistent}/posts should return 404, not 200 with empty list."""
        resp = await client.get("/api/labels/nonexistent/posts")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Label not found"
