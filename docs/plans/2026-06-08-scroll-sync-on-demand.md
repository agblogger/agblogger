# Editor Scroll Sync — On-Demand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken continuous auto-sync between editor and preview with two explicit on-demand sync buttons in a gutter column between the panes.

**Architecture:** The existing position-mapping infrastructure (backend sentinels, mirror div, piecewise-linear interpolation) is unchanged. The hook loses its scroll event handlers and toggle state; it gains two imperative `syncEditorToPreview` / `syncPreviewToEditor` functions. The editor grid gains a narrow center column holding the two `ChevronRight` / `ChevronLeft` gutter buttons.

**Tech Stack:** React 19, TypeScript (strict, `noUncheckedIndexedAccess`), Tailwind CSS, Vitest + `@testing-library/react`, lucide-react icons

---

## Files

| File | Action |
|------|--------|
| `frontend/src/hooks/useScrollSync.ts` | Modify — remove continuous sync; expose two imperative sync functions |
| `frontend/src/hooks/__tests__/useScrollSync.test.ts` | Modify — replace all tests to match new API |
| `frontend/src/pages/EditorPage.tsx` | Modify — 3-col grid, gutter buttons, remove toggle row and `onScroll` props |

Backend files are **not touched**.

---

### Task 1: Refactor `useScrollSync` hook

**Files:**
- Modify: `frontend/src/hooks/useScrollSync.ts`
- Test: `frontend/src/hooks/__tests__/useScrollSync.test.ts`

**Context:** The hook currently exposes `{ syncEnabled, toggleSync, onEditorScroll, onPreviewScroll }` and uses scroll event listeners for continuous bidirectional sync. This causes ghostly scrolling artifacts. We replace it with two one-shot functions. The position-mapping helpers (`editorScrollToLine`, `lineToPreviewScroll`, `previewScrollToLine`, `lineToEditorScroll`) and infrastructure (`buildSyncMap`, `setupMirror`, ResizeObserver, MutationObserver, mirror div) all stay unchanged.

Run tests with: `just test-frontend`
Check static analysis with: `just check-frontend`

- [ ] **Step 1: Replace the test file**

Replace the entire contents of `frontend/src/hooks/__tests__/useScrollSync.test.ts` with:

```typescript
import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
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
  it('exposes syncEditorToPreview and syncPreviewToEditor functions', () => {
    const { result } = renderHook(() =>
      useScrollSync({
        textareaRef: { current: null },
        previewRef: { current: null },
        content: '',
      })
    )
    expect(typeof result.current.syncEditorToPreview).toBe('function')
    expect(typeof result.current.syncPreviewToEditor).toBe('function')
  })

  it('syncEditorToPreview is a no-op when refs are null', () => {
    const { result } = renderHook(() =>
      useScrollSync({
        textareaRef: { current: null },
        previewRef: { current: null },
        content: '',
      })
    )
    expect(() => result.current.syncEditorToPreview()).not.toThrow()
  })

  it('syncPreviewToEditor is a no-op when refs are null', () => {
    const { result } = renderHook(() =>
      useScrollSync({
        textareaRef: { current: null },
        previewRef: { current: null },
        content: '',
      })
    )
    expect(() => result.current.syncPreviewToEditor()).not.toThrow()
  })
})

describe('sync position helpers (via hook behaviour)', () => {
  it('syncEditorToPreview sets preview.scrollTop based on editor position', () => {
    const textarea = makeTextarea(0)
    const preview = makeDiv(0)

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

    act(() => result.current.syncEditorToPreview())
    expect(previewScrollSetter).toHaveBeenCalledWith(0)
  })

  it('syncPreviewToEditor sets textarea.scrollTop based on preview position', () => {
    const textarea = makeTextarea(0)
    const preview = makeDiv(0)

    const sentinel = document.createElement('span')
    sentinel.id = 'agbpos-L0'
    Object.defineProperty(sentinel, 'offsetTop', { get: () => 0, configurable: true })
    preview.appendChild(sentinel)

    const textareaScrollSetter = vi.fn()
    Object.defineProperty(textarea, 'scrollTop', {
      get: () => 0,
      set: textareaScrollSetter,
      configurable: true,
    })

    const { result } = renderHook(() =>
      useScrollSync({
        textareaRef: { current: textarea },
        previewRef: { current: preview },
        content: 'Hello world.',
      })
    )

    act(() => result.current.syncPreviewToEditor())
    expect(textareaScrollSetter).toHaveBeenCalledWith(0)
  })
})
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
just test-frontend
```

