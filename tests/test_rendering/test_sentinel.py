"""Tests for scroll-sync sentinel injection."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from backend.pandoc.sentinel import _split_markdown_blocks


class TestSplitMarkdownBlocks:
    def test_empty_string(self) -> None:
        assert _split_markdown_blocks("") == []

    def test_blank_only(self) -> None:
        assert _split_markdown_blocks("\n\n\n") == []

    def test_single_paragraph(self) -> None:
        assert _split_markdown_blocks("Hello world.") == [0]

    def test_two_paragraphs(self) -> None:
        md = "First paragraph.\n\nSecond paragraph."
        assert _split_markdown_blocks(md) == [0, 2]

    def test_three_paragraphs(self) -> None:
        md = "One.\n\nTwo.\n\nThree."
        assert _split_markdown_blocks(md) == [0, 2, 4]

    def test_multiple_blank_lines_between(self) -> None:
        md = "One.\n\n\n\nTwo."
        assert _split_markdown_blocks(md) == [0, 4]

    def test_heading_is_a_block(self) -> None:
        md = "## Heading\n\nParagraph."
        assert _split_markdown_blocks(md) == [0, 2]

    def test_fence_not_split_on_internal_blank(self) -> None:
        md = "Before.\n\n```\ncode\n\nmore code\n```\n\nAfter."
        # blocks: 'Before.' at 0, fence block at 2, 'After.' at 8
        assert _split_markdown_blocks(md) == [0, 2, 8]

    def test_tilde_fence_not_split(self) -> None:
        md = "Before.\n\n~~~\ncode\n\nmore\n~~~\n\nAfter."
        assert _split_markdown_blocks(md) == [0, 2, 8]

    def test_fence_with_info_string(self) -> None:
        md = "Before.\n\n```python\ncode\n\nmore\n```\n\nAfter."
        assert _split_markdown_blocks(md) == [0, 2, 8]

    def test_longer_closing_fence_allowed(self) -> None:
        # Opening ``` can be closed by ```` (longer is fine)
        md = "```\ncode\n\nmore\n````\n\nAfter."
        assert _split_markdown_blocks(md) == [0, 6]

    def test_fence_character_must_match(self) -> None:
        # ``` opened, ~~~ does NOT close it
        md = "```\ncode\n\nmore\n~~~\n\nstill inside\n```\n\nAfter."
        assert _split_markdown_blocks(md) == [0, 9]

    @given(st.text(min_size=0, max_size=300))
    @settings(max_examples=200)
    def test_all_returned_line_numbers_point_to_non_blank_lines(self, markdown: str) -> None:
        lines = markdown.split("\n")
        for line_no in _split_markdown_blocks(markdown):
            assert 0 <= line_no < len(lines)
            assert lines[line_no].strip() != ""

    @given(st.text(min_size=0, max_size=300))
    @settings(max_examples=200)
    def test_line_numbers_are_strictly_increasing(self, markdown: str) -> None:
        result = _split_markdown_blocks(markdown)
        assert result == sorted(set(result))
