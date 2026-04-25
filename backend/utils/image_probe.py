"""Probe image dimensions and MIME type from file headers.

Lightweight zero-dependency reader for the formats AgBlogger accepts as
og:image: PNG, JPEG, GIF, WEBP. Used by the SEO service to emit
``og:image:width``, ``og:image:height``, and ``og:image:type`` so social
preview scrapers (notably Facebook) don't need to download and process
the full image just to find its dimensions.
"""

from __future__ import annotations

import logging
import struct
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class ImageInfo(NamedTuple):
    width: int
    height: int
    mime_type: str


def probe_image_file(path: Path) -> ImageInfo | None:
    """Read enough of the file to extract (width, height, mime_type).

    Returns ``None`` for unrecognized or malformed files so the caller can
    silently fall back to omitting the dimension hints.
    """
    try:
        with path.open("rb") as fh:
            header = fh.read(64)
            if len(header) < 24:
                return None
            info = _parse_known_format(header, fh)
    except OSError:
        logger.debug("Could not read image file for dimension probe: %s", path, exc_info=True)
        return None
    return info


def _parse_known_format(header: bytes, fh) -> ImageInfo | None:  # type: ignore[no-untyped-def]
    if header[:8] == b"\x89PNG\r\n\x1a\n":
        return _parse_png(header)
    if header[:3] == b"GIF":
        return _parse_gif(header)
    if header[:2] == b"\xff\xd8":
        return _parse_jpeg(fh)
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return _parse_webp(header, fh)
    return None


def _parse_png(header: bytes) -> ImageInfo | None:
    # IHDR chunk starts at byte 8; width/height are big-endian uint32 at offsets 16, 20.
    if len(header) < 24 or header[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", header[16:24])
    return ImageInfo(width, height, "image/png")


def _parse_gif(header: bytes) -> ImageInfo | None:
    # GIF87a / GIF89a — width and height are little-endian uint16 at offsets 6, 8.
    if header[3:6] not in (b"87a", b"89a") or len(header) < 10:
        return None
    width, height = struct.unpack("<HH", header[6:10])
    return ImageInfo(width, height, "image/gif")


def _parse_webp(header: bytes, fh) -> ImageInfo | None:  # type: ignore[no-untyped-def]
    # WEBP wraps a VP8/VP8L/VP8X chunk inside a RIFF container.  The chunk
    # header is at offset 12; dimensions live at format-specific offsets.
    if len(header) < 30:
        return None
    chunk = header[12:16]
    if chunk == b"VP8 ":
        # Lossy VP8: 14-bit width/height with scale, at offsets 26, 28.
        width = struct.unpack("<H", header[26:28])[0] & 0x3FFF
        height = struct.unpack("<H", header[28:30])[0] & 0x3FFF
        return ImageInfo(width, height, "image/webp")
    if chunk == b"VP8L":
        # Lossless VP8L: 14-bit width-1 / height-1 packed at offsets 21..24.
        b0, b1, b2, b3 = header[21], header[22], header[23], header[24]
        width = ((b1 & 0x3F) << 8 | b0) + 1
        height = ((b3 & 0x0F) << 10 | b2 << 2 | (b1 & 0xC0) >> 6) + 1
        return ImageInfo(width, height, "image/webp")
    if chunk == b"VP8X":
        # Extended VP8X: 24-bit width-1 / height-1 packed at offsets 24..29.
        width = (header[24] | header[25] << 8 | header[26] << 16) + 1
        height = (header[27] | header[28] << 8 | header[29] << 16) + 1
        return ImageInfo(width, height, "image/webp")
    return None


def _parse_jpeg(fh) -> ImageInfo | None:  # type: ignore[no-untyped-def]
    # Walk JPEG segments until we hit a Start-Of-Frame marker (SOF0..SOF15
    # except DHT=C4, JPG=C8, DAC=CC). Bail out on EOF or malformed segment.
    fh.seek(2)
    while True:
        marker = fh.read(2)
        if len(marker) < 2 or marker[0] != 0xFF:
            return None
        code = marker[1]
        sof = code not in (0xC4, 0xC8, 0xCC) and 0xC0 <= code <= 0xCF
        length_bytes = fh.read(2)
        if len(length_bytes) < 2:
            return None
        (segment_length,) = struct.unpack(">H", length_bytes)
        if segment_length < 2:
            return None
        if sof:
            payload = fh.read(5)
            if len(payload) < 5:
                return None
            height, width = struct.unpack(">HH", payload[1:5])
            return ImageInfo(width, height, "image/jpeg")
        fh.seek(segment_length - 2, 1)
