"""Tests for TOML manager read/write roundtrip and error resilience."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.filesystem.toml_manager import (
    PageConfig,
    SiteConfig,
    parse_labels_config,
    parse_site_config,
    write_site_config,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_write_site_config_roundtrip(tmp_path: Path) -> None:
    config = SiteConfig(
        title="My Test Blog",
        description="A test blog",
        timezone="America/New_York",
        pages=[
            PageConfig(id="timeline", title="Posts"),
            PageConfig(id="about", title="About", file="about.md"),
            PageConfig(id="labels", title="Tags"),
        ],
    )
    (tmp_path / "index.toml").write_text("[site]\n")

    write_site_config(tmp_path, config)
    result = parse_site_config(tmp_path)

    assert result.title == "My Test Blog"
    assert result.description == "A test blog"
    assert result.timezone == "America/New_York"
    assert len(result.pages) == 3
    assert result.pages[0].id == "timeline"
    assert result.pages[1].id == "about"
    assert result.pages[1].file == "about.md"
    assert result.pages[2].id == "labels"
    assert result.pages[2].file is None


def test_write_site_config_preserves_pages_without_file(tmp_path: Path) -> None:
    config = SiteConfig(
        title="Blog",
        pages=[
            PageConfig(id="timeline", title="Posts"),
        ],
    )
    (tmp_path / "index.toml").write_text("[site]\n")

    write_site_config(tmp_path, config)
    result = parse_site_config(tmp_path)

    assert result.pages[0].file is None


class TestInvalidTomlResilience:
    def test_corrupted_index_toml_returns_default_config(self, tmp_path: Path) -> None:
        """Invalid TOML in index.toml must not crash; returns safe defaults."""
        (tmp_path / "index.toml").write_text("this is not valid [toml\n!@#$%")
        result = parse_site_config(tmp_path)
        assert result.title == "My Blog"
        assert result.timezone == "UTC"
        assert result.pages == []

    def test_corrupted_labels_toml_returns_empty_dict(self, tmp_path: Path) -> None:
        """Invalid TOML in labels.toml must not crash; returns empty labels."""
        (tmp_path / "labels.toml").write_text("broken = [unclosed\n!@#")
        result = parse_labels_config(tmp_path)
        assert result == {}

    def test_index_toml_page_missing_id_returns_default_config(self, tmp_path: Path) -> None:
        """A page entry missing the 'id' field must not crash."""
        (tmp_path / "index.toml").write_text(
            '[site]\ntitle = "Blog"\n\n[[pages]]\ntitle = "No ID"\n'
        )
        result = parse_site_config(tmp_path)
        assert result.title == "My Blog"
        assert result.pages == []

    def test_empty_timezone_falls_back_to_utc(self, tmp_path: Path) -> None:
        """Empty timezone values must not raise; fallback to UTC."""
        (tmp_path / "index.toml").write_text('[site]\ntitle = "Blog"\ntimezone = ""\n')
        result = parse_site_config(tmp_path)
        assert result.timezone == "UTC"

    def test_non_string_timezone_falls_back_to_utc(self, tmp_path: Path) -> None:
        """Non-string timezone values must not raise; fallback to UTC."""
        (tmp_path / "index.toml").write_text('[site]\ntitle = "Blog"\ntimezone = 42\n')
        result = parse_site_config(tmp_path)
        assert result.timezone == "UTC"
