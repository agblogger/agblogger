"""Tests for application configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from backend.config import Settings


class TestSettings:
    def test_default_settings(self) -> None:
        s = Settings(_env_file=None)
        assert s.secret_key == "change-me-in-production"
        assert s.debug is False
        assert s.port == 8000

    def test_custom_settings(self, tmp_path: Path) -> None:
        s = Settings(
            secret_key="my-secret",
            debug=True,
            content_dir=tmp_path / "content",
            database_url="sqlite+aiosqlite:///test.db",
        )
        assert s.secret_key == "my-secret"
        assert s.debug is True
        assert s.content_dir == tmp_path / "content"

    def test_settings_from_fixture(self, test_settings: Settings) -> None:
        assert test_settings.secret_key == "test-secret-key-with-at-least-32-characters"
        assert test_settings.debug is True
        assert test_settings.content_dir.exists()


class TestCrosspostSettings:
    def test_x_settings_default_empty(self, tmp_path: Path) -> None:
        settings = Settings(secret_key="x" * 32, content_dir=tmp_path)
        assert settings.x_client_id == ""
        assert settings.x_client_secret == ""

    def test_facebook_settings_default_empty(self, tmp_path: Path) -> None:
        settings = Settings(secret_key="x" * 32, content_dir=tmp_path)
        assert settings.facebook_app_id == ""
        assert settings.facebook_app_secret == ""
