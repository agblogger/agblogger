# backend/pandoc/sentinel.py
"""Scroll-sync sentinel injection for the preview render path."""

from __future__ import annotations

import re

_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")


def _split_markdown_blocks(markdown: str) -> list[int]:
    """Return the starting source line number of each top-level markdown block.

    Only fenced code blocks are tracked specially — blank lines inside a fence
    are not treated as block boundaries. Loose lists, blockquotes, and other
    constructs are not tracked; their blank-line boundaries produce extra block
    entries which are naturally truncated when zipped against HTML elements.
    """
    if not markdown.strip():
        return []

    lines = markdown.split("\n")
    block_lines: list[int] = []
    in_fence = False
    fence_char = ""
    fence_len = 0
    in_gap = True  # treat start-of-file as a gap so the first line starts a block

    for i, line in enumerate(lines):
        was_in_fence = in_fence

        if not in_fence:
            m = _FENCE_RE.match(line)
            if m:
                in_fence = True
                fence_char = m.group(1)[0]
                fence_len = len(m.group(1))
        else:
            m = _FENCE_RE.match(line)
            if (
                m
                and m.group(1)[0] == fence_char
                and len(m.group(1)) >= fence_len
                and not line[len(m.group(1)) :].strip()
            ):
                in_fence = False
                fence_char = ""
                fence_len = 0

        is_blank = not line.strip()

        if not was_in_fence and in_gap and not is_blank:
            block_lines.append(i)
            in_gap = False
        elif not in_fence and is_blank:
            in_gap = True

    return block_lines
