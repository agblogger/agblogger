# Editor Scroll Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add independently scrollable editor and preview panes (capped at 80vh) with accurate bidirectional scroll sync driven by server-injected position sentinels and a client-side mirror div.

**Architecture:** The preview render endpoint pre-processes HTML to inject `<span id="agbpos-L{n}">` sentinels before each top-level block element, where `n` is the block's source line number from a markdown block splitter. The `useScrollSync` React hook builds two lazy maps on first scroll after content change: a mirror-div map (source line → editor pixel) and a sentinel map (source line → preview pixel). Bidirectional piecewise-linear interpolation between sentinel pairs drives scroll sync. A toggle button above the pane grid enables/disables sync.

**Tech Stack:** Python `html.parser` (HTML sentinel injector), FastAPI (endpoint update), React + TypeScript hooks, Tailwind CSS (layout).

---

## Files

**Create:**
- `backend/pandoc/sentinel.py` — `_split_markdown_blocks`, `_inject_sentinels_into_html`, exported `render_markdown_preview`
- `tests/test_rendering/test_sentinel.py` — unit + property-based tests for sentinel functions
- `frontend/src/hooks/useScrollSync.ts` — scroll sync hook
- `frontend/src/hooks/__tests__/useScrollSync.test.ts` — hook unit tests

**Modify:**
- `backend/api/render.py` — call `render_markdown_preview` in the preview endpoint
- `frontend/src/pages/EditorPage.tsx` — layout (80vh), sync toggle button, wire up hook

---

## Task 1: Markdown block splitter

**Files:**
- Create: `backend/pandoc/sentinel.py`
- Create: `tests/test_rendering/test_sentinel.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_rendering/test_sentinel.py
"""Tests for scroll-sync sentinel injection."""

from __future__ import annotations

import pytest
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
        assert _split_markdown_blocks(md) == [0, 5]

    def test_fence_character_must_match(self) -> None:
        # ``` opened, ~~~ does NOT close it
        md = "```\ncode\n\nmore\n~~~\n\nstill inside\n```\n\nAfter."
        assert _split_markdown_blocks(md) == [0, 9]

    @given(st.text(min_size=0, max_size=300))
    @settings(max_examples=200)
    def test_all_returned_line_numbers_point_to_non_blank_lines(
        self, markdown: str
    ) -> None:
        lines = markdown.split("\n")
        for line_no in _split_markdown_blocks(markdown):
            assert 0 <= line_no < len(lines)
            assert lines[line_no].strip() != ""

    @given(st.text(min_size=0, max_size=300))
    @settings(max_examples=200)
    def test_line_numbers_are_strictly_increasing(self, markdown: str) -> None:
        result = _split_markdown_blocks(markdown)
        assert result == sorted(set(result))
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
uv run pytest tests/test_rendering/test_sentinel.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'backend.pandoc.sentinel'`

- [ ] **Step 3: Implement `_split_markdown_blocks`**

```python
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
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run pytest tests/test_rendering/test_sentinel.py::TestSplitMarkdownBlocks -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add backend/pandoc/sentinel.py tests/test_rendering/test_sentinel.py
git commit -m "feat: add markdown block splitter for scroll sync sentinels"
```

---

## Task 2: HTML sentinel injector

**Files:**
- Modify: `backend/pandoc/sentinel.py`
- Modify: `tests/test_rendering/test_sentinel.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_rendering/test_sentinel.py`:

```python
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
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
uv run pytest tests/test_rendering/test_sentinel.py::TestInjectSentinelsIntoHtml -v 2>&1 | head -10
```

Expected: `ImportError` (function not defined yet).

- [ ] **Step 3: Implement `_inject_sentinels_into_html`**

Open `backend/pandoc/sentinel.py` and add this import directly after the existing `import re` line at the top:

```python
from html.parser import HTMLParser
```

Then append the following after `_split_markdown_blocks`:

```python

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
    for offset, line_no in zip(finder.offsets, block_lines):
        parts.append(html[prev:offset])
        parts.append(f'<span id="agbpos-L{line_no}"></span>')
        prev = offset
    parts.append(html[prev:])
    return "".join(parts)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run pytest tests/test_rendering/test_sentinel.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add backend/pandoc/sentinel.py tests/test_rendering/test_sentinel.py
