"""Scroll-sync sentinel injection for the preview render path."""

from __future__ import annotations

import re
from html.parser import HTMLParser

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


_TOP_LEVEL_BLOCK_TAGS: frozenset[str] = frozenset({
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "pre", "ul", "ol", "blockquote", "table",
    "figure", "div", "details", "section",
})
_VOID_TAGS: frozenset[str] = frozenset({"br", "hr", "img", "input"})


def _build_line_offsets(text: str) -> list[int]:
    """Return char offset of each line start (result[i] = offset of line i+1)."""
    offsets = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            offsets.append(i + 1)
    return offsets


class _BlockTagFinder(HTMLParser):
    """Collect character offsets of top-level block element start tags."""

    def __init__(self, line_offsets: list[int]) -> None:
        super().__init__(convert_charrefs=False)
        self._line_offsets = line_offsets
        self._depth = 0
        self.offsets: list[int] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if self._depth == 0 and tag_lower in _TOP_LEVEL_BLOCK_TAGS:
            line, col = self.getpos()
            self.offsets.append(self._line_offsets[line - 1] + col)
        if tag_lower not in _VOID_TAGS:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() not in _VOID_TAGS:
            self._depth = max(0, self._depth - 1)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if self._depth == 0 and tag_lower in _TOP_LEVEL_BLOCK_TAGS:
            line, col = self.getpos()
            self.offsets.append(self._line_offsets[line - 1] + col)
        # self-closing: depth unchanged


def _inject_sentinels_into_html(html: str, block_lines: list[int]) -> str:
    """Insert <span id="agbpos-L{n}"> before each top-level block element.

    Pairs the Nth top-level HTML block with the Nth source line number.
    Truncates to the shorter of the two sequences so count mismatches
    (e.g. loose lists = 1 HTML element but 2 source blocks) are handled
    gracefully — later elements simply don't receive sentinels.
    """
    if not html or not block_lines:
        return html

    line_offsets = _build_line_offsets(html)
    finder = _BlockTagFinder(line_offsets)
    finder.feed(html)
    finder.close()

    parts: list[str] = []
    prev = 0
    for offset, line_no in zip(finder.offsets, block_lines, strict=False):
        parts.append(html[prev:offset])
        parts.append(f'<span id="agbpos-L{line_no}"></span>')
        prev = offset
    parts.append(html[prev:])
    return "".join(parts)
