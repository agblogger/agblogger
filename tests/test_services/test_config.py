"""Tests for application configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.config import Settings, parse_human_size, sqlite_database_path


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


class TestMaxContentSize:
    def test_default_is_none(self) -> None:
        s = Settings(_env_file=None)
        assert s.max_content_size is None

    def test_parse_gigabytes(self) -> None:
        assert parse_human_size("2G") == 2 * 1024**3

    def test_parse_megabytes(self) -> None:
        assert parse_human_size("500M") == 500 * 1024**2

    def test_parse_kilobytes(self) -> None:
        assert parse_human_size("10K") == 10 * 1024

    def test_parse_plain_bytes(self) -> None:
        assert parse_human_size("1048576") == 1048576

    def test_case_insensitive_gigabytes(self) -> None:
        assert parse_human_size("1g") == 1024**3

    def test_case_insensitive_megabytes(self) -> None:
        assert parse_human_size("1m") == 1024**2

    def test_case_insensitive_kilobytes(self) -> None:
        assert parse_human_size("1k") == 1024

    def test_zero_rejected(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            parse_human_size("0")

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            parse_human_size("-1M")

    def test_invalid_suffix_rejected(self) -> None:
        with pytest.raises(ValueError, match="suffix"):
            parse_human_size("100X")

    def test_settings_accepts_human_size_string(self) -> None:
        s = Settings(_env_file=None, max_content_size="2G")  # type: ignore[arg-type]
        assert s.max_content_size == 2 * 1024**3

    def test_settings_accepts_plain_int(self) -> None:
        s = Settings(_env_file=None, max_content_size=1024)
        assert s.max_content_size == 1024

    def test_settings_empty_string_treated_as_none(self) -> None:
        s = Settings(_env_file=None, max_content_size="")  # type: ignore[arg-type]
        assert s.max_content_size is None

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid size value"):
            parse_human_size("")

    def test_settings_zero_int_rejected(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            Settings(_env_file=None, max_content_size=0)

    def test_zero_error_message_is_generic(self) -> None:
        """parse_human_size error should say 'Size' not 'max_content_size'."""
        with pytest.raises(ValueError, match=r"^Size must be a positive integer"):
            parse_human_size("0")

    def test_negative_error_message_is_generic(self) -> None:
        with pytest.raises(ValueError, match=r"^Size must be a positive integer"):
            parse_human_size("-5M")