git commit -m "feat: add HTML sentinel injector for scroll sync"
```

---

## Task 3: Preview render function + endpoint

**Files:**
- Modify: `backend/pandoc/sentinel.py` — add `render_markdown_preview`
- Modify: `backend/api/render.py` — call `render_markdown_preview`
- Modify: `tests/test_rendering/test_sentinel.py` — integration test

- [ ] **Step 1: Add failing integration test**

Append to `tests/test_rendering/test_sentinel.py`:

```python
from unittest.mock import AsyncMock, patch

import pytest

from backend.pandoc.sentinel import render_markdown_preview


class TestRenderMarkdownPreview:
    @pytest.mark.anyio
    async def test_sentinels_present_in_output(self) -> None:
        mock_html = "<p>Paragraph one.</p>\n<p>Paragraph two.</p>"
        with patch(
            "backend.pandoc.sentinel.render_markdown",
            AsyncMock(return_value=mock_html),
        ):
            html = await render_markdown_preview("Paragraph one.\n\nParagraph two.")
        assert 'id="agbpos-L0"' in html
        assert 'id="agbpos-L2"' in html

    @pytest.mark.anyio
    async def test_single_paragraph_has_sentinel(self) -> None:
        mock_html = "<p>Only paragraph.</p>"
        with patch(
            "backend.pandoc.sentinel.render_markdown",
            AsyncMock(return_value=mock_html),
        ):
            html = await render_markdown_preview("Only paragraph.")
        assert 'id="agbpos-L0"' in html

    @pytest.mark.anyio
    async def test_empty_markdown_no_sentinel(self) -> None:
        with patch(
            "backend.pandoc.sentinel.render_markdown",
            AsyncMock(return_value=""),
        ):
            html = await render_markdown_preview("")
        assert "agbpos" not in html
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
uv run pytest tests/test_rendering/test_sentinel.py::TestRenderMarkdownPreview -v 2>&1 | head -15
```

Expected: `ImportError` for `render_markdown_preview`.

- [ ] **Step 3: Add `render_markdown_preview` to `sentinel.py`**

Add the import and function at the bottom of `backend/pandoc/sentinel.py`:

```python
from backend.pandoc.renderer import render_markdown


async def render_markdown_preview(markdown: str) -> str:
    """Render markdown to HTML with scroll-sync sentinels for the editor preview."""
    block_lines = _split_markdown_blocks(markdown)
    html = await render_markdown(markdown)
    return _inject_sentinels_into_html(html, block_lines)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run pytest tests/test_rendering/test_sentinel.py::TestRenderMarkdownPreview -v
```

- [ ] **Step 5: Update the preview endpoint**

In `backend/api/render.py`, replace the `render_markdown` import and call:

```python
# Change this import:
from backend.pandoc.renderer import RenderError, render_markdown, rewrite_relative_urls
# To:
from backend.pandoc.renderer import RenderError, rewrite_relative_urls
from backend.pandoc.sentinel import render_markdown_preview
```

In the `preview` handler body, change:

```python
# Before:
html = await render_markdown(body.markdown)
# After:
html = await render_markdown_preview(body.markdown)
```

- [ ] **Step 6: Run the full backend check**

```bash
just check-backend
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add backend/pandoc/sentinel.py backend/api/render.py tests/test_rendering/test_sentinel.py
git commit -m "feat: use sentinel-injected render for editor preview endpoint"
```

---

## Task 4: Editor layout — 80vh height cap + sync toggle button

**Files:**
- Modify: `frontend/src/pages/EditorPage.tsx`

The current two-column grid has `style={{ minHeight: '60vh' }}` and the textarea has `h-full min-h-[60vh]`. Both need replacing. The preview div already has `overflow-y-auto` and just needs a height.

- [ ] **Step 1: Update the grid container and column heights**

Find and replace in `EditorPage.tsx`:

```tsx
// BEFORE — the outer grid div (around line 567):
<div className="grid grid-cols-1 lg:grid-cols-2 gap-4" style={{ minHeight: '60vh' }}>
  <div className={mobileTab === 'preview' ? 'hidden lg:block' : ''}>
    <MarkdownToolbar ... />
    <input {...imageInputProps} />
    <textarea
      ...
      className="w-full h-full min-h-[60vh] p-4 bg-paper-warm border border-border rounded-lg
               font-mono text-sm leading-relaxed text-ink resize-none
               focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
               disabled:opacity-50"
      ...
    />
  </div>

  <div className={`p-6 bg-paper border border-border rounded-lg overflow-y-auto ${mobileTab === 'edit' ? 'hidden lg:block' : ''}`}>