Expected: tests fail because the hook still exports the old API (`syncEnabled`, `toggleSync`, etc.) instead of the new one.

- [ ] **Step 3: Replace the hook implementation**

Replace the entire contents of `frontend/src/hooks/useScrollSync.ts` with:

```typescript
import { type RefObject, useCallback, useEffect, useRef } from 'react'

interface SentinelEntry {
  line: number
  top: number
}

interface SyncMap {
  editorLines: number[]
  sentinels: SentinelEntry[]
}

interface UseScrollSyncOptions {
  textareaRef: RefObject<HTMLTextAreaElement | null>
  previewRef: RefObject<HTMLDivElement | null>
  content: string
}

interface UseScrollSyncResult {
  syncEditorToPreview: () => void
  syncPreviewToEditor: () => void
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
  mirror.style.width = `${textarea.clientWidth}px`
}

function buildSyncMap(
  textarea: HTMLTextAreaElement,
  preview: HTMLDivElement,
  mirror: HTMLDivElement,
  content: string,
): SyncMap {
  setupMirror(mirror, textarea)

  const lines = content.split('\n')
  mirror.innerHTML = ''
  const fragment = document.createDocumentFragment()
  for (const line of lines) {
    const div = document.createElement('div')
    div.style.margin = '0'
    div.style.padding = '0'
    // Zero-width space so empty lines retain their line-height
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

function editorScrollToLine(editorLines: number[], scrollTop: number): number {
  if (editorLines.length === 0) return 0
  let lo = 0
  let hi = editorLines.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if ((editorLines[mid] ?? 0) <= scrollTop) lo = mid
    else hi = mid - 1
  }
  const lineTop = editorLines[lo]
  if (lineTop === undefined) return lo
  const nextTop = editorLines[lo + 1]
  if (nextTop === undefined || nextTop <= lineTop) return lo
  return lo + Math.min(1, (scrollTop - lineTop) / (nextTop - lineTop))
}

function lineToPreviewScroll(sentinels: SentinelEntry[], fractionalLine: number): number {
  if (sentinels.length === 0) return 0
  let lo = 0
  let hi = sentinels.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if ((sentinels[mid]?.line ?? 0) <= fractionalLine) lo = mid
    else hi = mid - 1
  }
  const s0 = sentinels[lo]
  if (!s0) return 0
  const s1 = sentinels[lo + 1]
  if (!s1 || s1.line <= s0.line) return s0.top
  const t = Math.min(1, Math.max(0, (fractionalLine - s0.line) / (s1.line - s0.line)))
  return s0.top + t * (s1.top - s0.top)
}

function previewScrollToLine(sentinels: SentinelEntry[], scrollTop: number): number {
  if (sentinels.length === 0) return 0
  let lo = 0
  let hi = sentinels.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if ((sentinels[mid]?.top ?? 0) <= scrollTop) lo = mid
    else hi = mid - 1
  }
  const s0 = sentinels[lo]
  if (!s0) return 0
  const s1 = sentinels[lo + 1]
  if (!s1 || s1.top <= s0.top) return s0.line
  const t = Math.min(1, Math.max(0, (scrollTop - s0.top) / (s1.top - s0.top)))
  return s0.line + t * (s1.line - s0.line)
}

function lineToEditorScroll(editorLines: number[], fractionalLine: number): number {
  if (editorLines.length === 0) return 0
  const floorIdx = Math.floor(fractionalLine)
  const idx = Math.min(floorIdx, editorLines.length - 1)
  const fraction = fractionalLine - floorIdx
  const lineTop = editorLines[idx] ?? 0
  const nextTop = editorLines[idx + 1]
  if (nextTop === undefined) return lineTop
  return lineTop + fraction * (nextTop - lineTop)
}

export function useScrollSync({
  textareaRef,
  previewRef,
  content,
}: UseScrollSyncOptions): UseScrollSyncResult {
  const mapRef = useRef<SyncMap | null>(null)
  const mirrorRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    mapRef.current = null
  }, [content])

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

  useEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) return
    const observer = new ResizeObserver(() => {
      mapRef.current = null
    })
    observer.observe(textarea)
    return () => observer.disconnect()
  }, [textareaRef])

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
        if (img.complete) handleLoad()
      })
    }

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

  const syncEditorToPreview = useCallback(() => {
    const textarea = textareaRef.current
    const preview = previewRef.current
    if (!textarea || !preview) return
    const map = getOrBuildMap()
    if (!map) return
    const fractionalLine = editorScrollToLine(map.editorLines, textarea.scrollTop)
    preview.scrollTop = lineToPreviewScroll(map.sentinels, fractionalLine)
  }, [textareaRef, previewRef, getOrBuildMap])

  const syncPreviewToEditor = useCallback(() => {
    const textarea = textareaRef.current
    const preview = previewRef.current
    if (!textarea || !preview) return
    const map = getOrBuildMap()
    if (!map) return
    const fractionalLine = previewScrollToLine(map.sentinels, preview.scrollTop)
    textarea.scrollTop = lineToEditorScroll(map.editorLines, fractionalLine)
  }, [textareaRef, previewRef, getOrBuildMap])

  return { syncEditorToPreview, syncPreviewToEditor }
}
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
just test-frontend
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useScrollSync.ts frontend/src/hooks/__tests__/useScrollSync.test.ts
git commit -m "refactor: replace continuous scroll sync with on-demand sync functions"
```

