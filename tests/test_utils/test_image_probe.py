"""Tests for the lightweight image-header probe."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from backend.utils.image_probe import probe_image_file

if TYPE_CHECKING:
    from pathlib import Path


def _png_bytes(width: int, height: int) -> bytes:
    # Minimal-but-valid PNG: 8-byte signature + IHDR chunk header (length=13,
    # type=IHDR, then 13 bytes of IHDR data starting with width/height).
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x06\x00\x00\x00"
        + b"\x00" * 32
    )


def _gif_bytes(width: int, height: int) -> bytes:
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00" * 32


def _jpeg_bytes(width: int, height: int) -> bytes:
    # SOI + APP0 (skipped) + SOF0 with width/height + EOI.
    return (
        b"\xff\xd8"
        + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xc0\x00\x11\x08"
        + struct.pack(">HH", height, width)
        + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
        + b"\xff\xd9"
    )


def _webp_vp8x_bytes(width: int, height: int) -> bytes:
    # RIFF / WEBP / VP8X header with 24-bit width-1 / height-1.
    w_minus_1 = width - 1
    h_minus_1 = height - 1
    body = (
        b"VP8X"
        + struct.pack("<I", 10)
        + b"\x00\x00\x00\x00"
        + bytes(
            [
                w_minus_1 & 0xFF,
                (w_minus_1 >> 8) & 0xFF,
                (w_minus_1 >> 16) & 0xFF,
                h_minus_1 & 0xFF,
                (h_minus_1 >> 8) & 0xFF,
                (h_minus_1 >> 16) & 0xFF,
            ]
        )
    )
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + body + b"\x00" * 16


class TestProbeImageFile:
    def test_png_returns_dimensions(self, tmp_path: Path) -> None:
        path = tmp_path / "x.png"
        path.write_bytes(_png_bytes(2876, 1640))
        info = probe_image_file(path)
        assert info is not None
        assert info.width == 2876
        assert info.height == 1640
        assert info.mime_type == "image/png"

    def test_gif_returns_dimensions(self, tmp_path: Path) -> None:
        path = tmp_path / "x.gif"
        path.write_bytes(_gif_bytes(120, 80))
        info = probe_image_file(path)
        assert info is not None
        assert info.width == 120
        assert info.height == 80
        assert info.mime_type == "image/gif"

    def test_jpeg_returns_dimensions(self, tmp_path: Path) -> None:
        path = tmp_path / "x.jpg"
        path.write_bytes(_jpeg_bytes(640, 480))
        info = probe_image_file(path)
        assert info is not None
        assert info.width == 640
        assert info.height == 480
        assert info.mime_type == "image/jpeg"

    def test_webp_vp8x_returns_dimensions(self, tmp_path: Path) -> None:
        path = tmp_path / "x.webp"
        path.write_bytes(_webp_vp8x_bytes(1024, 768))
        info = probe_image_file(path)
        assert info is not None
        assert info.width == 1024
        assert info.height == 768
        assert info.mime_type == "image/webp"

    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        assert probe_image_file(tmp_path / "nope.png") is None

    def test_returns_none_for_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.png"
        path.write_bytes(b"")
        assert probe_image_file(path) is None

    def test_returns_none_for_unknown_format(self, tmp_path: Path) -> None:
        path = tmp_path / "x.txt"
        path.write_bytes(b"this is not an image at all, just plain text content here.")
        assert probe_image_file(path) is None

    def test_returns_none_for_truncated_png(self, tmp_path: Path) -> None:
        path = tmp_path / "trunc.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 4)
        assert probe_image_file(path) is None