// AFTER:
<div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
  <div className={`flex flex-col h-[80vh] ${mobileTab === 'preview' ? 'hidden lg:flex' : ''}`}>
    <MarkdownToolbar ... />
    <input {...imageInputProps} />
    <textarea
      ...
      className="flex-1 overflow-y-auto w-full p-4 bg-paper-warm border border-border rounded-lg
               font-mono text-sm leading-relaxed text-ink resize-none
               focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
               disabled:opacity-50"
      ...
    />
  </div>

  <div className={`h-[80vh] p-6 bg-paper border border-border rounded-lg overflow-y-auto ${mobileTab === 'edit' ? 'hidden lg:block' : ''}`}>
```

- [ ] **Step 2: Add sync toggle state and button**

After the `mobileTab` state declaration, add:

```tsx
const [syncScroll, setSyncScroll] = useState(true)
```

Add a toggle button row directly above the grid (after the mobile tab switcher div and before the grid div):

```tsx
{/* Sync toggle — desktop only, mobile shows one pane at a time */}
<div className="hidden lg:flex justify-end mb-2">
  <button
    type="button"
    onClick={() => setSyncScroll((s) => !s)}
    className={`inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-lg border transition-colors ${
      syncScroll
        ? 'bg-accent/10 border-accent/30 text-accent'
        : 'bg-paper-warm border-border text-muted hover:text-ink'
    }`}
  >
    ⇄ Sync
  </button>
</div>
```

- [ ] **Step 3: Verify the UI renders without errors**

```bash
just start
```

Open `http://localhost:5173`, navigate to the editor. Verify:
- Both panes are the same tall fixed height.
- The "⇄ Sync" button appears above the panes on desktop.
- Clicking the button changes its visual state (accent vs muted).
- Both panes scroll independently.

```bash
just stop
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/EditorPage.tsx
git commit -m "feat: cap editor/preview panes at 80vh with independent scroll and sync toggle"
```

---

## Task 5: `useScrollSync` hook — skeleton and unit tests

**Files:**
- Create: `frontend/src/hooks/useScrollSync.ts`
- Create: `frontend/src/hooks/__tests__/useScrollSync.test.ts`

- [ ] **Step 1: Write failing unit tests**

