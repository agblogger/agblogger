"""Tests for scroll-sync sentinel injection."""

from __future__ import annotations

import re
import shutil
import subprocess
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from backend.pandoc.sentinel import (
    BlockAnchor,
    _BlockTagFinder,
    _build_line_offsets,
    _inject_sentinels_into_html,
    _scan_blocks,
    _scan_document,
    _split_markdown_blocks,
    render_markdown_preview,
)

_FOOTNOTE_DEF_RE = re.compile(r"^\s{0,3}\[\^[^\]]+\]:")


def _anchors(*lines: int) -> list[BlockAnchor]:
    return [BlockAnchor(line) for line in lines]


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

    def test_list_after_paragraph_without_blank_line_is_its_own_block(self) -> None:
        # Regression: the `lists_without_preceding_blankline` extension makes pandoc
        # start a list immediately after a paragraph. The list must count as a separate
        # top-level block (anchored at its first item) so HTML/source blocks stay aligned.
        md = "I see two possibilities.\n1. First.\n2. Second.\n\nAfter."
        assert _split_markdown_blocks(md) == [0, 1, 4]

    def test_list_after_blank_line_is_one_block_at_first_item(self) -> None:
        md = "Intro.\n\n- a\n- b\n\nAfter."
        assert _split_markdown_blocks(md) == [0, 2, 5]

    def test_loose_list_counts_as_single_block(self) -> None:
        # Blank lines inside a list must not create extra top-level blocks.
        md = "- a\n\n- b\n\nAfter."
        assert _split_markdown_blocks(md) == [0, 4]

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

    def test_scan_blocks_captures_list_item_lines(self) -> None:
        md = "Intro.\n1. First.\n2. Second.\n3. Third.\n\nAfter."
        anchors = _scan_blocks(md)
        assert [a.line for a in anchors] == [0, 1, 5]
        assert anchors[1].item_lines == (1, 2, 3)
        assert anchors[0].item_lines == ()
        assert anchors[2].item_lines == ()

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


