"""Tests for application configuration."""

from __future__ import annotations

from pathlib import Path

from backend.config import Settings, sqlite_database_path


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

    def test_sqlite_database_path_preserves_absolute_container_paths(self) -> None:
        assert sqlite_database_path("sqlite+aiosqlite:////data/db/agblogger.db") == Path(
            "/data/db/agblogger.db"
        )


class TestSqliteDatabasePath:
    def test_absolute_aiosqlite_url(self) -> None:
        assert sqlite_database_path("sqlite+aiosqlite:////data/db/agblogger.db") == Path(
            "/data/db/agblogger.db"
        )

    def test_absolute_sqlite_url(self) -> None:
        assert sqlite_database_path("sqlite:////data/db/agblogger.db") == Path(
            "/data/db/agblogger.db"
        )

    def test_relative_aiosqlite_url(self) -> None:
        assert sqlite_database_path("sqlite+aiosqlite:///data/db/agblogger.db") == Path(
            "data/db/agblogger.db"
        )

    def test_relative_sqlite_url(self) -> None:
        assert sqlite_database_path("sqlite:///data/db/agblogger.db") == Path(
            "data/db/agblogger.db"
        )

    def test_non_sqlite_url_returns_none(self) -> None:
        assert sqlite_database_path("postgresql://localhost/db") is None

    def test_empty_string_returns_none(self) -> None:
        assert sqlite_database_path("") is None

    def test_simple_filename(self) -> None:
        assert sqlite_database_path("sqlite+aiosqlite:///test.db") == Path("test.db")


class TestCrosspostSettings:
    def test_x_settings_default_empty(self, tmp_path: Path) -> None:
        settings = Settings(secret_key="x" * 32, content_dir=tmp_path)
        assert settings.x_client_id == ""
        assert settings.x_client_secret == ""

    def test_facebook_settings_default_empty(self, tmp_path: Path) -> None:
        settings = Settings(secret_key="x" * 32, content_dir=tmp_path)
        assert settings.facebook_app_id == ""
        assert settings.facebook_app_secret == ""

    def test_atproto_oauth_key_path_uses_private_dir_outside_content(self, tmp_path: Path) -> None:
        content_dir = tmp_path / "content"
        db_path = tmp_path / "db" / "agblogger.db"
        settings = Settings(
            secret_key="x" * 32,
            content_dir=content_dir,
            database_url=f"sqlite+aiosqlite:///{db_path}",
        )

        key_path = settings.atproto_oauth_key_path()

        assert key_path == tmp_path / "db" / ".agblogger-secrets" / "atproto-oauth-key.json"
        assert not key_path.is_relative_to(content_dir)