```typescript
// frontend/src/hooks/__tests__/useScrollSync.test.ts
import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useScrollSync } from '@/hooks/useScrollSync'

function makeTextarea(scrollTop = 0, scrollHeight = 1000, clientHeight = 400): HTMLTextAreaElement {
  const el = document.createElement('textarea')
  Object.defineProperty(el, 'scrollTop', { get: () => scrollTop, set: vi.fn(), configurable: true })
  Object.defineProperty(el, 'scrollHeight', { get: () => scrollHeight, configurable: true })
  Object.defineProperty(el, 'clientHeight', { get: () => clientHeight, configurable: true })
  Object.defineProperty(el, 'clientWidth', { get: () => 600, configurable: true })
  return el
}

function makeDiv(scrollTop = 0, scrollHeight = 2000, clientHeight = 400): HTMLDivElement {
  const el = document.createElement('div')
  Object.defineProperty(el, 'scrollTop', { get: () => scrollTop, set: vi.fn(), configurable: true })
  Object.defineProperty(el, 'scrollHeight', { get: () => scrollHeight, configurable: true })
  Object.defineProperty(el, 'clientHeight', { get: () => clientHeight, configurable: true })
  return el
}

describe('useScrollSync', () => {
  it('starts with sync enabled', () => {
    const { result } = renderHook(() =>
      useScrollSync({
        textareaRef: { current: null },
        previewRef: { current: null },
        content: '',
      })
    )
    expect(result.current.syncEnabled).toBe(true)
  })

  it('toggleSync toggles syncEnabled', () => {
    const { result } = renderHook(() =>
      useScrollSync({
        textareaRef: { current: null },
        previewRef: { current: null },
        content: '',
      })
    )
    act(() => result.current.toggleSync())
    expect(result.current.syncEnabled).toBe(false)
    act(() => result.current.toggleSync())
    expect(result.current.syncEnabled).toBe(true)
  })

  it('onEditorScroll is a no-op when refs are null', () => {
    const { result } = renderHook(() =>
      useScrollSync({
        textareaRef: { current: null },
        previewRef: { current: null },
        content: '',
      })
    )
    // Should not throw
    expect(() => result.current.onEditorScroll()).not.toThrow()
  })

  it('onPreviewScroll is a no-op when refs are null', () => {
    const { result } = renderHook(() =>
      useScrollSync({
        textareaRef: { current: null },
        previewRef: { current: null },
        content: '',
      })
    )
    expect(() => result.current.onPreviewScroll()).not.toThrow()
  })

  it('scroll handlers are no-ops when syncEnabled is false', () => {
    const textarea = makeTextarea()
    const preview = makeDiv()
    const previewScrollTopSetter = vi.fn()
    Object.defineProperty(preview, 'scrollTop', { get: () => 0, set: previewScrollTopSetter, configurable: true })

    const { result } = renderHook(() =>
      useScrollSync({
        textareaRef: { current: textarea },
        previewRef: { current: preview },
        content: 'Some content',
      })
    )
    act(() => result.current.toggleSync())  // disable sync
    act(() => result.current.onEditorScroll())
    expect(previewScrollTopSetter).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd frontend && npx vitest run src/hooks/__tests__/useScrollSync.test.ts 2>&1 | head -15
```

Expected: module not found error.

- [ ] **Step 3: Create hook skeleton**

```typescript
// frontend/src/hooks/useScrollSync.ts
import { useCallback, useEffect, useRef, useState } from 'react'

interface SentinelEntry {
  line: number
  top: number
}

interface SyncMap {
  editorLines: number[]
  sentinels: SentinelEntry[]
}

interface UseScrollSyncOptions {
  textareaRef: React.RefObject<HTMLTextAreaElement>
  previewRef: React.RefObject<HTMLDivElement>
  content: string
}

interface UseScrollSyncResult {
  syncEnabled: boolean
  toggleSync: () => void
  onEditorScroll: () => void
  onPreviewScroll: () => void
}

export function useScrollSync({
  textareaRef,
  previewRef,
  content,
}: UseScrollSyncOptions): UseScrollSyncResult {
  const [syncEnabled, setSyncEnabled] = useState(true)
  const syncEnabledRef = useRef(syncEnabled)
  const mapRef = useRef<SyncMap | null>(null)
  const syncingRef = useRef(false)
  const mirrorRef = useRef<HTMLDivElement | null>(null)

  // Keep syncEnabledRef in sync with state
  useEffect(() => {
    syncEnabledRef.current = syncEnabled
  }, [syncEnabled])

  // Invalidate map on content change
  useEffect(() => {
    mapRef.current = null
  }, [content])

  // Create mirror div on mount, remove on unmount
  useEffect(() => {
    const mirror = document.createElement('div')
    mirror.style.position = 'absolute'
    mirror.style.top = '-9999px'
    mirror.style.left = '-9999px'
    mirror.style.visibility = 'hidden'
    mirror.style.pointerEvents = 'none'
    document.body.appendChild(mirror)
    mirrorRef.current = mirror
    return () => {
      document.body.removeChild(mirror)
      mirrorRef.current = null
    }
  }, [])

  const toggleSync = useCallback(() => setSyncEnabled((s) => !s), [])

  const onEditorScroll = useCallback(() => {
    if (!syncEnabledRef.current || syncingRef.current) return
    const textarea = textareaRef.current
    const preview = previewRef.current
    if (!textarea || !preview) return
    // Map building and sync handled in Task 6
  }, [textareaRef, previewRef])

  const onPreviewScroll = useCallback(() => {
    if (!syncEnabledRef.current || syncingRef.current) return
    const textarea = textareaRef.current
    const preview = previewRef.current
    if (!textarea || !preview) return
    // Map building and sync handled in Task 6
  }, [textareaRef, previewRef])

  return { syncEnabled, toggleSync, onEditorScroll, onPreviewScroll }
}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd frontend && npx vitest run src/hooks/__tests__/useScrollSync.test.ts
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useScrollSync.ts frontend/src/hooks/__tests__/useScrollSync.test.ts
git commit -m "feat: add useScrollSync hook skeleton with toggle"
```