class TestInjectSentinelsIntoHtml:
    def test_basic_two_paragraphs(self) -> None:
        html = "<p>First.</p>\n<p>Second.</p>"
        result = _inject_sentinels_into_html(html, _anchors(0, 2))
        assert '<span id="agbpos-L0"></span><p>First.</p>' in result
        assert '<span id="agbpos-L2"></span><p>Second.</p>' in result

    def test_heading_gets_sentinel(self) -> None:
        html = "<h2>Heading</h2>\n<p>Para.</p>"
        result = _inject_sentinels_into_html(html, _anchors(0, 2))
        assert "agbpos-L0" in result
        assert "agbpos-L2" in result

    def test_nested_paragraph_in_blockquote_not_collected(self) -> None:
        html = "<blockquote>\n<p>Quoted.</p>\n</blockquote>\n<p>After.</p>"
        result = _inject_sentinels_into_html(html, _anchors(0, 2))
        # Only 2 sentinels: one for blockquote, one for after-paragraph
        assert result.count("agbpos-L") == 2
        # Inner <p> must NOT get a sentinel
        assert "<span" not in result.split("<blockquote>")[1].split("</blockquote>")[0]

    def test_more_source_blocks_than_html_elements(self) -> None:
        # More source blocks than HTML elements: extra source lines are truncated.
        html = "<ul>\n<li><p>Item 1</p></li>\n<li><p>Item 2</p></li>\n</ul>\n<p>After.</p>"
        result = _inject_sentinels_into_html(html, _anchors(0, 2, 4))
        # Only 2 block sentinels (ul + p); the third source line has no HTML element.
        assert result.count("agbpos-L") == 2
        assert "agbpos-L0" in result  # ul gets first line number
        assert "agbpos-L2" in result  # p gets second line number

    def test_list_items_get_per_item_sentinels(self) -> None:
        html = "<ol>\n<li>Item 1</li>\n<li>Item 2</li>\n</ol>\n<p>After.</p>"
        anchors = [BlockAnchor(0, (0, 1)), BlockAnchor(3)]
        result = _inject_sentinels_into_html(html, anchors)
        # Block sentinel for the <ol> plus one inside each <li>, plus the after-paragraph.
        assert '<span id="agbpos-L0"></span><ol>' in result
        assert '<li><span id="agbpos-L0"></span>Item 1</li>' in result
        assert '<li><span id="agbpos-L1"></span>Item 2</li>' in result
        assert "agbpos-L3" in result

    def test_list_item_sentinels_only_for_direct_children(self) -> None:
        # A nested list's <li> must not receive a top-level item sentinel.
        html = "<ul>\n<li>Outer<ul>\n<li>Inner</li>\n</ul></li>\n</ul>"
        result = _inject_sentinels_into_html(html, [BlockAnchor(0, (0,))])
        assert result.count("agbpos-L0") == 2  # block sentinel + one direct <li>
        assert "Inner</li>" in result
        assert "<span" not in result.split("<li>Inner")[0].split("Outer")[1]

    def test_empty_block_lines(self) -> None:
        html = "<p>Paragraph.</p>"
        result = _inject_sentinels_into_html(html, [])
        assert result == html

    def test_empty_html(self) -> None:
        result = _inject_sentinels_into_html("", _anchors(0))
        assert result == ""

    def test_pre_block_gets_sentinel(self) -> None:
        html = '<div class="sourceCode"><pre><code>x = 1</code></pre></div>'
        result = _inject_sentinels_into_html(html, _anchors(0))
        assert "agbpos-L0" in result

    def test_id_format_survives_sanitizer_regex(self) -> None:
        html = "<p>Test.</p>"
        result = _inject_sentinels_into_html(html, _anchors(42))
        ids = re.findall(r'id="([^"]+)"', result)
        assert ids == ["agbpos-L42"]
        # Verify the id matches _SAFE_ID_RE from renderer.py
        safe_id_re = re.compile(r"^[a-zA-Z][a-zA-Z0-9:_-]*$")
        for id_val in ids:
            assert safe_id_re.fullmatch(id_val)


class TestRenderMarkdownPreview:
    async def test_uses_canonical_renderer_binding(self) -> None:
        mock_html = "<p>Only paragraph.</p>"
        with patch(
            "backend.pandoc.renderer.render_markdown",
            AsyncMock(return_value=mock_html),
        ) as renderer:
            html = await render_markdown_preview("Only paragraph.")
        renderer.assert_awaited_once_with("Only paragraph.")
        assert 'id="agbpos-L0"' in html

    async def test_sentinels_present_in_output(self) -> None:
        mock_html = "<p>Paragraph one.</p>\n<p>Paragraph two.</p>"
        with patch(
            "backend.pandoc.renderer.render_markdown",
            AsyncMock(return_value=mock_html),
        ):
            html = await render_markdown_preview("Paragraph one.\n\nParagraph two.")
        assert 'id="agbpos-L0"' in html
        assert 'id="agbpos-L2"' in html

    async def test_single_paragraph_has_sentinel(self) -> None:
        mock_html = "<p>Only paragraph.</p>"
        with patch(
            "backend.pandoc.renderer.render_markdown",
            AsyncMock(return_value=mock_html),
        ):
            html = await render_markdown_preview("Only paragraph.")
        assert 'id="agbpos-L0"' in html

    async def test_empty_markdown_no_sentinel(self) -> None:
        with patch(
            "backend.pandoc.renderer.render_markdown",
            AsyncMock(return_value=""),
        ):
            html = await render_markdown_preview("")
        assert "agbpos" not in html


_BUG1_MARKDOWN = "First.[^1]\n\nSecond.[^2]\n\n[^1]: Footnote one.\n\n[^2]: Footnote two.\n\nThird."


