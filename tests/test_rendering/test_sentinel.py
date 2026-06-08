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


from backend.pandoc.sentinel import _inject_sentinels_into_html


class TestInjectSentinelsIntoHtml:
    def test_basic_two_paragraphs(self) -> None:
        html = "<p>First.</p>\n<p>Second.</p>"
        result = _inject_sentinels_into_html(html, [0, 2])
        assert '<span id="agbpos-L0"></span><p>First.</p>' in result
        assert '<span id="agbpos-L2"></span><p>Second.</p>' in result

    def test_heading_gets_sentinel(self) -> None:
        html = "<h2>Heading</h2>\n<p>Para.</p>"
        result = _inject_sentinels_into_html(html, [0, 2])
        assert 'agbpos-L0' in result
        assert 'agbpos-L2' in result

    def test_nested_paragraph_in_blockquote_not_collected(self) -> None:
        html = "<blockquote>\n<p>Quoted.</p>\n</blockquote>\n<p>After.</p>"
        result = _inject_sentinels_into_html(html, [0, 2])
        # Only 2 sentinels: one for blockquote, one for after-paragraph
        assert result.count("agbpos-L") == 2
        # Inner <p> must NOT get a sentinel
        assert "<span" not in result.split("<blockquote>")[1].split("</blockquote>")[0]

    def test_more_source_blocks_than_html_elements(self) -> None:
        # Loose list: 2 source blocks map to 1 <ul> element
        html = "<ul>\n<li><p>Item 1</p></li>\n<li><p>Item 2</p></li>\n</ul>\n<p>After.</p>"
        result = _inject_sentinels_into_html(html, [0, 2, 4])
        # Only 2 sentinels (ul + p), not 3
        assert result.count("agbpos-L") == 2
        assert "agbpos-L0" in result   # ul gets first line number
        assert "agbpos-L2" in result   # p gets second line number

    def test_empty_block_lines(self) -> None:
        html = "<p>Paragraph.</p>"
        result = _inject_sentinels_into_html(html, [])
        assert result == html

    def test_empty_html(self) -> None:
        result = _inject_sentinels_into_html("", [0])
        assert result == ""

    def test_pre_block_gets_sentinel(self) -> None:
        html = '<div class="sourceCode"><pre><code>x = 1</code></pre></div>'
        result = _inject_sentinels_into_html(html, [0])
        assert "agbpos-L0" in result

    def test_id_format_survives_sanitizer_regex(self) -> None:
        import re
        html = "<p>Test.</p>"
        result = _inject_sentinels_into_html(html, [42])
        ids = re.findall(r'id="([^"]+)"', result)
        assert ids == ["agbpos-L42"]
        # Verify the id matches _SAFE_ID_RE from renderer.py
        safe_id_re = re.compile(r"^[a-zA-Z][a-zA-Z0-9:_-]*$")
        for id_val in ids:
            assert safe_id_re.fullmatch(id_val)
