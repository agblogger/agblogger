"""Unit tests for the og:image URL helpers in backend.main.

Covers _absolutize_url (relative, scheme-relative, absolute, data:, javascript:,
empty) and the _post_image_url priority logic (inline-first, then site fallback).
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from backend.main import _absolutize_url, _post_image_url, _site_image_url


def _make_request(base_url: str = "http://test.example/") -> MagicMock:
    request = MagicMock()
    request.base_url = base_url
    return request


def _make_cm(*, image: str | None) -> MagicMock:
    cm = MagicMock()
    cm.site_config.image = image
    return cm


class TestAbsolutizeUrl:
    @pytest.mark.parametrize(
        ("src", "expected"),
        [
            ("https://cdn.example/img.png", "https://cdn.example/img.png"),
            ("http://cdn.example/img.png", "http://cdn.example/img.png"),
            ("//cdn.example/img.png", "https://cdn.example/img.png"),
            ("/img.png", "http://test.example/img.png"),
            ("cover.png", "http://test.example/cover.png"),
            ("post/x/cover.png", "http://test.example/post/x/cover.png"),
        ],
    )
    def test_absolutizes_supported_inputs(self, src: str, expected: str) -> None:
        assert _absolutize_url(_make_request(), src) == expected

    @pytest.mark.parametrize("src", ["", "   ", "\n\t  "])
    def test_returns_none_for_empty(self, src: str) -> None:
        assert _absolutize_url(_make_request(), src) is None

    @pytest.mark.parametrize(
        "src",
        [
            "data:image/png;base64,AAAA",
            "DATA:image/png;base64,AAAA",
            "javascript:alert(1)",
            "JavaScript:alert(1)",
            "vbscript:msgbox",
        ],
    )
    def test_rejects_unsafe_schemes(self, src: str) -> None:
        assert _absolutize_url(_make_request(), src) is None


class TestPostImageUrl:
    def test_inline_image_takes_priority_over_site_image(self) -> None:
        cm = _make_cm(image="assets/image.png")
        rendered_html = '<p><img src="cover.png" alt="Cover"></p>'
        url, alt = _post_image_url(_make_request(), rendered_html, cm)
        assert url == "http://test.example/cover.png"
        assert alt == "Cover"

    def test_falls_back_to_site_image_when_no_inline(self) -> None:
        cm = _make_cm(image="assets/image.png")
        url, alt = _post_image_url(_make_request(), "<p>no images</p>", cm)
        assert url == "http://test.example/image.png"
        assert alt is None

    def test_falls_back_to_site_image_when_inline_is_unsafe(self) -> None:
        cm = _make_cm(image="assets/image.png")
        rendered_html = '<img src="javascript:alert(1)" alt="x">'
        url, alt = _post_image_url(_make_request(), rendered_html, cm)
        assert url == "http://test.example/image.png"
        assert alt is None

    def test_returns_none_when_no_inline_and_no_site_image(self) -> None:
        cm = _make_cm(image=None)
        url, alt = _post_image_url(_make_request(), None, cm)
        assert url is None
        assert alt is None

    def test_logs_debug_when_inline_image_promoted(self, caplog: pytest.LogCaptureFixture) -> None:
        cm = _make_cm(image="assets/image.png")
        rendered_html = '<img src="cover.png">'
        with caplog.at_level(logging.DEBUG, logger="backend.main"):
            _post_image_url(_make_request(), rendered_html, cm)
        assert any(
            "og:image" in record.message and "cover.png" in record.message
            for record in caplog.records
        )


class TestSiteImageUrl:
    def test_returns_none_when_no_site_image(self) -> None:
        assert _site_image_url(_make_request(), _make_cm(image=None)) is None

    @pytest.mark.parametrize(
        ("rel", "expected"),
        [
            ("assets/image.png", "http://test.example/image.png"),
            ("assets/image.jpg", "http://test.example/image.jpg"),
            ("assets/image.webp", "http://test.example/image.webp"),
            ("assets/image.gif", "http://test.example/image.gif"),
        ],
    )
    def test_serves_known_extensions(self, rel: str, expected: str) -> None:
        assert _site_image_url(_make_request(), _make_cm(image=rel)) == expected

    def test_warns_on_unrecognized_extension(self, caplog: pytest.LogCaptureFixture) -> None:
        cm = _make_cm(image="assets/image.bmp")
        with caplog.at_level(logging.WARNING, logger="backend.main"):
            result = _site_image_url(_make_request(), cm)
        assert result is None
        assert any(
            "image.bmp" in record.message or ".bmp" in record.message for record in caplog.records
        )