class TestFootnoteDefinitions:
    def test_footnote_defs_excluded_from_in_flow_blocks(self) -> None:
        # Bug 1: footnote definition lines must not become in-flow block anchors.
        assert _split_markdown_blocks(_BUG1_MARKDOWN) == [0, 2, 8]

    def test_footnote_lines_in_reference_order(self) -> None:
        scan = _scan_document(_BUG1_MARKDOWN)
        assert scan.footnote_lines == (4, 6)

    def test_footnote_lines_follow_reference_order_not_def_order(self) -> None:
        # Bug 1: <li> order follows reference order in the body.
        # Reference [^b] appears before [^a]; definitions are a then b.
        md = "Body [^b] and [^a].\n\n[^a]: alpha.\n\n[^b]: beta.\n\nEnd."
        scan = _scan_document(md)
        # def lines: [^a] at 2, [^b] at 4; reference order is b, a -> (4, 2)
        assert scan.footnote_lines == (4, 2)

    def test_unreferenced_definition_dropped(self) -> None:
        md = "Ref [^1] then [^3].\n\n[^1]: one.\n\n[^2]: two.\n\n[^3]: three.\n\nEnd."
        scan = _scan_document(md)
        # def lines: 1 at 2, 2 at 4, 3 at 6; referenced 1 then 3 -> (2, 6)
        assert scan.footnote_lines == (2, 6)
        assert len(scan.footnote_lines) == 2

    def test_multiline_footnote_def_continuation_consumed(self) -> None:
        md = (
            "Body [^1].\n"
            "\n"
            "[^1]: First paragraph.\n"
            "\n"
            "    Second paragraph of the footnote.\n"
            "\n"
            "After."
        )
        # The footnote def at line 2 plus its indented continuation (line 4) must be
        # consumed; the block after gets line 6, not an earlier line.
        assert _split_markdown_blocks(md) == [0, 6]

    def test_inline_footnote_occurrence(self) -> None:
        md = "Body with^[inline note] here.\n\nAfter."
        scan = _scan_document(md)
        # Inline footnote occurrence keyed to the line where ^[ appears.
        assert scan.footnote_lines == (0,)

    def test_duplicate_reference_creates_one_li_per_occurrence(self) -> None:
        # Pandoc emits one <li> per reference OCCURRENCE (not per definition): a duplicate
        # reference duplicates the content into a new <li>, and an unreferenced definition
        # ([^3]) is dropped.
        md = "A[^1] B[^2] C[^2]\n\n[^1]: one\n\n[^2]: two\n\n[^3]: three"
        scan = _scan_document(md)
        # def lines: 1 at 2, 2 at 4; occurrences in order 1, 2, 2 -> (2, 4, 4)
        assert len(scan.footnote_lines) == 3
        assert scan.footnote_lines == (2, 4, 4)

    def test_reference_like_text_in_inline_code_is_ignored(self) -> None:
        md = "Code `[^a]` then real[^b].\n\n[^a]: alpha.\n\n[^b]: beta."
        scan = _scan_document(md)
        assert scan.footnote_lines == (4,)

    def test_escaped_reference_like_text_is_ignored(self) -> None:
        md = "Escaped \\[^a] then real[^b].\n\n[^a]: alpha.\n\n[^b]: beta."
        scan = _scan_document(md)
        assert scan.footnote_lines == (4,)


class TestLinkReferenceDefinitions:
    def test_link_ref_def_excluded_from_in_flow_blocks(self) -> None:
        # Bug 2: link reference definitions produce no HTML and must be excluded.
        md = "See [x][r].\n\n[r]: https://e.com\n\nAfter."
        assert _split_markdown_blocks(md) == [0, 4]

    def test_multiline_link_ref_def_title_consumed(self) -> None:
        md = 'See [x][r].\n\n[r]: https://e.com\n  "A title"\n\nAfter.'
        # The continuation title line is consumed with the ref def.
        assert _split_markdown_blocks(md) == [0, 5]


_DEF_MARKER_RE = re.compile(r"^\s{0,3}[:~]\s")


