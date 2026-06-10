# Toolbar Overflow Dropdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an overflow `…` button to the markdown editor toolbar so formatting buttons that don't fit in the available width are accessible via a dropdown, while Save and Fullscreen always remain visible on the right.

**Architecture:** All changes are confined to `MarkdownToolbar.tsx`. A `ResizeObserver` on the toolbar container fires `computeOverflow` on mount and on every resize; it sums button `offsetWidth`s left-to-right against the available space and records the first index that doesn't fit as `overflowFrom`. Buttons at `overflowFrom` and beyond are hidden inline (`visibility: hidden`) and rendered as clickable items in an absolute-positioned dropdown. A guard (`availableWidth <= 0`) keeps everything visible in JSDOM where all measurements return 0, so existing tests continue to work without changes.

**Tech Stack:** React (hooks: `useState`, `useEffect`, `useCallback`, `useRef`), ResizeObserver, lucide-react (`Ellipsis` icon), Tailwind CSS, Vitest + @testing-library/react.

---

## Files

- **Modify:** `frontend/src/components/editor/MarkdownToolbar.tsx` — all implementation changes
- **Modify:** `frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx` — new `overflow dropdown` describe block + updated imports

---

## Task 1: Write failing overflow tests

**Files:**
- Modify: `frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx`

- [ ] **Step 1: Add `act` to the @testing-library/react import**

Change line 1 from:
```tsx
import { render, screen } from '@testing-library/react'
```
to:
```tsx
import { render, screen, act } from '@testing-library/react'
```

- [ ] **Step 2: Append the new describe block at the end of the file (before the closing `}` of the outer describe, or as a new top-level describe)**

Add this entire block after the last `it(...)` in the `MarkdownToolbar` describe (before the final `})`):

```tsx
  describe('overflow dropdown', () => {
    let capturedObserver!: ResizeObserverCallback

    beforeEach(() => {
      vi.stubGlobal(
        'ResizeObserver',
        vi.fn().mockImplementation((cb: ResizeObserverCallback) => {
          capturedObserver = cb
          return { observe: vi.fn(), disconnect: vi.fn(), unobserve: vi.fn() }
        }),
      )
    })

    afterEach(() => {
      vi.unstubAllGlobals()
    })

    // Sets container offsetWidth=120, all buttons/separators to 28px each.
    // GAP=4. availableWidth = 120 - 28(overflowBtn) - 0(rightGroup) - 8(2×gap) = 84.
    // Bold(28+4=32, sum=32 ≤ 84 ✓), Italic(sum=64 ≤ 84 ✓), Underline(sum=96 > 84 ✗)
    // → overflowFrom=2 (Underline and everything after it overflows)
    function makeNarrow(toolbarEl: HTMLElement) {
      Object.defineProperty(toolbarEl, 'offsetWidth', { configurable: true, value: 120 })
      toolbarEl.querySelectorAll('button, [role="separator"]').forEach((el) => {
        Object.defineProperty(el, 'offsetWidth', { configurable: true, value: 28 })
      })
      act(() => capturedObserver([], {} as ResizeObserver))
    }

    it('overflow button is hidden when all buttons fit', () => {
      const ref = createRef<HTMLTextAreaElement>()
      const { container } = render(<MarkdownToolbar textareaRef={ref} value="" onChange={() => {}} />)
      const toolbarEl = container.firstChild as HTMLElement
      const btn = toolbarEl.querySelector('[aria-label="More formatting options"]') as HTMLElement
      expect(btn).not.toBeNull()
      expect(btn.style.visibility).toBe('hidden')
    })

    it('overflow button becomes visible when container is narrow', () => {
      const ref = createRef<HTMLTextAreaElement>()
      const { container } = render(<MarkdownToolbar textareaRef={ref} value="" onChange={() => {}} />)
      makeNarrow(container.firstChild as HTMLElement)
      expect(screen.getByLabelText('More formatting options')).toBeInTheDocument()
    })

    it('clicking overflow button opens dropdown with overflow items', async () => {
      const user = userEvent.setup()
      const ref = createRef<HTMLTextAreaElement>()
      const { container } = render(
        <MarkdownToolbar textareaRef={ref} value="" onChange={() => {}} />,
      )
      makeNarrow(container.firstChild as HTMLElement)
      await user.click(screen.getByLabelText('More formatting options'))
      expect(screen.getByRole('menu')).toBeInTheDocument()
      // Underline (index 2) is the first overflow item
      expect(screen.getByRole('menuitem', { name: 'Underline' })).toBeInTheDocument()
    })

    it('clicking dropdown item fires action and closes dropdown', async () => {
      const onChange = vi.fn()
      const user = userEvent.setup()
      const textarea = document.createElement('textarea')
      textarea.value = 'hello world'
      textarea.selectionStart = 6
      textarea.selectionEnd = 11
      const ref = { current: textarea }
      const { container } = render(
        <MarkdownToolbar textareaRef={ref} value="hello world" onChange={onChange} />,
      )
      makeNarrow(container.firstChild as HTMLElement)
      await user.click(screen.getByLabelText('More formatting options'))
      await user.click(screen.getByRole('menuitem', { name: 'Underline' }))
      expect(onChange).toHaveBeenCalledWith('hello [world]{.underline}')
      expect(screen.queryByRole('menu')).toBeNull()
    })

    it('clicking outside the dropdown closes it', async () => {
      const user = userEvent.setup()
      const ref = createRef<HTMLTextAreaElement>()
      const { container } = render(
        <MarkdownToolbar textareaRef={ref} value="" onChange={() => {}} />,
      )
      makeNarrow(container.firstChild as HTMLElement)
      await user.click(screen.getByLabelText('More formatting options'))
      expect(screen.getByRole('menu')).toBeInTheDocument()
      await user.click(document.body)
      expect(screen.queryByRole('menu')).toBeNull()
    })

    it('pressing Escape closes the dropdown', async () => {
      const user = userEvent.setup()
      const ref = createRef<HTMLTextAreaElement>()
      const { container } = render(
        <MarkdownToolbar textareaRef={ref} value="" onChange={() => {}} />,
      )
      makeNarrow(container.firstChild as HTMLElement)
      await user.click(screen.getByLabelText('More formatting options'))
      expect(screen.getByRole('menu')).toBeInTheDocument()
      await user.keyboard('{Escape}')
      expect(screen.queryByRole('menu')).toBeNull()
    })

    it('save and fullscreen are always rendered regardless of overflow', () => {
      const ref = createRef<HTMLTextAreaElement>()
      const { container } = render(
        <MarkdownToolbar
          textareaRef={ref}
          value=""
          onChange={() => {}}
          onSave={vi.fn()}
          onToggleFullscreen={vi.fn()}
        />,
      )
      makeNarrow(container.firstChild as HTMLElement)
      expect(screen.getByLabelText('Save')).toBeInTheDocument()
      expect(screen.getByLabelText('Enter fullscreen')).toBeInTheDocument()
    })
  })
```