---

## Task 6: Map building and scroll handlers

**Files:**
- Modify: `frontend/src/hooks/useScrollSync.ts`
- Modify: `frontend/src/hooks/__tests__/useScrollSync.test.ts`

- [ ] **Step 1: Add scroll-sync accuracy tests**

Append to `frontend/src/hooks/__tests__/useScrollSync.test.ts`:

```typescript
describe('scroll sync position helpers (via hook behaviour)', () => {
  it('scrolling editor with sentinel data moves preview proportionally', () => {
    // Set up a textarea at scrollTop=0, a preview with a sentinel at offsetTop=100 for line 0
    const textarea = makeTextarea(0)
    const preview = makeDiv(0)

    // Inject a sentinel element into the preview div
    const sentinel = document.createElement('span')
    sentinel.id = 'agbpos-L0'
    Object.defineProperty(sentinel, 'offsetTop', { get: () => 0, configurable: true })
    preview.appendChild(sentinel)

    const previewScrollSetter = vi.fn()
    Object.defineProperty(preview, 'scrollTop', {
      get: () => 0,
      set: previewScrollSetter,
      configurable: true,
    })

    const { result } = renderHook(() =>
      useScrollSync({
        textareaRef: { current: textarea },
        previewRef: { current: preview },
        content: 'Hello world.',
      })
    )

    act(() => result.current.onEditorScroll())
    // With only one sentinel at top=0 and editor at scrollTop=0,
    // preview should be set to 0
    expect(previewScrollSetter).toHaveBeenCalledWith(0)
  })

  it('re-entrancy guard prevents feedback loop', () => {
    const textarea = makeTextarea(100)
    const preview = makeDiv(0)

    const previewScrollSetter = vi.fn()
    Object.defineProperty(preview, 'scrollTop', {
      get: () => 0,
      set: previewScrollSetter,
      configurable: true,
    })
    const textareaScrollSetter = vi.fn()
    Object.defineProperty(textarea, 'scrollTop', {
      get: () => 100,
      set: textareaScrollSetter,
      configurable: true,
    })

    const { result } = renderHook(() =>
      useScrollSync({
        textareaRef: { current: textarea },
        previewRef: { current: preview },
        content: 'Paragraph.',
      })
    )

    // Simulate editor scroll triggering preview scroll triggering editor scroll again
    act(() => {
      result.current.onEditorScroll()
      // Immediately call preview scroll (simulating the scroll event it fires)
      result.current.onPreviewScroll()
    })

    // textareaScrollSetter should NOT have been called (re-entrancy guard active)
    expect(textareaScrollSetter).not.toHaveBeenCalled()
    // But preview should have been set once from editor scroll
    expect(previewScrollSetter).toHaveBeenCalledTimes(1)
  })
})
```

- [ ] **Step 2: Run tests — verify the new tests fail**

```bash
cd frontend && npx vitest run src/hooks/__tests__/useScrollSync.test.ts 2>&1 | tail -20
```

- [ ] **Step 3: Implement map building and scroll handlers**