class TestDefinitionListScanning:
    def test_tight_single_pair_is_one_block(self) -> None:
        assert _split_markdown_blocks("Term\n:   Def\n\nAfter.") == [0, 3]

    def test_loose_single_pair_is_one_block(self) -> None:
        # The `:` line does NOT get an anchor; the term does.
        assert _split_markdown_blocks("Term\n\n:   Def\n\nAfter.") == [0, 4]

    def test_loose_multi_term_is_one_block(self) -> None:
        md = "Term one\n:   Def one\n\nTerm two\n:   Def two\n\nAfter."
        assert _split_markdown_blocks(md) == [0, 6]

    def test_loose_multi_term_blank_between_term_and_def(self) -> None:
        md = "T1\n\n:   D1\n\nT2\n\n:   D2\n\nAfter."
        assert _split_markdown_blocks(md) == [0, 8]

    def test_tilde_marker(self) -> None:
        assert _split_markdown_blocks("Term\n~   Def\n\nAfter.") == [0, 3]

    def test_deflist_followed_by_heading(self) -> None:
        md = "Term\n:   Def\n\n## Next\n\nPara."
        assert _split_markdown_blocks(md) == [0, 3, 5]

    def test_two_separate_deflists_with_paragraph_between(self) -> None:
        md = "A\n:   da\n\nMiddle para.\n\nB\n:   db\n\nEnd."
        assert _split_markdown_blocks(md) == [0, 3, 5, 8]

    def test_orphan_marker_no_preceding_term(self) -> None:
        # Malformed: a `:`-leading line with no term before it must not crash or delete.
        assert _split_markdown_blocks(":   orphan\n\nAfter.") == [0, 2]

    @given(st.text(min_size=0, max_size=300))
    @settings(max_examples=200)
    def test_no_in_flow_block_is_a_definition_marker_line(self, markdown: str) -> None:
        lines = markdown.split("\n")
        result = _split_markdown_blocks(markdown)
        assert result == sorted(set(result))
        for line_no in result:
            if not _DEF_MARKER_RE.match(lines[line_no]):
                continue
            # A def-marker line attached to a preceding term is absorbed into the
            # term's block, never its own. It is only ever a block start as an
            # "orphan": at the document start, or after a blank line, with no term
            # on the line directly above. See test_orphan_marker_no_preceding_term.
            assert line_no == 0 or not lines[line_no - 1].strip()


class TestDefinitionListAndHorizontalRule:
    def test_finder_collects_dl(self) -> None:
        # Bug 3: <dl> must be collected as a top-level block.
        html = "<p>Before.</p>\n<dl>\n<dt>Term</dt>\n<dd>Def</dd>\n</dl>\n<p>After.</p>"
        result = _inject_sentinels_into_html(html, _anchors(0, 2, 6))
        assert result.count("agbpos-L") == 3
        assert '<span id="agbpos-L0"></span><p>Before.</p>' in result
        assert '<span id="agbpos-L2"></span><dl>' in result
        assert '<span id="agbpos-L6"></span><p>After.</p>' in result

    def test_finder_collects_hr(self) -> None:
        # Bug 4: <hr /> must be collected as a top-level block.
        html = "<p>Before.</p>\n<hr />\n<p>After.</p>"
        result = _inject_sentinels_into_html(html, _anchors(0, 2, 3))
        assert result.count("agbpos-L") == 3
        assert '<span id="agbpos-L2"></span><hr' in result