---

### Task 2: Update `EditorPage` layout

**Files:**
- Modify: `frontend/src/pages/EditorPage.tsx`

**Context:** The page currently has a "⇄ Sync" toggle div above the grid (lines ~573–587) and a 2-column grid (`lg:grid-cols-2`). We remove the toggle, change the grid to 3-column with an explicit gutter, insert the gutter column with two icon buttons between the editor and preview columns, and remove `onScroll` props from the textarea and preview div. No new tests are needed — the hook tests cover sync logic, and EditorPage has no unit tests.

- [ ] **Step 1: Update the lucide-react import**

In `frontend/src/pages/EditorPage.tsx`, line 3, change:

```typescript
import { Save, ArrowLeft, Eye } from 'lucide-react'
```

to:

```typescript
import { Save, ArrowLeft, Eye, ChevronRight, ChevronLeft } from 'lucide-react'
```

- [ ] **Step 2: Update the useScrollSync destructuring**

Change line ~60:

```typescript
  const { syncEnabled, toggleSync, onEditorScroll, onPreviewScroll } = useScrollSync({
    textareaRef,
    previewRef,
    content: body,
  })
```

to:

```typescript
  const { syncEditorToPreview, syncPreviewToEditor } = useScrollSync({
    textareaRef,
    previewRef,
    content: body,
  })
```

- [ ] **Step 3: Remove the sync toggle div and update the grid**

Remove the entire `{/* Scroll sync toggle — desktop only */}` block (the `<div className="hidden lg:flex justify-end mb-2">...</div>`).

Change the grid opening tag from:

```tsx
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
```

to:

```tsx
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_2.5rem_1fr] gap-4">
```

- [ ] **Step 4: Add the gutter column and remove onScroll props**

After the editor column's closing `</div>` and before the preview column's `<div ref={previewRef} ...>`, insert the gutter column:

```tsx
        <div className="hidden lg:flex flex-col items-center justify-center gap-2">
          <button
            type="button"
            onClick={syncEditorToPreview}
            title="Go to editor position in preview"
            aria-label="Go to editor position in preview"
            className="p-1.5 text-muted hover:text-ink hover:bg-paper-warm rounded transition-colors"
          >
            <ChevronRight size={16} />
          </button>
          <button
            type="button"
            onClick={syncPreviewToEditor}
            title="Go to preview position in editor"
            aria-label="Go to preview position in editor"
            className="p-1.5 text-muted hover:text-ink hover:bg-paper-warm rounded transition-colors"
          >
            <ChevronLeft size={16} />
          </button>
        </div>
```

Remove `onScroll={onEditorScroll}` from the `<textarea>` element.

Remove `onScroll={onPreviewScroll}` from the preview `<div>`.

- [ ] **Step 5: Verify static analysis passes**

```bash
just check-frontend
```

Expected: no TypeScript, ESLint, or test errors. (If `syncEnabled` or `toggleSync` are still referenced anywhere, ESLint will flag them — search for both and remove any remaining references.)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/EditorPage.tsx
git commit -m "feat: replace sync toggle with on-demand gutter buttons"
```

---

### Task 3: Full gate

**Files:** none

- [ ] **Step 1: Run the full check**

```bash
just check
```

Expected: all static checks and tests pass with no errors.

- [ ] **Step 2: Commit if any fixes were needed**

If `just check` required any fixes, commit them:

```bash
git add -p
git commit -m "fix: address just check failures in scroll sync on-demand"
```