Replace the contents of `frontend/src/hooks/useScrollSync.ts` with the full implementation:

```typescript
import { useCallback, useEffect, useRef, useState } from 'react'

interface SentinelEntry {
  line: number
  top: number
}

interface SyncMap {
  editorLines: number[]
  sentinels: SentinelEntry[]
}

interface UseScrollSyncOptions {
  textareaRef: React.RefObject<HTMLTextAreaElement>
  previewRef: React.RefObject<HTMLDivElement>
  content: string
}

interface UseScrollSyncResult {
  syncEnabled: boolean
  toggleSync: () => void
  onEditorScroll: () => void
  onPreviewScroll: () => void
}

function setupMirror(mirror: HTMLDivElement, textarea: HTMLTextAreaElement): void {
  const cs = getComputedStyle(textarea)
  mirror.style.fontFamily = cs.fontFamily
  mirror.style.fontSize = cs.fontSize
  mirror.style.lineHeight = cs.lineHeight
  mirror.style.letterSpacing = cs.letterSpacing
  mirror.style.paddingTop = cs.paddingTop
  mirror.style.paddingRight = cs.paddingRight
  mirror.style.paddingBottom = cs.paddingBottom
  mirror.style.paddingLeft = cs.paddingLeft
  mirror.style.whiteSpace = 'pre-wrap'
  mirror.style.wordBreak = cs.wordBreak
  mirror.style.overflowWrap = cs.overflowWrap
  mirror.style.boxSizing = 'border-box'
  // clientWidth excludes the scrollbar so wrapping matches the textarea exactly
  mirror.style.width = textarea.clientWidth + 'px'
}

function buildSyncMap(
  textarea: HTMLTextAreaElement,
  preview: HTMLDivElement,
  mirror: HTMLDivElement,
  content: string,
): SyncMap {
  setupMirror(mirror, textarea)

  // Populate mirror with one div per source line
  const lines = content.split('\n')
  mirror.innerHTML = ''
  const fragment = document.createDocumentFragment()
  for (const line of lines) {
    const div = document.createElement('div')
    div.style.margin = '0'
    div.style.padding = '0'
    // Use a zero-width space so empty lines retain their line-height
    div.textContent = line.length > 0 ? line : '​'
    fragment.appendChild(div)
  }
  mirror.appendChild(fragment)

  const editorLines = Array.from(mirror.children).map(
    (child) => (child as HTMLElement).offsetTop,
  )

  const sentinelEls = preview.querySelectorAll<HTMLElement>('[id^="agbpos-L"]')
  const sentinels: SentinelEntry[] = Array.from(sentinelEls)
    .map((el) => ({
      line: parseInt(el.id.slice('agbpos-L'.length), 10),
      top: el.offsetTop,
    }))
    .sort((a, b) => a.line - b.line)

  return { editorLines, sentinels }
}

// Returns fractional line index for a given editor scrollTop
function editorScrollToLine(editorLines: number[], scrollTop: number): number {
  if (editorLines.length === 0) return 0
  let lo = 0
  let hi = editorLines.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (editorLines[mid] <= scrollTop) lo = mid
    else hi = mid - 1
  }
  const lineTop = editorLines[lo]
  const nextTop = editorLines[lo + 1]
  if (nextTop === undefined || nextTop <= lineTop) return lo
  return lo + Math.min(1, (scrollTop - lineTop) / (nextTop - lineTop))
}

// Returns preview scrollTop for a fractional line index
function lineToPreviewScroll(sentinels: SentinelEntry[], fractionalLine: number): number {
  if (sentinels.length === 0) return 0
  let lo = 0
  let hi = sentinels.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (sentinels[mid].line <= fractionalLine) lo = mid
    else hi = mid - 1
  }
  const s0 = sentinels[lo]
  const s1 = sentinels[lo + 1]
  if (!s1 || s1.line <= s0.line) return s0.top
  const t = Math.min(1, Math.max(0, (fractionalLine - s0.line) / (s1.line - s0.line)))
  return s0.top + t * (s1.top - s0.top)
}

// Returns fractional line index for a given preview scrollTop
function previewScrollToLine(sentinels: SentinelEntry[], scrollTop: number): number {
  if (sentinels.length === 0) return 0
  let lo = 0
  let hi = sentinels.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (sentinels[mid].top <= scrollTop) lo = mid
    else hi = mid - 1
  }
  const s0 = sentinels[lo]
  const s1 = sentinels[lo + 1]
  if (!s1 || s1.top <= s0.top) return s0.line
  const t = Math.min(1, Math.max(0, (scrollTop - s0.top) / (s1.top - s0.top)))
  return s0.line + t * (s1.line - s0.line)
}

// Returns editor scrollTop for a fractional line index
function lineToEditorScroll(editorLines: number[], fractionalLine: number): number {
  if (editorLines.length === 0) return 0
  const idx = Math.min(Math.floor(fractionalLine), editorLines.length - 1)
  const fraction = fractionalLine - Math.floor(fractionalLine)
  const lineTop = editorLines[idx]
  const nextTop = editorLines[idx + 1]
  if (nextTop === undefined) return lineTop
  return lineTop + fraction * (nextTop - lineTop)
}

export function useScrollSync({
  textareaRef,
  previewRef,
  content,
}: UseScrollSyncOptions): UseScrollSyncResult {
  const [syncEnabled, setSyncEnabled] = useState(true)
  const syncEnabledRef = useRef(syncEnabled)
  const mapRef = useRef<SyncMap | null>(null)
  const syncingRef = useRef(false)
  const mirrorRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    syncEnabledRef.current = syncEnabled
  }, [syncEnabled])

  // Invalidate map when content changes
  useEffect(() => {
    mapRef.current = null
  }, [content])

  // Create mirror div on mount
  useEffect(() => {
    const mirror = document.createElement('div')
    mirror.style.position = 'absolute'
    mirror.style.top = '-9999px'
    mirror.style.left = '-9999px'
    mirror.style.visibility = 'hidden'
    mirror.style.pointerEvents = 'none'
    document.body.appendChild(mirror)
    mirrorRef.current = mirror
    return () => {
      document.body.removeChild(mirror)
      mirrorRef.current = null
    }
  }, [])

  const getOrBuildMap = useCallback((): SyncMap | null => {
    if (mapRef.current) return mapRef.current
    const textarea = textareaRef.current
    const preview = previewRef.current
    const mirror = mirrorRef.current
    if (!textarea || !preview || !mirror) return null
    const map = buildSyncMap(textarea, preview, mirror, content)
    mapRef.current = map
    return map
  }, [textareaRef, previewRef, content])

  const toggleSync = useCallback(() => setSyncEnabled((s) => !s), [])

  const onEditorScroll = useCallback(() => {
    if (!syncEnabledRef.current || syncingRef.current) return
    const textarea = textareaRef.current
    const preview = previewRef.current
    if (!textarea || !preview) return
    const map = getOrBuildMap()
    if (!map) return
    const fractionalLine = editorScrollToLine(map.editorLines, textarea.scrollTop)
    const previewTop = lineToPreviewScroll(map.sentinels, fractionalLine)
    syncingRef.current = true
    preview.scrollTop = previewTop
    requestAnimationFrame(() => {
      syncingRef.current = false
    })
  }, [textareaRef, previewRef, getOrBuildMap])

  const onPreviewScroll = useCallback(() => {
    if (!syncEnabledRef.current || syncingRef.current) return
    const textarea = textareaRef.current
    const preview = previewRef.current
    if (!textarea || !preview) return
    const map = getOrBuildMap()
    if (!map) return
    const fractionalLine = previewScrollToLine(map.sentinels, preview.scrollTop)
    const editorTop = lineToEditorScroll(map.editorLines, fractionalLine)
    syncingRef.current = true
    textarea.scrollTop = editorTop
    requestAnimationFrame(() => {
      syncingRef.current = false
    })
  }, [textareaRef, previewRef, getOrBuildMap])

  return { syncEnabled, toggleSync, onEditorScroll, onPreviewScroll }
}
```