- [ ] **Step 3: Run the new tests to verify they fail**

```bash
cd /Users/lukasz/dev/agblogger && just test-frontend 2>&1 | grep -A3 "overflow dropdown"
```

Expected: the 7 new tests fail (the overflow button doesn't exist yet, ResizeObserver isn't used yet, etc.)

---

## Task 2: Implement overflow detection and dropdown

**Files:**
- Modify: `frontend/src/components/editor/MarkdownToolbar.tsx`

- [ ] **Step 1: Update the import block**

Replace:
```tsx
import {
  Bold, Italic, Underline, Strikethrough, Highlighter,
  Heading2, Heading3, Heading4,
  List, ListOrdered,
  Link, ImagePlus, Youtube,
  TextQuote, Code, FileCode,
  Sigma, Pi,
  Superscript, StickyNote,
  Save, Maximize2, Minimize2,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { memo } from 'react'
import type { RefObject } from 'react'
```

With:
```tsx
import {
  Bold, Italic, Underline, Strikethrough, Highlighter,
  Heading2, Heading3, Heading4,
  List, ListOrdered,
  Link, ImagePlus, Youtube,
  TextQuote, Code, FileCode,
  Sigma, Pi,
  Superscript, StickyNote,
  Save, Maximize2, Minimize2,
  Ellipsis,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { memo, useState, useEffect, useCallback, useRef } from 'react'
import type { RefObject } from 'react'
```

- [ ] **Step 2: Add the GAP constant after the `mod` constant**

After the line:
```tsx
const mod = isMac ? 'Cmd' : 'Ctrl'
```

Add:
```tsx
const GAP = 4 // matches gap-1 in Tailwind (4px)
```

- [ ] **Step 3: Replace the component body up to the return statement**

Replace everything from `export default memo(function MarkdownToolbar(` up to (but not including) `return (` with the following. This adds refs, state, `computeOverflow`, and two effects.