class TestFootnotesSectionInjection:
    _FOOTNOTES_HTML = (
        "<p>First.</p>\n"
        "<p>Second.</p>\n"
        '<section id="footnotes" class="footnotes footnotes-end-of-document"'
        ' role="doc-endnotes">\n'
        "<hr />\n"
        "<ol>\n"
        '<li id="fn1"><p>one</p></li>\n'
        '<li id="fn2"><p>two</p></li>\n'
        "</ol>\n"
        "</section>"
    )

    def test_footnotes_section_does_not_consume_body_anchor(self) -> None:
        result = _inject_sentinels_into_html(
            self._FOOTNOTES_HTML, _anchors(0, 2), footnote_lines=(44, 45)
        )
        assert '<span id="agbpos-L0"></span><p>First.</p>' in result
        assert '<span id="agbpos-L2"></span><p>Second.</p>' in result

    def test_footnotes_section_block_sentinel(self) -> None:
        result = _inject_sentinels_into_html(
            self._FOOTNOTES_HTML, _anchors(0, 2), footnote_lines=(44, 45)
        )
        assert '<span id="agbpos-L44"></span><section' in result

    def test_footnotes_li_sentinels(self) -> None:
        result = _inject_sentinels_into_html(
            self._FOOTNOTES_HTML, _anchors(0, 2), footnote_lines=(44, 45)
        )
        assert '<li id="fn1"><span id="agbpos-L44"></span>' in result
        assert '<li id="fn2"><span id="agbpos-L45"></span>' in result

    def test_non_footnote_section_is_in_flow_block(self) -> None:
        html = "<p>Before.</p>\n<section>\n<p>Inside.</p>\n</section>\n<p>After.</p>"
        result = _inject_sentinels_into_html(html, _anchors(0, 1, 4))
        assert result.count("agbpos-L") == 3
        assert '<span id="agbpos-L1"></span><section>' in result


class TestScanBlocksProperties:
    @given(st.text(min_size=0, max_size=300))
    @settings(max_examples=200)
    def test_no_in_flow_block_is_a_footnote_definition_line(self, markdown: str) -> None:
        lines = markdown.split("\n")
        for line_no in _split_markdown_blocks(markdown):
            assert not _FOOTNOTE_DEF_RE.match(lines[line_no])


class TestFencedDivs:
    def test_simple_div_is_one_block(self) -> None:
        md = "::: note\nText.\n:::\n\nAfter."
        assert _split_markdown_blocks(md) == [0, 4]

    def test_multiblock_div_is_one_block(self) -> None:
        md = "::: note\nPara one.\n\nPara two.\n:::\n\nAfter."
        assert _split_markdown_blocks(md) == [0, 6]

    def test_nested_div_is_one_block(self) -> None:
        md = "::: outer\nA\n\n::: inner\nB\n:::\n\nC\n:::\n\nAfter."
        # One outer div plus the after-paragraph.
        assert _split_markdown_blocks(md) == [0, 10]

    def test_div_with_code_fence_containing_colons(self) -> None:
        md = "::: note\n```\n:::\n```\n:::\n\nAfter."
        # The ``` fence body contains a `:::` line that must NOT close the div.
        assert _split_markdown_blocks(md) == [0, 6]

    def test_brace_attr_div(self) -> None:
        md = "::: {.warning}\nWatch out.\n:::\n\nAfter."
        assert _split_markdown_blocks(md) == [0, 4]

    def test_bare_colons_is_paragraph(self) -> None:
        md = ":::\nLone.\n:::\n\nAfter."
        # No open div -> bare ::: is paragraph text; pandoc renders a single <p>.
        assert _split_markdown_blocks(md) == [0, 4]

    def test_div_followed_by_content(self) -> None:
        md = "::: note\nInside.\n:::\n\nMiddle.\n\nEnd."
        assert _split_markdown_blocks(md) == [0, 4, 6]