- [ ] **Step 4: Run all hook tests**

```bash
cd frontend && npx vitest run src/hooks/__tests__/useScrollSync.test.ts
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useScrollSync.ts frontend/src/hooks/__tests__/useScrollSync.test.ts
git commit -m "feat: implement scroll sync map building and bidirectional handlers"
```

---

## Task 7: Map invalidation + wire up in EditorPage

**Files:**
- Modify: `frontend/src/hooks/useScrollSync.ts` — ResizeObserver + image load invalidation
- Modify: `frontend/src/pages/EditorPage.tsx` — wire up hook

- [ ] **Step 1: Add ResizeObserver and image-load invalidation to the hook**

Add a new effect inside `useScrollSync`, after the mirror-creation effect:

```typescript
// Invalidate map on textarea container resize (width change breaks mirror measurements)
useEffect(() => {
  const textarea = textareaRef.current
  if (!textarea) return
  const observer = new ResizeObserver(() => {
    mapRef.current = null
  })
  observer.observe(textarea)
  return () => observer.disconnect()
}, [textareaRef])

// Invalidate map when images load inside the preview (they change offsetTop of everything below)
useEffect(() => {
  const preview = previewRef.current
  if (!preview) return

  const handleLoad = () => {
    mapRef.current = null
  }

  const attachToImages = () => {
    preview.querySelectorAll('img').forEach((img) => {
      img.removeEventListener('load', handleLoad)
      img.addEventListener('load', handleLoad)
    })
  }

  // Watch for new images added by React re-renders
  const mutationObserver = new MutationObserver(attachToImages)
  mutationObserver.observe(preview, { childList: true, subtree: true })
  attachToImages()

  return () => {
    mutationObserver.disconnect()
    preview.querySelectorAll('img').forEach((img) =>
      img.removeEventListener('load', handleLoad),
    )
  }
}, [previewRef])
```

