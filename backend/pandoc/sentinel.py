"""Scroll-sync sentinel injection for the preview render path.

Known limitations (the source scanner may misalign with rendered HTML for these):

1. Raw HTML blocks that span blank lines (pandoc folds the whole thing into one block,
   but the scanner counts the blank-separated parts).
2. Uppercase ``I.``-style single-space ordered lists: pandoc's capital-initial heuristic
   may treat the marker as a paragraph rather than a list.
3. Non-numeric ordered-list markers (``a.``, ``i.``, ``(1)``, ``#.``) sync at the block
   level but get no per-item sentinels; loose lists with such markers may misalign.
4. Multi-paragraph definition-list items (a ``dd`` with several blank-separated paragraphs).
5. Indented code blocks containing blank lines.
6. Footnote and inline-footnote sync assumes definitions appear near the document end
   (monotonic ordering).
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass, field
from html.parser import HTMLParser

from backend.pandoc import renderer
from backend.pandoc.renderer import _VOID_TAGS

_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")
# A list-item marker at the start of a (de-indented) line: a bullet (-, *, +) or an
# ordered marker (digits followed by '.' or ')'), in either case followed by whitespace.
_LIST_ITEM_RE = re.compile(r"^([-*+]|\d{1,9}[.)])(\s+)")
# A footnote definition at the start of a line: ``[^label]:`` with up to 3 leading spaces.
_FOOTNOTE_DEF_RE = re.compile(r"^\s{0,3}\[\^([^\]]+)\]:")
# A link reference definition: ``[label]:`` where the label does NOT start with ``^``.
_LINK_REF_DEF_RE = re.compile(r"^\s{0,3}\[[^^\]][^\]]*\]:\s")
# An inline footnote reference ``[^label]`` NOT immediately followed by ``:`` (a def).
_FOOTNOTE_REF_RE = re.compile(r"\[\^([^\]]+)\](?!:)")
# A definition-list marker line: ``:`` or ``~`` followed by whitespace (already de-indented).
_DEF_MARKER_RE = re.compile(r"^[:~]\s")
# A fenced-div line: 3+ colons; non-empty trailing attributes mean an opener, bare a closer.
_DIV_FENCE_RE = re.compile(r"^(:{3,})\s*(.*)$")
_ESCAPABLE_PUNCTUATION = frozenset(string.punctuation)


@dataclass(frozen=True)
class BlockAnchor:
    """A top-level markdown block paired with its source line.

    ``item_lines`` holds the source line of each top-level item when the block is a
    list, enabling per-item sentinels; it is empty for non-list blocks.
    """

    line: int
    item_lines: tuple[int, ...] = ()


@dataclass(frozen=True)
class ScanResult:
    """The result of scanning a markdown document for sentinel anchoring.

    ``blocks`` holds the in-flow top-level blocks (footnote and link-reference
    definitions excluded). ``footnote_lines`` holds the source line of each footnote
    ``<li>`` in pandoc reference order (the order in which footnotes are first referenced
    in the body), so the trailing footnotes ``<section>`` can be paired separately.
    """

    blocks: list[BlockAnchor]
    footnote_lines: tuple[int, ...] = ()


def _mask_inline_code_and_escapes(markdown: str) -> str:
    """Mask syntax where pandoc does not parse footnotes, preserving source positions."""
    masked = list(markdown)
    i = 0
    while i < len(markdown):
        if (
            markdown[i] == "\\"
            and i + 1 < len(markdown)
            and markdown[i + 1] in _ESCAPABLE_PUNCTUATION
        ):
            masked[i] = " "
            masked[i + 1] = " "
            i += 2
            continue
        if markdown[i] != "`":
            i += 1
            continue

        run_end = i + 1
        while run_end < len(markdown) and markdown[run_end] == "`":
            run_end += 1
        delimiter = markdown[i:run_end]
        close = markdown.find(delimiter, run_end)
        while close != -1 and (
            (close > 0 and markdown[close - 1] == "`")
            or (close + len(delimiter) < len(markdown) and markdown[close + len(delimiter)] == "`")
        ):
            close = markdown.find(delimiter, close + len(delimiter))
        if close == -1:
            i = run_end
            continue
        for pos in range(i, close + len(delimiter)):
            if markdown[pos] != "\n":
                masked[pos] = " "
        i = close + len(delimiter)
    return "".join(masked)


def _collect_footnote_lines(lines: list[str]) -> tuple[int, ...]:
    """Return footnote ``<li>`` source lines in pandoc document order.

    Pandoc emits one ``<li>`` per footnote reference *occurrence* in document order, not
    one per definition. A duplicate reference produces a new ``<li>`` (content looked up
    by label), and a definition that is never referenced is dropped. Each occurrence maps
    to the source line that ``<li>`` displays: the definition line for an inline reference
    ``[^label]``, or the occurrence line for an inline footnote ``^[``. References to an
    undefined label render as literal text (no ``<li>``) and are skipped.
    """
    definitions: dict[str, int] = {}
    i = 0
    while i < len(lines):
        m = _FOOTNOTE_DEF_RE.match(lines[i])
        if m:
            label = m.group(1)
            if label not in definitions:
                definitions[label] = i
            # Consume continuation lines (blank, or indented >= 4 spaces / a tab).
            i += 1
            while i < len(lines):
                cont = lines[i]
                if not cont.strip() or cont.startswith("    ") or cont.startswith("\t"):
                    i += 1
                    continue
                break
            continue
        i += 1

    occurrences: list[int] = []
    occurrence_lines = _mask_inline_code_and_escapes("\n".join(lines)).split("\n")
    in_fence = False
    fence_char = ""
    fence_len = 0
    for idx, raw in enumerate(occurrence_lines):
        if in_fence:
            m = _FENCE_RE.match(raw)
            if (
                m
                and m.group(1)[0] == fence_char
                and len(m.group(1)) >= fence_len
                and not raw[len(m.group(1)) :].strip()
            ):
                in_fence = False
            continue
        fence_match = _FENCE_RE.match(raw)
        if fence_match:
            in_fence = True
            fence_char = fence_match.group(1)[0]
            fence_len = len(fence_match.group(1))
            continue
        if _FOOTNOTE_DEF_RE.match(raw):
            continue
        # Merge inline references and inline footnotes in column order within the line so
        # the per-<li> ordering matches pandoc's left-to-right document order.
        line_occurrences: list[tuple[int, int]] = []
        for ref in _FOOTNOTE_REF_RE.finditer(raw):
            label = ref.group(1)
            if label in definitions:
                line_occurrences.append((ref.start(), definitions[label]))
        start = raw.find("^[")
        while start != -1:
            line_occurrences.append((start, idx))
            start = raw.find("^[", start + 2)
        line_occurrences.sort(key=lambda item: item[0])
        occurrences.extend(source_line for _, source_line in line_occurrences)

    return tuple(occurrences)


def _scan_document(markdown: str) -> ScanResult:
    """Scan ``markdown`` into in-flow block anchors plus footnote ``<li>`` source lines.

    A list is treated as a single top-level block anchored at its first item, matching
    pandoc's single ``<ul>``/``<ol>`` element. This holds whether the list follows a
    blank line or directly follows a paragraph (the ``lists_without_preceding_blankline``
    extension), and blank lines inside a loose list do not start new top-level blocks.
    Only fenced code blocks are tracked specially so blank lines inside a fence are not
    treated as block boundaries. Footnote definitions and link-reference definitions
    produce no in-flow HTML (footnotes are hoisted into a trailing ``<section>``), so they
    are excluded from ``blocks``. Other count mismatches (e.g. deeply nested constructs)
    are truncated when zipped against HTML elements during injection.
    """
    if not markdown.strip():
        return ScanResult(blocks=[])

    lines = markdown.split("\n")
    anchors: list[BlockAnchor] = []

    in_fence = False
    fence_char = ""
    fence_len = 0
    in_gap = True  # treat start-of-file as a gap so the first line starts a block

    in_list = False
    list_marker_indent = 0
    list_content_indent = 0
    list_anchor_index = -1
    current_items: list[int] = []

    def close_list() -> None:
        nonlocal in_list, list_anchor_index, current_items
        if in_list and list_anchor_index >= 0:
            anchor = anchors[list_anchor_index]
            anchors[list_anchor_index] = BlockAnchor(anchor.line, tuple(current_items))
        in_list = False
        list_anchor_index = -1
        current_items = []

    # Footnote definitions whose continuation lines should be skipped while scanning.
    skip_until = -1

    # Definition-list tracking: pandoc groups consecutive term/:definition groups (even
    # blank-separated) into one <dl>. ``unconfirmed_term_index`` is the anchor index of the
    # most recent generic block that could be a definition term.
    in_deflist = False
    deflist_term_index = -1
    unconfirmed_term_index = -1

    # Fenced-div nesting depth. Pandoc renders a fenced div (``::: class`` ... ``:::``) as a
    # single top-level <div> regardless of inner block count, so inner lines emit no anchors.
    div_depth = 0

    i = 0
    while i < len(lines):
        raw = lines[i]
        if i < skip_until:
            i += 1
            continue
        if in_fence:
            m = _FENCE_RE.match(raw)
            if (
                m
                and m.group(1)[0] == fence_char
                and len(m.group(1)) >= fence_len
                and not raw[len(m.group(1)) :].strip()
            ):
                in_fence = False
                fence_char = ""
                fence_len = 0
            i += 1
            continue

        if div_depth > 0:
            # Inside a fenced div: swallow lines without emitting anchors, tracking nesting.
            fence_match = _FENCE_RE.match(raw)
            if fence_match:
                # A code fence inside the div: enter fence mode so a ``:::`` in the code
                # body does not close the div.
                in_fence = True
                fence_char = fence_match.group(1)[0]
                fence_len = len(fence_match.group(1))
                i += 1
                continue
            div_match = _DIV_FENCE_RE.match(raw)
            if div_match:
                if div_match.group(2).strip():
                    div_depth += 1
                else:
                    div_depth -= 1
            i += 1
            continue

        is_blank = not raw.strip()
        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw[indent:]

        if in_list:
            if is_blank:
                in_gap = True  # may be a loose-list gap or the end of the list
                i += 1
                continue
            if indent >= list_content_indent:
                # Continuation or nested content belonging to the current item.
                in_gap = False
                i += 1
                continue
            marker = _LIST_ITEM_RE.match(stripped)
            if marker and indent <= list_marker_indent:
                # Sibling item of the same list.
                current_items.append(i)
                list_content_indent = indent + len(marker.group(0))
                in_gap = False
                i += 1
                continue
            # De-indented past the list: the list has ended; reprocess this line below.
            close_list()

        if is_blank:
            in_gap = True
            i += 1
            continue

        div_match = _DIV_FENCE_RE.match(raw)
        if div_match and div_match.group(2).strip():
            # A fenced-div opener at the top level: one <div> block. Inner blocks are
            # swallowed by the ``div_depth > 0`` branch above until the matching closer.
            if in_gap:
                anchors.append(BlockAnchor(i))
                unconfirmed_term_index = -1
                in_deflist = False
                in_gap = False
            div_depth = 1
            i += 1
            continue

        if in_gap and _FOOTNOTE_DEF_RE.match(raw):
            # Footnote definitions are hoisted into a trailing <section>; they are not
            # in-flow blocks. Consume their continuation lines (blank or indented >= 4).
            j = i + 1
            while j < len(lines):
                cont = lines[j]
                if not cont.strip() or cont.startswith("    ") or cont.startswith("\t"):
                    j += 1
                    continue
                break
            skip_until = j
            i += 1
            continue

        if in_gap and _LINK_REF_DEF_RE.match(raw):
            # Link reference definitions produce no HTML. Consume an immediately-following
            # indented (non-blank) continuation line (a multi-line title).
            if i + 1 < len(lines):
                nxt = lines[i + 1]
                if nxt.strip() and nxt[:1] == " ":
                    skip_until = i + 2
            i += 1
            continue

        m = _FENCE_RE.match(raw)
        if m:
            in_fence = True
            fence_char = m.group(1)[0]
            fence_len = len(m.group(1))
            if in_gap:
                anchors.append(BlockAnchor(i))
                in_gap = False
            # A code block can't be a definition term; reset deflist tracking.
            unconfirmed_term_index = -1
            in_deflist = False
            i += 1
            continue

        if (
            indent <= 3
            and _DEF_MARKER_RE.match(stripped)
            and (in_deflist or unconfirmed_term_index >= 0)
        ):
            # Definition-list marker line attached to a preceding term: a continuation of a
            # definition-list block, never its own block. (An orphan marker with no term
            # before it is rendered as a normal paragraph by pandoc, so it falls through to
            # the generic emit below.)
            if not in_deflist:
                in_deflist = True
                deflist_term_index = unconfirmed_term_index
            elif (
                unconfirmed_term_index == len(anchors) - 1
                and unconfirmed_term_index > deflist_term_index
            ):
                # A later term of the SAME dl (blank-separated) got its own anchor; merge
                # it away. Guarded to the last element so deflist_term_index never shifts.
                del anchors[unconfirmed_term_index]
            unconfirmed_term_index = -1
            in_gap = False
            i += 1
            continue

        marker = _LIST_ITEM_RE.match(stripped)
        if marker and indent <= 3:
            # Start of a new top-level list (after a blank line or directly after a
            # paragraph). The whole list is one block anchored at this first item.
            anchors.append(BlockAnchor(i))
            list_anchor_index = len(anchors) - 1
            in_list = True
            list_marker_indent = indent
            list_content_indent = indent + len(marker.group(0))
            current_items = [i]
            in_gap = False
            # A list can't be a definition term; reset deflist tracking.
            unconfirmed_term_index = -1
            in_deflist = False
            i += 1
            continue

        if in_gap:
            if in_deflist and unconfirmed_term_index >= 0:
                # Two consecutive generic blocks with no marker between → the dl has ended.
                in_deflist = False
                deflist_term_index = -1
            anchors.append(BlockAnchor(i))
            # This generic block may be a definition term for a following marker line.
            unconfirmed_term_index = len(anchors) - 1
            in_gap = False
        i += 1

    close_list()
    return ScanResult(blocks=anchors, footnote_lines=_collect_footnote_lines(lines))


def _scan_blocks(markdown: str) -> list[BlockAnchor]:
    """Return one :class:`BlockAnchor` per in-flow top-level markdown block."""
    return _scan_document(markdown).blocks


def _split_markdown_blocks(markdown: str) -> list[int]:
    """Return the starting source line number of each top-level markdown block."""
    return [anchor.line for anchor in _scan_blocks(markdown)]


_TOP_LEVEL_BLOCK_TAGS: frozenset[str] = frozenset(
    {
        "p",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "pre",
        "ul",
        "ol",
        "blockquote",
        "table",
        "figure",
        "div",
        "details",
        "section",
        "dl",
        "hr",
    }
)
_LIST_TAGS: frozenset[str] = frozenset({"ul", "ol"})


def _build_line_offsets(text: str) -> list[int]:
    """Return char offset of each line start (result[i] = offset of line i+1)."""
    offsets = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            offsets.append(i + 1)
    return offsets


@dataclass
class _HtmlBlock:
    """A top-level HTML block element and (for lists) its direct-child ``<li>`` offsets."""

    offset: int
    tag: str
    li_offsets: list[int] = field(default_factory=list)


class _BlockTagFinder(HTMLParser):
    """Collect top-level block elements and the direct ``<li>`` children of top-level lists."""

    def __init__(self, line_offsets: list[int]) -> None:
        super().__init__(convert_charrefs=False)
        self._line_offsets = line_offsets
        self._depth = 0
        self.blocks: list[_HtmlBlock] = []
        self._current_list: _HtmlBlock | None = None
        # The trailing footnotes <section>, paired separately from in-flow blocks.
        self.footnotes_section: _HtmlBlock | None = None
        self._in_footnotes = False

    def _offset(self) -> int:
        line, col = self.getpos()
        return self._line_offsets[line - 1] + col

    @staticmethod
    def _is_footnotes_section(tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        if tag != "section":
            return False
        for name, value in attrs:
            if name.lower() == "class" and value is not None and "footnotes" in value.split():
                return True
        return False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if self._depth == 0 and self._is_footnotes_section(tag_lower, attrs):
            section = _HtmlBlock(offset=self._offset(), tag=tag_lower)
            self.footnotes_section = section
            self._in_footnotes = True
        elif self._depth == 0 and tag_lower in _TOP_LEVEL_BLOCK_TAGS:
            block = _HtmlBlock(offset=self._offset(), tag=tag_lower)
            self.blocks.append(block)
            self._current_list = block if tag_lower in _LIST_TAGS else None
        elif self._depth == 1 and tag_lower == "li" and self._current_list is not None:
            self._current_list.li_offsets.append(self._offset())
        elif (
            self._in_footnotes
            and self._depth == 2
            and tag_lower == "li"
            and self.footnotes_section is not None
        ):
            self.footnotes_section.li_offsets.append(self._offset())
        if tag_lower not in _VOID_TAGS:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() not in _VOID_TAGS:
            self._depth = max(0, self._depth - 1)
            if self._depth == 0:
                self._current_list = None
                self._in_footnotes = False

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if self._depth == 0 and tag_lower in _TOP_LEVEL_BLOCK_TAGS:
            self.blocks.append(_HtmlBlock(offset=self._offset(), tag=tag_lower))
            self._current_list = None
        # self-closing: depth unchanged


def _inject_sentinels_into_html(
    html: str,
    anchors: list[BlockAnchor],
    footnote_lines: tuple[int, ...] = (),
) -> str:
    """Insert ``<span id="agbpos-L{n}">`` sentinels keyed to source line numbers.

    One sentinel is placed before each top-level block element (paired with the Nth
    source block). For list blocks, an extra sentinel is placed at the start of each
    direct ``<li>`` so multi-item lists sync per item. Pairings truncate to the shorter
    of the two sequences so count mismatches are handled gracefully.

    The trailing footnotes ``<section>`` (if present) is paired separately: a block
    sentinel keyed to ``footnote_lines[0]`` is placed before it, and each footnote
    ``<li>`` is keyed to its source definition line in pandoc reference order.
    """
    if not html or not anchors:
        return html

    line_offsets = _build_line_offsets(html)
    finder = _BlockTagFinder(line_offsets)
    finder.feed(html)
    finder.close()

    # (offset, fragment): the fragment is inserted immediately before `offset`.
    insertions: list[tuple[int, str]] = []
    for block, anchor in zip(finder.blocks, anchors, strict=False):
        insertions.append((block.offset, f'<span id="agbpos-L{anchor.line}"></span>'))
        if anchor.item_lines and block.tag in _LIST_TAGS:
            for li_offset, item_line in zip(block.li_offsets, anchor.item_lines, strict=False):
                # Insert just after the `<li ...>` start tag (a <span> is not valid as a
                # direct child of <ul>/<ol>, but is fine as the first child of an <li>).
                tag_end = html.find(">", li_offset)
                if tag_end == -1:
                    continue
                insertions.append((tag_end + 1, f'<span id="agbpos-L{item_line}"></span>'))

    section = finder.footnotes_section
    if section is not None and footnote_lines:
        insertions.append((section.offset, f'<span id="agbpos-L{footnote_lines[0]}"></span>'))
        for li_offset, fn_line in zip(section.li_offsets, footnote_lines, strict=False):
            tag_end = html.find(">", li_offset)
            if tag_end == -1:
                continue
            insertions.append((tag_end + 1, f'<span id="agbpos-L{fn_line}"></span>'))

    insertions.sort(key=lambda item: item[0])
    parts: list[str] = []
    prev = 0
    for offset, fragment in insertions:
        parts.append(html[prev:offset])
        parts.append(fragment)
        prev = offset
    parts.append(html[prev:])
    return "".join(parts)


async def render_markdown_preview(markdown: str) -> str:
    """Render markdown to HTML with scroll-sync sentinels for the editor preview."""
    if not markdown.strip():
        return ""
    scan = _scan_document(markdown)
    html = await renderer.render_markdown(markdown)
    return _inject_sentinels_into_html(html, scan.blocks, scan.footnote_lines)
