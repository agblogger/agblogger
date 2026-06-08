# Editor Scroll Sync Design

**Date:** 2026-06-08

## Goal

The post editor's textarea and preview pane should each have a fixed maximum height and scroll independently. A toggle lets the user synchronise their scroll positions so that scrolling one pane automatically moves the other to the corresponding position in the document.

## Constraints

- Pandoc `markdown` reader must not change (no `commonmark` switch, no `+sourcepos`).
- Pandoc server HTTP API does not accept Lua filters — no filter-based solution is possible.
- The sanitizer (`_HtmlSanitizer`) already allows `id` on all tags and `span` is an allowed tag — no sanitizer changes required.
- The editor is a plain `<textarea>` (no CodeMirror/Monaco).

## Approach: Server-injected sentinels + mirror div

### Why not the alternatives

- **Scroll percentage**: consistently inaccurate whenever images, code blocks, or tables create height mismatches between the two panes.
- **Heading-anchored sync**: useless for posts without headings, which is common.
- **Client-side DOM zipping**: positional zipping of textarea blocks to preview DOM children breaks silently whenever the JS block parser disagrees with Pandoc on block count (reference-link definitions, footnotes, loose lists produce no output element or are relocated).

### Chosen approach

Before rendering, the server injects a `<span id="agbpos-L{n}">` raw-HTML sentinel before each top-level markdown block, where `n` is the block's starting source line number. Pandoc renders these through unchanged. The frontend reads each sentinel's `offsetTop` to build a source-line → preview-pixel map. A hidden mirror div with identical CSS to the textarea provides the inverse map: source-line → editor-pixel.

## Backend

### `inject_scroll_sentinels(markdown: str) -> str`

New pure function in `backend/pandoc/renderer.py`. Scans the markdown line by line, tracking whether the cursor is inside a fenced code block (` ``` ` or `~~~`, of any length ≥ 3). Blank lines inside a fence are not block boundaries. At each transition from blank gap to non-blank content, the starting source line is recorded and a sentinel is prepended:

```
<span id="agbpos-L0"></span>

First paragraph.

<span id="agbpos-L2"></span>

Second paragraph.
```

Each sentinel is isolated by blank lines so Pandoc treats it as a standalone raw-HTML block rather than inline content merged into the following paragraph.

The `id` value `agbpos-L{n}` passes the sanitizer's `_SAFE_ID_RE` (`^[a-zA-Z][a-zA-Z0-9:_-]*$`) and survives DOMPurify (which allows `id` by default). No sanitizer changes needed.

### `render_markdown_preview(markdown: str) -> str`

New function that calls `inject_scroll_sentinels(markdown)` then `render_markdown(...)`. The existing `render_markdown` is unchanged and continues to be used for all non-preview paths.

### `/api/render/preview` endpoint

Calls `render_markdown_preview` instead of `render_markdown`. Response schema (`{"html": "..."}`) is unchanged — sentinels are embedded in the HTML.

## Frontend

### Layout changes (`EditorPage.tsx`)

- The `style={{ minHeight: '60vh' }}` inline style on the two-column grid container is removed.
- The editor column becomes `flex flex-col h-[80vh]`. `MarkdownToolbar` stays at its natural height; the `<textarea>` gets `flex-1 overflow-y-auto`, replacing `h-full min-h-[60vh]`.
- The preview column gets `h-[80vh]` alongside its existing `overflow-y-auto`.
- Both panes are now fixed-height and independently scrollable; the outer page scrolls to reveal metadata above.

### Sync toggle

A small `⇄ Sync` button is added in a right-aligned row directly above the two-column grid, desktop-only (hidden on mobile where only one pane is visible at a time). It is accent-coloured when sync is on, muted when off. Default state: on.

### `useScrollSync` hook (`frontend/src/hooks/useScrollSync.ts`)

**Interface:**
```typescript
interface UseScrollSyncOptions {
  textareaRef: RefObject<HTMLTextAreaElement>
  previewRef: RefObject<HTMLDivElement>
  content: string
}
interface UseScrollSyncResult {
  syncEnabled: boolean
  toggleSync: () => void
  onEditorScroll: () => void
  onPreviewScroll: () => void
}
```

**Internal state (all refs except `syncEnabled`):**
- `mapRef: SyncMap | null` — lazy-built position map, `null` means stale/not yet built.
- `syncingRef: boolean` — re-entrancy guard preventing scroll feedback loops.
- `mirrorRef: HTMLDivElement | null` — the hidden mirror div, created on mount and removed on unmount.

**`SyncMap` structure:**
```typescript
interface SyncMap {
  editorLines: number[]                      // index = source line, value = visual pixel top
  sentinels: { line: number; top: number }[] // sorted by line number
}
```

**Map building** (triggered lazily on first scroll after invalidation):

1. Mirror div CSS is copied from `getComputedStyle(textarea)` — `fontFamily`, `fontSize`, `lineHeight`, `letterSpacing`, `paddingTop/Right/Bottom/Left`, `wordBreak`, `overflowWrap`, `whiteSpace: pre-wrap`. Width is set to `textarea.clientWidth` (excludes scrollbar, so wrapping matches exactly).
2. Mirror div content: `content.split('\n')`, one `<div>` per source line. Each child div has `margin: 0; padding: 0` so source lines stack without added spacing. Read each div's `offsetTop` → `editorLines`.
3. `previewEl.querySelectorAll('[id^="agbpos-L"]')` → parse line number from each `id`, read `offsetTop` → `sentinels`.

**Scroll handler (editor → preview):**
1. Bail if sync off or `syncingRef` true.
2. Build map if null.
3. Binary-search `editorLines` for `textarea.scrollTop` → source line `N` + fractional offset within that line's visual height.
4. Find the bracketing sentinel pair for line `N`; interpolate to get `previewScrollTop`.
5. Set `syncingRef = true`, set `previewEl.scrollTop`, clear guard via `requestAnimationFrame`.

**Scroll handler (preview → editor):** symmetric.

**Map invalidation** — `mapRef.current = null` on:
- `content` prop change (effect).
- `ResizeObserver` on the textarea container (width change breaks mirror div measurements).
- `img` `load` events inside the preview (images shift all `offsetTop`s below them).
- `renderedPreview` change already covers KaTeX async re-render and post-render DOM mutations from `useCodeBlockEnhance`.

## Error handling

All sync failures are silent and non-destructive:
- If sentinel query returns no elements (preview not yet rendered, blank body), map building produces an empty sentinel array and scroll handlers are no-ops.
- If mirror div measurements fail, same result.
- Sync never affects saving, auto-save, or the rendered output shown to readers.

## Testing

### Backend

Property-based tests (Hypothesis) for `inject_scroll_sentinels`:
- Fenced code blocks containing blank lines: sentinels must not appear inside fences.
- Consecutive blank lines: treated as a single block boundary.
- Empty input, single-block input, input with only blank lines.
- Fence markers of varying lengths and styles (` ``` `, `~~~`, ` ```python `).
- Assert: sentinel `id` line numbers match actual source line positions of each block.

### Frontend

Unit tests for `useScrollSync`:
- Map is nulled on content change.
- `syncingRef` guard prevents the feedback loop (scrolling editor does not re-trigger editor scroll).
- Scroll handlers are no-ops when `syncEnabled` is false.

Playwright integration test:
- Open editor, type multi-paragraph content (no headings), scroll editor to bottom, assert preview `scrollTop` is non-zero and within a reasonable range of the preview's `scrollHeight`.