- [ ] **Step 2: Wire up the hook in EditorPage**

At the top of `EditorPage`, add the import:

```typescript
import { useScrollSync } from '@/hooks/useScrollSync'
```

After the existing `previewRef` and `textareaRef` declarations, add:

```typescript
const { syncEnabled, toggleSync, onEditorScroll, onPreviewScroll } = useScrollSync({
  textareaRef,
  previewRef,
  content: body,
})
```

Pass `syncEnabled` and `toggleSync` to the toggle button:

```tsx
// Update the toggle button (from Task 4) to use hook state:
<button
  type="button"
  onClick={toggleSync}
  className={`inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-lg border transition-colors ${
    syncEnabled
      ? 'bg-accent/10 border-accent/30 text-accent'
      : 'bg-paper-warm border-border text-muted hover:text-ink'
  }`}
>
  ⇄ Sync
</button>
```

Add scroll handlers to the textarea and preview div:

```tsx
// On the textarea element, add:
onScroll={onEditorScroll}

// On the preview div, add:
onScroll={onPreviewScroll}
```

- [ ] **Step 3: Manual verification**

```bash
just start
```

Open `http://localhost:5173/editor/new` and test:
1. Type several paragraphs (no headings) long enough to scroll.
2. Wait for the preview to appear (500ms debounce).
3. Scroll the editor — the preview should follow.
4. Scroll the preview — the editor should follow.
5. Click "⇄ Sync" to disable — scroll editor, preview should NOT move.
6. Re-enable sync — scroll behaviour should resume.

```bash
just stop
```

- [ ] **Step 4: Run all frontend checks**

```bash
just check-frontend
```

Expected: all green (type-checked, linted, tests passing).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useScrollSync.ts frontend/src/pages/EditorPage.tsx
git commit -m "feat: wire up scroll sync hook with resize and image-load invalidation"
```

---

## Task 8: Full gate

- [ ] **Step 1: Run the full check**

```bash
just check
```

Expected: all green — static analysis, backend tests, frontend tests, coverage.

- [ ] **Step 2: Fix any issues and commit**

Address any type errors, lint warnings, or test failures. Commit fixes:

```bash
git add -p
git commit -m "fix: resolve check failures from scroll sync implementation"
```