```tsx
export default memo(function MarkdownToolbar({
  textareaRef,
  value,
  onChange,
  disabled,
  onImageClick,
  imageUploading,
  imageDisabledReason,
  onSave,
  saving = false,
  canSave = true,
  isFullscreen = false,
  onToggleFullscreen,
}: MarkdownToolbarProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const itemRefs = useRef<(HTMLElement | null)[]>([])
  const overflowBtnRef = useRef<HTMLButtonElement>(null)
  const rightGroupRef = useRef<HTMLDivElement>(null)

  const [overflowFrom, setOverflowFrom] = useState(items.length)
  const [dropdownOpen, setDropdownOpen] = useState(false)

  const computeOverflow = useCallback(() => {
    const container = containerRef.current
    if (!container) return
    const availableWidth =
      container.offsetWidth -
      (rightGroupRef.current?.offsetWidth ?? 0) -
      (overflowBtnRef.current?.offsetWidth ?? 0) -
      GAP * 2
    if (availableWidth <= 0) {
      setOverflowFrom(items.length)
      return
    }
    let sum = 0
    let newOverflowFrom = items.length
    for (let i = 0; i < items.length; i++) {
      const el = itemRefs.current[i]
      if (!el) continue
      const w = el.offsetWidth + GAP
      if (sum + w > availableWidth) {
        newOverflowFrom = i
        break
      }
      sum += w
    }
    setOverflowFrom(newOverflowFrom)
  }, [])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    computeOverflow()
    const observer = new ResizeObserver(computeOverflow)
    observer.observe(container)
    return () => observer.disconnect()
  }, [computeOverflow])

  useEffect(() => {
    if (!dropdownOpen) return
    function onMouseDown(e: MouseEvent) {
      if (overflowBtnRef.current?.contains(e.target as Node)) return
      setDropdownOpen(false)
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') setDropdownOpen(false)
    }
    document.addEventListener('mousedown', onMouseDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onMouseDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [dropdownOpen])

  function handleAction(key: string) {
    if (key === 'image') return
    const textarea = textareaRef.current
    if (!textarea) return

    const action = actions[key]
    if (action === undefined) return
    const { newValue, cursorStart, cursorEnd } = wrapSelection(
      value,
      textarea.selectionStart,
      textarea.selectionEnd,
      action,
    )

    onChange(newValue)

    requestAnimationFrame(() => {
      textarea.focus()
      textarea.setSelectionRange(cursorStart, cursorEnd)
    })
  }

  function imageTitle(shortcut: string): string {
    if (imageDisabledReason !== undefined) return imageDisabledReason
    if (imageUploading === true) return 'Uploading...'
    return `Image (${shortcut})`
  }

  const saveDisabled = (disabled ?? false) || saving || !canSave

  // Determine dropdown range: overflow items with leading/trailing separators trimmed
  let dropdownFirstBtn = -1
  let dropdownLastBtn = -1
  for (let i = overflowFrom; i < items.length; i++) {
    if (!('separator' in items[i])) {
      if (dropdownFirstBtn === -1) dropdownFirstBtn = i
      dropdownLastBtn = i
    }
  }
```

- [ ] **Step 4: Replace the return statement with the new JSX**

Replace the entire `return (...)` block (from `return (` to the final `}`) with:

