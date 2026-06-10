"""Text processing utilities."""

from __future__ import annotations

import re

_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def _strip_fenced_code(body: str) -> str:
    """Remove Pandoc-style backtick and tilde fenced code blocks."""
    stripped: list[str] = []
    fence_char: str | None = None
    fence_length = 0

    for line in body.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        if fence_char is None:
            match = _FENCE_OPEN_RE.match(content)
            if match is None:
                stripped.append(line)
                continue

            marker, info = match.groups()
            if marker[0] == "`" and "`" in info:
                stripped.append(line)
                continue
            fence_char = marker[0]
            fence_length = len(marker)
            stripped.append("\n")
            continue

        candidate = content.lstrip(" ")
        indentation = len(content) - len(candidate)
        marker_length = len(candidate) - len(candidate.lstrip(fence_char))
        if (
            indentation <= 3
            and marker_length >= fence_length
            and candidate[marker_length:].strip() == ""
        ):
            fence_char = None
            fence_length = 0
            stripped.append("\n")

    return "".join(stripped)


def _is_escaped(body: str, position: int) -> bool:
    backslashes = 0
    position -= 1
    while position >= 0 and body[position] == "\\":
        backslashes += 1
        position -= 1
    return backslashes % 2 == 1


def _strip_inline_code(body: str) -> str:
    """Remove backtick code spans while preserving unmatched delimiters."""
    stripped: list[str] = []
    text_start = 0
    position = 0

    while position < len(body):
        if body[position] != "`" or _is_escaped(body, position):
            position += 1
            continue

        delimiter_end = position + 1
        while delimiter_end < len(body) and body[delimiter_end] == "`":
            delimiter_end += 1
        delimiter_length = delimiter_end - position

        close = delimiter_end
        while close < len(body):
            close = body.find("`", close)
            if close == -1:
                break
            close_end = close + 1
            while close_end < len(body) and body[close_end] == "`":
                close_end += 1
            if close_end - close == delimiter_length:
                stripped.append(body[text_start:position])
                stripped.append(" ")
                position = close_end
                text_start = close_end
                break
            close = close_end
        else:
            close = -1

        if close == -1:
            position = delimiter_end

    stripped.append(body[text_start:])
    return "".join(stripped)


def count_words(body: str) -> int:
    """Count prose words in a markdown body.

    Strips fenced code blocks and inline code before counting so that
    code tokens do not inflate the reading-time estimate.
    """
    body = _strip_fenced_code(body)
    body = _strip_inline_code(body)
    return len(body.split())