_BATTERY_CASES: dict[str, str] = {
    "paragraphs": "One.\n\nTwo.\n\nThree.",
    "atx headings": "# H1\n\nP.\n\n## H2\n\nQ.",
    "setext h1/h2": "Title\n=====\n\nP.\n\nSub\n---\n\nQ.",
    "blockquote nested": "> outer\n> > inner\n> back\n\nAfter.",
    "blockquote multi-para": "> a\n>\n> b\n\nAfter.",
    "indented code": "Before.\n\n    line1\n    line2\n\nAfter.",
    "fenced code": "Before.\n\n```\nx\n```\n\nAfter.",
    "fenced code attrs": "Before.\n\n``` {.python}\nx = 1\n```\n\nAfter.",
    "line block": "| line one\n| line two\n\nAfter.",
    "bullet list": "- a\n- b\n- c\n\nAfter.",
    "ordered 1.": "1. a\n2. b\n\nAfter.",
    "ordered 1)": "1) a\n2) b\n\nAfter.",
    "ordered (1)": "(1) a\n(2) b\n\nAfter.",
    "ordered #.": "#. a\n#. b\n\nAfter.",
    "ordered a.": "a. a\nb. b\n\nAfter.",
    "ordered A)": "A) a\nB) b\n\nAfter.",
    "ordered i.": "i. a\nii. b\n\nAfter.",
    "example list": "(@) first\n(@) second\n\nAfter.",
    "nested list": "- a\n- b\n    - b1\n    - b2\n- c\n\nAfter.",
    "loose list": "- a\n\n- b\n\nAfter.",
    "def list tight": "Term\n:   Def\n\nAfter.",
    "def list loose": "Term\n\n:   Def\n\nAfter.",
    "def list multi": "T1\n:   D1\n\nT2\n:   D2\n\nAfter.",
    "pipe table": "| A | B |\n|---|---|\n| 1 | 2 |\n\nAfter.",
    "grid table": "+---+---+\n| A | B |\n+===+===+\n| 1 | 2 |\n+---+---+\n\nAfter.",
    "simple table": "  A   B\n --- ---\n  1   2\n\nAfter.",
    "multiline table": (
        "-------------\n A      B\n ------ ------\n 1      2\n-------------\n\nAfter."
    ),
    "hr dashes": "Before.\n\n---\n\nAfter.",
    "hr stars": "Before.\n\n***\n\nAfter.",
    "hr unders": "Before.\n\n___\n\nAfter.",
    "fenced div simple": "::: note\nText.\n:::\n\nAfter.",
    "fenced div multiblock": "::: note\nPara one.\n\nPara two.\n:::\n\nAfter.",
    "raw html block": '<div class="x">\nraw\n</div>\n\nAfter.',
    "image figure": "Before.\n\n![cap](real.png)\n\nAfter.",
    "math display": "Before.\n\n$$\nE = mc^2\n$$\n\nAfter.",
    "footnotes basic": "A.[^1]\n\nB.[^2]\n\n[^1]: one\n\n[^2]: two\n\nC.",
    "inline footnote": "A note.^[the inline note text]\n\nAfter.",
    "link ref def": "See [x][r].\n\n[r]: https://e.com\n\nAfter.",
    "heading after para no blank": "Para.\n# Heading\n\nAfter.",
    "list then para no blank": "- a\n- b\nAfter the list.",
}


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc binary not available")
class TestConstructAlignmentBattery:
    """For each pandoc construct, the source scanner must agree with rendered HTML.

    Known-limitation cases (``ordered I.`` capital-roman heuristic, ``raw html
    multiblock`` spanning blank lines) are excluded; see the module docstring of
    ``backend.pandoc.sentinel``.
    """

    @pytest.mark.parametrize("md", _BATTERY_CASES.values(), ids=list(_BATTERY_CASES.keys()))
    def test_scanner_agrees_with_rendered_html(self, md: str) -> None:
        html = subprocess.run(
            [
                "pandoc",
                "-f",
                "markdown+emoji+lists_without_preceding_blankline+mark",
                "-t",
                "html5",
                "--wrap=none",
            ],
            input=md,
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        scan = _scan_document(md)
        finder = _BlockTagFinder(_build_line_offsets(html))
        finder.feed(html)
        finder.close()
        li = len(finder.footnotes_section.li_offsets) if finder.footnotes_section else 0
        assert len(scan.blocks) == len(finder.blocks)
        assert li == len(scan.footnote_lines)
