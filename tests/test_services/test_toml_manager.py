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


class TestNonIterableParents:
    """Non-iterable parents value in labels.toml must not crash."""

    def test_integer_parents_skipped_gracefully(self, tmp_path: Path) -> None:
        labels_path = tmp_path / "labels.toml"
        labels_path.write_text(
            '[labels.broken]\nnames = ["broken"]\nparents = 42\n[labels.good]\nnames = ["good"]\n'
        )
        result = parse_labels_config(tmp_path)
        assert result["broken"].parents == []
        assert "good" in result


def test_site_config_favicon_roundtrip(tmp_path: Path) -> None:
    config = SiteConfig(
        title="My Blog",
        favicon="assets/favicon.png",
        pages=[PageConfig(id="timeline", title="Posts")],
    )
    (tmp_path / "index.toml").write_text("[site]\n")

    write_site_config(tmp_path, config)
    result = parse_site_config(tmp_path)

    assert result.favicon == "assets/favicon.png"


def test_site_config_favicon_omitted_when_none(tmp_path: Path) -> None:
    config = SiteConfig(title="My Blog", favicon=None)
    (tmp_path / "index.toml").write_text("[site]\n")

    write_site_config(tmp_path, config)
    raw = (tmp_path / "index.toml").read_bytes()

    assert b"favicon" not in raw
    assert parse_site_config(tmp_path).favicon is None


def test_site_config_with_pages_preserves_favicon(tmp_path: Path) -> None:
    config = SiteConfig(title="Blog", favicon="assets/favicon.ico", pages=[])
    updated = config.with_pages([PageConfig(id="timeline", title="Posts")])

    assert updated.favicon == "assets/favicon.ico"


def test_parse_site_config_favicon_missing_returns_none(tmp_path: Path) -> None:
    (tmp_path / "index.toml").write_text('[site]\ntitle = "Blog"\n')
    result = parse_site_config(tmp_path)
    assert result.favicon is None


def test_parse_site_config_non_string_favicon_returns_none(tmp_path: Path) -> None:
    (tmp_path / "index.toml").write_text('[site]\ntitle = "Blog"\nfavicon = 42\n')
    result = parse_site_config(tmp_path)
    assert result.favicon is None


def test_site_config_image_roundtrip(tmp_path: Path) -> None:
    config = SiteConfig(
        title="My Blog",
        image="assets/image.png",
        pages=[PageConfig(id="timeline", title="Posts")],
    )
    (tmp_path / "index.toml").write_text("[site]\n")

    write_site_config(tmp_path, config)
    raw = (tmp_path / "index.toml").read_text()
    result = parse_site_config(tmp_path)

    assert result.image == "assets/image.png"
    # TOML key must be 'image', not 'og_image'.
    assert "image = " in raw
    assert "og_image" not in raw


def test_site_config_image_omitted_when_none(tmp_path: Path) -> None:
    config = SiteConfig(title="My Blog", image=None)
    (tmp_path / "index.toml").write_text("[site]\n")

    write_site_config(tmp_path, config)
    raw = (tmp_path / "index.toml").read_text()

    assert "image = " not in raw
    assert parse_site_config(tmp_path).image is None


def test_site_config_with_pages_preserves_image(tmp_path: Path) -> None:
    config = SiteConfig(title="Blog", image="assets/image.jpg", pages=[])
    updated = config.with_pages([PageConfig(id="timeline", title="Posts")])

    assert updated.image == "assets/image.jpg"


def test_parse_site_config_image_missing_returns_none(tmp_path: Path) -> None:
    (tmp_path / "index.toml").write_text('[site]\ntitle = "Blog"\n')
    result = parse_site_config(tmp_path)
    assert result.image is None


def test_parse_site_config_non_string_image_returns_none(tmp_path: Path) -> None:
    (tmp_path / "index.toml").write_text('[site]\ntitle = "Blog"\nimage = 42\n')
    result = parse_site_config(tmp_path)
    assert result.image is None


class TestParseSiteConfigAssetPathSafety:
    """parse_site_config must reject traversal-style favicon/image paths."""

    def test_rejects_absolute_image_path(self, tmp_path: Path) -> None:
        (tmp_path / "index.toml").write_text('[site]\ntitle = "Blog"\nimage = "/etc/passwd"\n')
        result = parse_site_config(tmp_path)
        assert result.image is None

    def test_rejects_dotdot_image_path(self, tmp_path: Path) -> None:
        (tmp_path / "index.toml").write_text(
            '[site]\ntitle = "Blog"\nimage = "../../../etc/passwd"\n'
        )
        result = parse_site_config(tmp_path)
        assert result.image is None

    def test_rejects_absolute_favicon_path(self, tmp_path: Path) -> None:
        (tmp_path / "index.toml").write_text('[site]\ntitle = "Blog"\nfavicon = "/etc/shadow"\n')
        result = parse_site_config(tmp_path)
        assert result.favicon is None

    def test_rejects_dotdot_favicon_path(self, tmp_path: Path) -> None:
        (tmp_path / "index.toml").write_text(
            '[site]\ntitle = "Blog"\nfavicon = "assets/../../escape.png"\n'
        )
        result = parse_site_config(tmp_path)
        assert result.favicon is None

    def test_accepts_legitimate_relative_path(self, tmp_path: Path) -> None:
        (tmp_path / "index.toml").write_text(
            '[site]\ntitle = "Blog"\nimage = "assets/image.png"\nfavicon = "assets/favicon.ico"\n'
        )
        result = parse_site_config(tmp_path)
        assert result.image == "assets/image.png"
        assert result.favicon == "assets/favicon.ico"