```tsx
  return (
    <div ref={containerRef} className="relative flex items-center gap-1 mb-2">
      {items.map((item, i) => {
        const isOverflow = i >= overflowFrom
        if ('separator' in item) {
          return (
            <div
              key={`sep-${i}`}
              role="separator"
              ref={(el) => { itemRefs.current[i] = el }}
              className="w-px h-4 bg-border mx-0.5 flex-shrink-0"
              style={isOverflow ? { visibility: 'hidden', pointerEvents: 'none' } : undefined}
            />
          )
        }

        const { key, label, Icon, shortcut } = item
        const isImage = key === 'image'
        const isDisabled = isImage
          ? (disabled ?? false) || imageDisabledReason !== undefined || onImageClick === undefined || imageUploading === true
          : disabled
        const title = isImage
          ? imageTitle(shortcut ?? '')
          : shortcut !== undefined ? `${label} (${shortcut})` : label
        const ariaLabel = shortcut !== undefined ? `${label} (${shortcut})` : label

        if (isImage && onImageClick === undefined && imageDisabledReason === undefined) {
          return null
        }

        return (
          <button
            key={key}
            ref={(el) => { itemRefs.current[i] = el }}
            type="button"
            onClick={() => (isImage ? onImageClick?.() : handleAction(key))}
            disabled={isDisabled}
            className={`p-1.5 text-muted hover:text-ink hover:bg-paper-warm rounded transition-colors
                     disabled:opacity-50 disabled:cursor-not-allowed${
                       isImage && imageUploading === true ? ' animate-pulse' : ''
                     }`}
            title={title}
            aria-label={ariaLabel}
            style={isOverflow ? { visibility: 'hidden', pointerEvents: 'none' } : undefined}
          >
            <Icon size={16} />
          </button>
        )
      })}

      <div className="relative">
        <button
          ref={overflowBtnRef}
          type="button"
          disabled={disabled}
          onClick={() => setDropdownOpen((o) => !o)}
          className="p-1.5 text-muted hover:text-ink hover:bg-paper-warm rounded transition-colors
                     disabled:opacity-50 disabled:cursor-not-allowed"
          title="More"
          aria-label="More formatting options"
          aria-expanded={dropdownOpen}
          style={{ visibility: overflowFrom < items.length ? 'visible' : 'hidden' }}
        >
          <Ellipsis size={16} />
        </button>

        {dropdownOpen && dropdownFirstBtn !== -1 && (
          <div
            className="absolute right-0 top-full mt-1 z-50 min-w-[160px] rounded-md border border-border bg-paper shadow-md py-1"
            role="menu"
          >
            {Array.from({ length: dropdownLastBtn - dropdownFirstBtn + 1 }, (_, j) => {
              const idx = dropdownFirstBtn + j
              const dropItem = items[idx]
              if ('separator' in dropItem) {
                return <hr key={`dsep-${idx}`} className="my-1 border-border" />
              }
              const { key, label, Icon, shortcut } = dropItem
              const isImage = key === 'image'
              const isDisabled = isImage
                ? (disabled ?? false) || imageDisabledReason !== undefined || onImageClick === undefined || imageUploading === true
                : disabled
              const title = isImage
                ? imageTitle(shortcut ?? '')
                : shortcut !== undefined ? `${label} (${shortcut})` : label
              if (isImage && onImageClick === undefined && imageDisabledReason === undefined) {
                return null
              }
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => {
                    if (isImage) {
                      onImageClick?.()
                    } else {
                      handleAction(key)
                    }
                    setDropdownOpen(false)
                  }}
                  disabled={isDisabled}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-sm text-ink
                             hover:bg-paper-warm disabled:opacity-50 disabled:cursor-not-allowed"
                  title={title}
                  aria-label={label}
                  role="menuitem"
                >
                  <Icon size={14} />
                  <span>{label}</span>
                </button>
              )
            })}
          </div>
        )}
      </div>

      {(onSave !== undefined || onToggleFullscreen !== undefined) && (
        <div ref={rightGroupRef} className="ml-auto flex items-center gap-1 flex-shrink-0">
          {onSave !== undefined && (
            <button
              type="button"
              onClick={() => onSave()}
              disabled={saveDisabled}
              className={`p-1.5 text-muted hover:text-ink hover:bg-paper-warm rounded transition-colors
                       disabled:opacity-50 disabled:cursor-not-allowed${saving ? ' animate-pulse' : ''}`}
              title={saving ? 'Saving...' : `Save (${mod}+S)`}
              aria-label="Save"
            >
              <Save size={16} />
            </button>
          )}
          {onToggleFullscreen !== undefined && (
            <button
              type="button"
              onClick={() => onToggleFullscreen()}
              disabled={disabled}
              className="p-1.5 text-muted hover:text-ink hover:bg-paper-warm rounded transition-colors
                       disabled:opacity-50 disabled:cursor-not-allowed"
              title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
              aria-label={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
            >
              {isFullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
            </button>
          )}
        </div>
      )}
    </div>
  )
})
```

---

## Task 3: Run all tests and fix any issues

- [ ] **Step 1: Run the full frontend test suite**

```bash
cd /Users/lukasz/dev/agblogger && just test-frontend 2>&1 | tail -40
```

Expected: all tests pass. The new overflow tests now pass; all existing tests still pass.

If any existing test fails, the most likely cause is a TypeScript error in the ref callback types (`(HTMLButtonElement | null)` assigned to `(HTMLElement | null)[]` — both extend `HTMLElement`, which is compatible). Fix by adjusting the ref type in the `itemRefs` declaration if needed.

- [ ] **Step 2: Run static checks**

```bash
cd /Users/lukasz/dev/agblogger && just check-frontend 2>&1 | tail -20
```

Expected: no TypeScript or ESLint errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/editor/MarkdownToolbar.tsx \
        frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx
git commit -m "feat: add overflow dropdown to editor toolbar"
```

---

## Task 4: Verify in browser

- [ ] **Step 1: Start the dev server**

```bash
just start && just health
```

- [ ] **Step 2: Open the editor and test the overflow behavior**

Navigate to a post's edit page. Narrow the browser window until the toolbar overflows. Verify:
- The `…` button appears between the last visible formatting button and Save/Fullscreen.
- Clicking `…` opens a vertical dropdown with labelled buttons.
- Clicking a dropdown item applies the formatting.
- Clicking outside or pressing Escape closes the dropdown.
- Save and Fullscreen remain visible at all widths.
- Widening the window restores buttons to the inline toolbar and hides `…`.

- [ ] **Step 3: Stop the dev server**

```bash
just stop
```
