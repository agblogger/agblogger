# Reusable Markdown Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the markdown editing surface into one reusable `MarkdownEditor` component and use it for both post editing (`EditorPage`) and page editing (`PagesSection`).

**Architecture:** A controlled component (`value`/`onChange`) owns the toolbar (formatting + save + fullscreen), textarea, debounced live preview, editor↔preview scroll sync, keyboard shortcuts, mobile edit/preview tabs, the fullscreen overlay, and all asset handling (opt-in). Hosts keep metadata, autosave, the `onSave` handler, and error banners. The duplicated debounced-preview logic is pulled into a single `useMarkdownPreview` hook.

**Tech Stack:** React 19 + TypeScript, Tailwind (semantic tokens), Vitest + Testing Library, SWR, lucide-react icons. Backend renders/sanitizes preview HTML via `render/preview`.

**Reference spec:** `docs/specs/2026-06-09-reusable-markdown-editor-design.md`

---

## Conventions (read once)

- Run frontend tests with `just test-frontend`; a single file with `cd frontend && npx vitest run <path>` (read-only commands; `just` preferred for the full gate).
- Test environment (`frontend/src/test/setup.ts`) **fails any test that logs `console.error`/`console.warn`**. For tests that exercise an error path, suppress with `vi.spyOn(console, 'error').mockImplementation(() => {})` inside that test.
- `ResizeObserver` is stubbed globally in the setup file.
- Tailwind responsive classes (`lg:`, `hidden`) are static strings and cannot be asserted via computed layout in jsdom — assert presence/state, not pixel visibility.
- Path alias `@/` → `frontend/src/`.
- Keep each test < 1s. Coverage gate: 80% statements/functions/lines, 70% branches.

## File Structure

- **Create** `frontend/src/hooks/useMarkdownPreview.ts` — debounced `render/preview` fetch + KaTeX hydration + code-block enhancement. One responsibility: turn markdown into ready-to-mount preview HTML.
- **Create** `frontend/src/hooks/__tests__/useMarkdownPreview.test.ts`
- **Modify** `frontend/src/components/editor/MarkdownToolbar.tsx` — add save + fullscreen buttons.
- **Modify** `frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx`
- **Create** `frontend/src/components/editor/MarkdownEditor.tsx` — the reusable editing surface.
- **Create** `frontend/src/components/editor/__tests__/MarkdownEditor.test.tsx`
- **Modify** `frontend/src/pages/EditorPage.tsx` — consume `MarkdownEditor`; drop ~250 lines.
- **Modify** `frontend/src/pages/__tests__/EditorPage.test.tsx` — keep green.
- **Modify** `frontend/src/components/admin/PagesSection.tsx` — consume `MarkdownEditor`; delete `PagePreview`.
- **Create** `frontend/src/components/admin/__tests__/PagesSection.test.tsx`
- **Modify** `docs/arch/frontend.md`; **Create** `docs/arch/editor.md`.

---

## Task 1: `useMarkdownPreview` hook

**Files:**
- Create: `frontend/src/hooks/useMarkdownPreview.ts`
- Test: `frontend/src/hooks/__tests__/useMarkdownPreview.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/hooks/__tests__/useMarkdownPreview.test.ts`:

```ts
import { renderHook, waitFor, act } from '@testing-library/react'
import { createRef } from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

import api from '@/api/client'
import { useMarkdownPreview } from '../useMarkdownPreview'

vi.mock('@/api/client', () => ({ default: { post: vi.fn() } }))
// KaTeX + code-enhance are exercised elsewhere; isolate the fetch/debounce logic.
vi.mock('@/hooks/useKatex', () => ({ useRenderedHtml: (h: string | null) => h ?? '' }))
vi.mock('@/hooks/useCodeBlockEnhance', () => ({ useCodeBlockEnhance: () => {} }))

const mockPost = vi.mocked(api.post)

function mockRender(html: string) {
  return { json: () => Promise.resolve({ html }) } as unknown as ReturnType<typeof api.post>
}

beforeEach(() => {
  vi.useFakeTimers()
  mockPost.mockReset()
})
afterEach(() => {
  vi.useRealTimers()
})

describe('useMarkdownPreview', () => {
  it('returns no content and does not fetch for empty/whitespace input', () => {
    const ref = createRef<HTMLDivElement>()
    const { result } = renderHook(() =>
      useMarkdownPreview({ value: '   ', previewRef: ref }),
    )
    expect(result.current.hasContent).toBe(false)
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('debounces, then fetches and returns rendered html', async () => {
    mockPost.mockReturnValue(mockRender('<p>hi</p>'))
    const ref = createRef<HTMLDivElement>()
    const { result } = renderHook(() =>
      useMarkdownPreview({ value: 'hi', previewRef: ref, debounceMs: 500 }),
    )
    expect(mockPost).not.toHaveBeenCalled()
    await act(async () => {
      vi.advanceTimersByTime(500)
    })
    await waitFor(() => expect(result.current.html).toBe('<p>hi</p>'))
    expect(result.current.error).toBe(false)
    expect(mockPost).toHaveBeenCalledWith('render/preview', { json: { markdown: 'hi' } })
  })

  it('includes file_path in the payload when provided', async () => {
    mockPost.mockReturnValue(mockRender('<p>x</p>'))
    const ref = createRef<HTMLDivElement>()
    renderHook(() =>
      useMarkdownPreview({ value: 'x', filePath: 'posts/a/index.md', previewRef: ref }),
    )
    await act(async () => {
      vi.advanceTimersByTime(500)
    })
    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith('render/preview', {
        json: { markdown: 'x', file_path: 'posts/a/index.md' },
      }),
    )
  })

  it('sets error=true when the render call rejects', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    mockPost.mockReturnValue({ json: () => Promise.reject(new Error('boom')) } as never)
    const ref = createRef<HTMLDivElement>()
    const { result } = renderHook(() => useMarkdownPreview({ value: 'x', previewRef: ref }))
    await act(async () => {
      vi.advanceTimersByTime(500)
    })
    await waitFor(() => expect(result.current.error).toBe(true))
  })

  it('ignores a stale response when a newer request supersedes it', async () => {
    let resolveFirst: (v: { html: string }) => void = () => {}
    const first = { json: () => new Promise<{ html: string }>((r) => (resolveFirst = r)) }
    mockPost.mockReturnValueOnce(first as never)
    mockPost.mockReturnValueOnce(mockRender('<p>second</p>'))

    const ref = createRef<HTMLDivElement>()
    const { result, rerender } = renderHook(
      ({ value }) => useMarkdownPreview({ value, previewRef: ref }),
      { initialProps: { value: 'one' } },
    )
    await act(async () => {
      vi.advanceTimersByTime(500)
    })
    rerender({ value: 'two' })
    await act(async () => {
      vi.advanceTimersByTime(500)
    })
    await waitFor(() => expect(result.current.html).toBe('<p>second</p>'))

    // Late resolution of the first (stale) request must not overwrite the html.
    await act(async () => {
      resolveFirst({ html: '<p>first</p>' })
    })
    expect(result.current.html).toBe('<p>second</p>')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/hooks/__tests__/useMarkdownPreview.test.ts`
Expected: FAIL — `Cannot find module '../useMarkdownPreview'`.

- [ ] **Step 3: Write the hook**

Create `frontend/src/hooks/useMarkdownPreview.ts`:

```ts
import { useEffect, useRef, useState, type RefObject } from 'react'

import api from '@/api/client'
import { useRenderedHtml } from '@/hooks/useKatex'
import { useCodeBlockEnhance } from '@/hooks/useCodeBlockEnhance'

interface UseMarkdownPreviewOptions {
  value: string
  filePath?: string | null
  previewRef: RefObject<HTMLElement | null>
  debounceMs?: number
}

interface UseMarkdownPreviewResult {
  /** KaTeX-hydrated, sanitized HTML ready to mount; empty string when no content. */
  html: string
  /** True when the most recent render request failed. */
  error: boolean
  /** True when the markdown has non-whitespace content. */
  hasContent: boolean
}

/**
 * Owns the editor live-preview pipeline: a debounced `render/preview` call
 * (server renders + sanitizes), KaTeX hydration, and code-block enhancement
 * wired to `previewRef`. Shared by post and page editing so the preview behaves
 * identically everywhere.
 */
export function useMarkdownPreview({
  value,
  filePath,
  previewRef,
  debounceMs = 500,
}: UseMarkdownPreviewOptions): UseMarkdownPreviewResult {
  const [serverHtml, setServerHtml] = useState<string | null>(null)
  const [error, setError] = useState(false)
  const requestRef = useRef(0)
  const hasContent = value.trim().length > 0

  useEffect(() => {
    if (!hasContent) {
      setServerHtml(null)
      setError(false)
      return
    }
    const requestId = ++requestRef.current
    const timer = setTimeout(() => {
      const payload: { markdown: string; file_path?: string } = { markdown: value }
      if (filePath != null) {
        payload.file_path = filePath
      }
      api
        .post('render/preview', { json: payload })
        .json<{ html: string }>()
        .then((resp) => {
          if (requestRef.current === requestId) {
            setServerHtml(resp.html)
            setError(false)
          }
        })
        .catch((err: unknown) => {
          console.error('Preview failed:', err)
          if (requestRef.current === requestId) {
            setError(true)
          }
        })
    }, debounceMs)
    return () => clearTimeout(timer)
  }, [value, filePath, hasContent, debounceMs])

  const html = useRenderedHtml(hasContent ? serverHtml : null)
  useCodeBlockEnhance(previewRef, html)

  return { html, error, hasContent }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/hooks/__tests__/useMarkdownPreview.test.ts`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useMarkdownPreview.ts frontend/src/hooks/__tests__/useMarkdownPreview.test.ts
git commit -m "feat: add useMarkdownPreview hook for shared editor preview"
```

---

## Task 2: Extend `MarkdownToolbar` with save + fullscreen buttons

**Files:**
- Modify: `frontend/src/components/editor/MarkdownToolbar.tsx`
- Test: `frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx`

- [ ] **Step 1: Add failing tests**

Append these tests inside the existing `describe('MarkdownToolbar', …)` block in `frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx` (the file already imports `render, screen`, `userEvent`, `vi`, `createRef`):

```tsx
  it('does not render save or fullscreen buttons by default', () => {
    const ref = createRef<HTMLTextAreaElement>()
    render(<MarkdownToolbar textareaRef={ref} value="" onChange={() => {}} />)
    expect(screen.queryByLabelText('Save')).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/fullscreen/i)).not.toBeInTheDocument()
  })

  it('save button calls onSave when enabled', async () => {
    const onSave = vi.fn()
    const ref = createRef<HTMLTextAreaElement>()
    const user = userEvent.setup()
    render(<MarkdownToolbar textareaRef={ref} value="x" onChange={() => {}} onSave={onSave} />)
    await user.click(screen.getByLabelText('Save'))
    expect(onSave).toHaveBeenCalledOnce()
  })

  it('save button is disabled when canSave is false', () => {
    const onSave = vi.fn()
    const ref = createRef<HTMLTextAreaElement>()
    render(
      <MarkdownToolbar textareaRef={ref} value="" onChange={() => {}} onSave={onSave} canSave={false} />,
    )
    expect(screen.getByLabelText('Save')).toBeDisabled()
  })

  it('save button is disabled and shows Saving… while saving', () => {
    const onSave = vi.fn()
    const ref = createRef<HTMLTextAreaElement>()
    render(
      <MarkdownToolbar textareaRef={ref} value="x" onChange={() => {}} onSave={onSave} saving />,
    )
    const btn = screen.getByLabelText('Save')
    expect(btn).toBeDisabled()
    expect(btn).toHaveAttribute('title', 'Saving...')
  })

  it('fullscreen button toggles and reflects state in its label', async () => {
    const onToggleFullscreen = vi.fn()
    const ref = createRef<HTMLTextAreaElement>()
    const user = userEvent.setup()
    const { rerender } = render(
      <MarkdownToolbar
        textareaRef={ref}
        value=""
        onChange={() => {}}
        onToggleFullscreen={onToggleFullscreen}
      />,
    )
    await user.click(screen.getByLabelText('Enter fullscreen'))
    expect(onToggleFullscreen).toHaveBeenCalledOnce()

    rerender(
      <MarkdownToolbar
        textareaRef={ref}
        value=""
        onChange={() => {}}
        onToggleFullscreen={onToggleFullscreen}
        isFullscreen
      />,
    )
    expect(screen.getByLabelText('Exit fullscreen')).toBeInTheDocument()
  })
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/editor/__tests__/MarkdownToolbar.test.tsx`
Expected: FAIL — new buttons not found.

- [ ] **Step 3: Update the toolbar**

Replace the contents of `frontend/src/components/editor/MarkdownToolbar.tsx` with:

```tsx
import {
  Bold, Italic, Heading2, Link, ImagePlus, TextQuote, Code, FileCode, Save, Maximize2, Minimize2,
} from 'lucide-react'
import type { RefObject } from 'react'
import { actions } from './toolbarActions'
import { wrapSelection } from './wrapSelection'

interface MarkdownToolbarProps {
  textareaRef: RefObject<HTMLTextAreaElement | null>
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  onImageClick?: (() => void) | undefined
  imageUploading?: boolean
  imageDisabledReason?: string
  onSave?: (() => void) | undefined
  saving?: boolean
  canSave?: boolean
  isFullscreen?: boolean
  onToggleFullscreen?: (() => void) | undefined
}

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad|iPod/.test(navigator.userAgent)
const mod = isMac ? 'Cmd' : 'Ctrl'

const buttons = [
  { key: 'bold', label: 'Bold', Icon: Bold, shortcut: `${mod}+B` },
  { key: 'italic', label: 'Italic', Icon: Italic, shortcut: `${mod}+I` },
  { key: 'heading', label: 'Heading', Icon: Heading2, shortcut: `${mod}+H` },
  { key: 'link', label: 'Link', Icon: Link, shortcut: `${mod}+K` },
  { key: 'image', label: 'Image', Icon: ImagePlus, shortcut: `${mod}+Shift+I` },
  { key: 'blockquote', label: 'Blockquote', Icon: TextQuote, shortcut: `${mod}+Shift+.` },
  { key: 'code', label: 'Code', Icon: Code, shortcut: `${mod}+E` },
  { key: 'codeblock', label: 'Code Block', Icon: FileCode, shortcut: `${mod}+Shift+E` },
] as const

export default function MarkdownToolbar({
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
  function handleAction(key: string) {
    if (key === 'image') return // handled via onImageClick
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

  return (
    <div className="flex items-center gap-1 mb-2">
      {buttons.map(({ key, label, Icon, shortcut }) => {
        const isImage = key === 'image'
        const isDisabled = isImage
          ? (disabled ?? false) || imageDisabledReason !== undefined || onImageClick === undefined || imageUploading === true
          : disabled
        const title = isImage ? imageTitle(shortcut) : `${label} (${shortcut})`

        return (
          <button
            key={key}
            type="button"
            onClick={() => (isImage ? onImageClick?.() : handleAction(key))}
            disabled={isDisabled}
            className={`p-1.5 text-muted hover:text-ink hover:bg-paper-warm rounded transition-colors
                     disabled:opacity-50 disabled:cursor-not-allowed${
                       isImage && imageUploading === true ? ' animate-pulse' : ''
                     }`}
            title={title}
            aria-label={`${label} (${shortcut})`}
          >
            <Icon size={16} />
          </button>
        )
      })}

      {(onSave !== undefined || onToggleFullscreen !== undefined) && (
        <div className="ml-auto flex items-center gap-1">
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
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/editor/__tests__/MarkdownToolbar.test.tsx`
Expected: PASS (all existing + 5 new).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/editor/MarkdownToolbar.tsx frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx
git commit -m "feat: add save and fullscreen buttons to markdown toolbar"
```

---

## Task 3: `MarkdownEditor` core (toolbar + textarea + preview + scroll sync + shortcuts + mobile tabs)

**Files:**
- Create: `frontend/src/components/editor/MarkdownEditor.tsx`
- Test: `frontend/src/components/editor/__tests__/MarkdownEditor.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/editor/__tests__/MarkdownEditor.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { useMarkdownPreview } from '@/hooks/useMarkdownPreview'
import MarkdownEditor from '../MarkdownEditor'

vi.mock('@/hooks/useMarkdownPreview', () => ({ useMarkdownPreview: vi.fn() }))

const mockPreview = vi.mocked(useMarkdownPreview)

beforeEach(() => {
  mockPreview.mockReturnValue({ html: '', error: false, hasContent: false })
})

describe('MarkdownEditor', () => {
  it('renders the textarea with the provided value and reports edits via onChange', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<MarkdownEditor value="hello" onChange={onChange} />)
    const textarea = screen.getByRole('textbox')
    expect(textarea).toHaveValue('hello')
    await user.type(textarea, '!')
    expect(onChange).toHaveBeenCalled()
  })

  it('shows the empty-state placeholder when there is no content', () => {
    render(<MarkdownEditor value="" onChange={() => {}} />)
    expect(screen.getByText(/start typing to see a live preview/i)).toBeInTheDocument()
  })

  it('renders sanitized preview html when content exists', () => {
    mockPreview.mockReturnValue({ html: '<p>rendered</p>', error: false, hasContent: true })
    render(<MarkdownEditor value="x" onChange={() => {}} />)
    expect(screen.getByText('rendered')).toBeInTheDocument()
  })

  it('shows "Preview unavailable" when the preview errors', () => {
    mockPreview.mockReturnValue({ html: '', error: true, hasContent: true })
    render(<MarkdownEditor value="x" onChange={() => {}} />)
    expect(screen.getByText(/preview unavailable/i)).toBeInTheDocument()
  })

  it('calls onSave when the toolbar save button is clicked', async () => {
    const onSave = vi.fn()
    const user = userEvent.setup()
    render(<MarkdownEditor value="x" onChange={() => {}} onSave={onSave} canSave />)
    await user.click(screen.getByLabelText('Save'))
    expect(onSave).toHaveBeenCalledOnce()
  })

  it('saves on Cmd/Ctrl+S when canSave is true', async () => {
    const onSave = vi.fn()
    const user = userEvent.setup()
    render(<MarkdownEditor value="x" onChange={() => {}} onSave={onSave} canSave />)
    screen.getByRole('textbox').focus()
    await user.keyboard('{Control>}s{/Control}')
    expect(onSave).toHaveBeenCalledOnce()
  })

  it('does not save on Cmd/Ctrl+S when canSave is false', async () => {
    const onSave = vi.fn()
    const user = userEvent.setup()
    render(<MarkdownEditor value="" onChange={() => {}} onSave={onSave} canSave={false} />)
    screen.getByRole('textbox').focus()
    await user.keyboard('{Control>}s{/Control}')
    expect(onSave).not.toHaveBeenCalled()
  })

  it('applies a formatting shortcut (Ctrl+B) via onChange', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<MarkdownEditor value="hi" onChange={onChange} />)
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement
    textarea.focus()
    textarea.setSelectionRange(0, 2)
    await user.keyboard('{Control>}b{/Control}')
    expect(onChange).toHaveBeenCalledWith('**hi**')
  })

  it('renders the mobile edit/preview tab controls', () => {
    render(<MarkdownEditor value="" onChange={() => {}} />)
    expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Preview' })).toBeInTheDocument()
  })

  it('does not render a save button when onSave is not provided', () => {
    render(<MarkdownEditor value="x" onChange={() => {}} />)
    expect(screen.queryByLabelText('Save')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/editor/__tests__/MarkdownEditor.test.tsx`
Expected: FAIL — `Cannot find module '../MarkdownEditor'`.

- [ ] **Step 3: Write the component**

Create `frontend/src/components/editor/MarkdownEditor.tsx`:

```tsx
import { useRef, useState, type KeyboardEvent } from 'react'
import { ChevronRight, ChevronLeft, Eye } from 'lucide-react'

import MarkdownToolbar from './MarkdownToolbar'
import { actions as toolbarActions } from './toolbarActions'
import { wrapSelection } from './wrapSelection'
import { useScrollSync } from '@/hooks/useScrollSync'
import { useMarkdownPreview } from '@/hooks/useMarkdownPreview'

const KEY_MAP: Record<string, string> = { b: 'bold', i: 'italic', h: 'heading', k: 'link' }

export interface MarkdownEditorProps {
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  onSave?: () => void
  saving?: boolean
  canSave?: boolean
  filePath?: string | null
  editorHeight?: string
}

export default function MarkdownEditor({
  value,
  onChange,
  disabled = false,
  onSave,
  saving = false,
  canSave = true,
  filePath = null,
  editorHeight = '80vh',
}: MarkdownEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const previewRef = useRef<HTMLDivElement>(null)
  const [mobileTab, setMobileTab] = useState<'edit' | 'preview'>('edit')

  const { syncEditorToPreview, syncPreviewToEditor } = useScrollSync({
    textareaRef,
    previewRef,
    content: value,
  })
  const { html, error: previewError, hasContent } = useMarkdownPreview({
    value,
    filePath,
    previewRef,
  })

  const saveAllowed = canSave && !saving && !disabled

  function applyAction(actionKey: string) {
    const textarea = textareaRef.current
    if (!textarea) return
    const action = toolbarActions[actionKey]
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

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    const isMod = e.metaKey || e.ctrlKey
    if (!isMod) return

    if ((e.key === 's' || e.key === 'S') && !e.shiftKey) {
      if (onSave !== undefined && saveAllowed) {
        e.preventDefault()
        onSave()
      }
      return
    }

    let actionKey: string | undefined
    if (e.key === 'e' || e.key === 'E') {
      actionKey = e.shiftKey ? 'codeblock' : 'code'
    } else if ((e.key === '>' || e.key === '.') && e.shiftKey) {
      actionKey = 'blockquote'
    } else if (!e.shiftKey) {
      actionKey = KEY_MAP[e.key.toLowerCase()]
    }

    if (actionKey === undefined) return
    e.preventDefault()
    applyAction(actionKey)
  }

  return (
    <div>
      <div className="flex lg:hidden mb-4 border-b border-border">
        <button
          type="button"
          onClick={() => setMobileTab('edit')}
          className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
            mobileTab === 'edit'
              ? 'border-accent text-accent'
              : 'border-transparent text-muted hover:text-ink'
          }`}
        >
          Edit
        </button>
        <button
          type="button"
          onClick={() => setMobileTab('preview')}
          className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
            mobileTab === 'preview'
              ? 'border-accent text-accent'
              : 'border-transparent text-muted hover:text-ink'
          }`}
        >
          Preview
        </button>
      </div>

      <div className={mobileTab === 'preview' ? 'hidden lg:block' : ''}>
        <MarkdownToolbar
          textareaRef={textareaRef}
          value={value}
          onChange={onChange}
          disabled={disabled}
          {...(onSave !== undefined && { onSave })}
          saving={saving}
          canSave={canSave}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_2.5rem_1fr] gap-4">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          style={{ height: editorHeight }}
          className={`w-full overflow-y-auto p-4 bg-paper-warm border border-border rounded-lg
                   font-mono text-sm leading-relaxed text-ink resize-none
                   focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                   disabled:opacity-50 ${mobileTab === 'preview' ? 'hidden lg:block' : ''}`}
          spellCheck={false}
        />

        <div className="hidden lg:flex flex-col items-center justify-center gap-2">
          <button
            type="button"
            onClick={syncEditorToPreview}
            disabled={disabled}
            title="Go to editor position in preview"
            aria-label="Go to editor position in preview"
            className="p-1.5 text-muted hover:text-ink hover:bg-paper-warm rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <ChevronRight size={16} />
          </button>
          <button
            type="button"
            onClick={syncPreviewToEditor}
            disabled={disabled}
            title="Go to preview position in editor"
            aria-label="Go to preview position in editor"
            className="p-1.5 text-muted hover:text-ink hover:bg-paper-warm rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <ChevronLeft size={16} />
          </button>
        </div>

        <div
          ref={previewRef}
          style={{ height: editorHeight }}
          className={`relative p-6 bg-paper border border-border rounded-lg overflow-y-auto ${
            mobileTab === 'edit' ? 'hidden lg:block' : ''
          }`}
        >
          {previewError ? (
            <p className="text-sm text-red-600 dark:text-red-400 italic">Preview unavailable</p>
          ) : hasContent ? (
            <div
              className="prose max-w-none"
              // nosemgrep: typescript.react.security.audit.react-dangerouslysetinnerhtml
              // Preview HTML is rendered and sanitized server-side.
              dangerouslySetInnerHTML={{ __html: html }}
            />
          ) : (
            <div className="flex flex-col items-center justify-center h-full min-h-[200px] border-2 border-dashed border-border/50 rounded-lg bg-paper-warm/30">
              <Eye size={32} className="text-muted/40 mb-3" />
              <p className="text-sm text-muted/60">Start typing to see a live preview</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/editor/__tests__/MarkdownEditor.test.tsx`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/editor/MarkdownEditor.tsx frontend/src/components/editor/__tests__/MarkdownEditor.test.tsx
git commit -m "feat: add reusable MarkdownEditor core component"
```

---

## Task 4: Add fullscreen to `MarkdownEditor`

**Files:**
- Modify: `frontend/src/components/editor/MarkdownEditor.tsx`
- Test: `frontend/src/components/editor/__tests__/MarkdownEditor.test.tsx`

- [ ] **Step 1: Add failing tests**

Append inside the `describe('MarkdownEditor', …)` block:

```tsx
  it('toggles fullscreen via the toolbar and back again', async () => {
    const user = userEvent.setup()
    render(<MarkdownEditor value="x" onChange={() => {}} />)
    await user.click(screen.getByLabelText('Enter fullscreen'))
    expect(screen.getByLabelText('Exit fullscreen')).toBeInTheDocument()
    await user.click(screen.getByLabelText('Exit fullscreen'))
    expect(screen.getByLabelText('Enter fullscreen')).toBeInTheDocument()
  })

  it('exits fullscreen when Escape is pressed', async () => {
    const user = userEvent.setup()
    render(<MarkdownEditor value="x" onChange={() => {}} />)
    await user.click(screen.getByLabelText('Enter fullscreen'))
    expect(screen.getByLabelText('Exit fullscreen')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.getByLabelText('Enter fullscreen')).toBeInTheDocument()
  })
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/editor/__tests__/MarkdownEditor.test.tsx`
Expected: FAIL — no `Enter fullscreen` button yet.

- [ ] **Step 3: Add fullscreen state, Escape handling, overlay layout, and toolbar wiring**

In `frontend/src/components/editor/MarkdownEditor.tsx`:

(a) Update the React import to add `useEffect`:

```tsx
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
```

(b) After the `const [mobileTab, setMobileTab] = useState<'edit' | 'preview'>('edit')` line, add:

```tsx
  const [isFullscreen, setIsFullscreen] = useState(false)

  useEffect(() => {
    if (!isFullscreen) return
    function onKey(e: globalThis.KeyboardEvent) {
      if (e.key === 'Escape') setIsFullscreen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isFullscreen])
```

(c) Replace the `<MarkdownToolbar … />` element with the version that wires fullscreen props:

```tsx
        <MarkdownToolbar
          textareaRef={textareaRef}
          value={value}
          onChange={onChange}
          disabled={disabled}
          {...(onSave !== undefined && { onSave })}
          saving={saving}
          canSave={canSave}
          isFullscreen={isFullscreen}
          onToggleFullscreen={() => setIsFullscreen((f) => !f)}
        />
```

(d) Replace the outermost `return ( <div> … </div> )` wrapper opening tag and the grid/textarea/preview heights so fullscreen fills the viewport. Change the opening wrapper `<div>` to:

```tsx
    <div
      className={
        isFullscreen ? 'fixed inset-0 z-50 flex flex-col bg-paper p-4 overflow-hidden' : ''
      }
    >
```

(e) Change the grid container `<div className="grid …">` to flex-grow in fullscreen:

```tsx
      <div
        className={`grid grid-cols-1 lg:grid-cols-[1fr_2.5rem_1fr] gap-4 ${
          isFullscreen ? 'flex-1 min-h-0' : ''
        }`}
      >
```

(f) For BOTH the `<textarea>` and the preview `<div ref={previewRef} …>`, make height adapt: replace `style={{ height: editorHeight }}` with:

```tsx
          style={isFullscreen ? undefined : { height: editorHeight }}
```

and append `${isFullscreen ? 'h-full' : ''}` to each of their `className` template strings (inside the existing backticks, before the closing backtick).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/editor/__tests__/MarkdownEditor.test.tsx`
Expected: PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/editor/MarkdownEditor.tsx frontend/src/components/editor/__tests__/MarkdownEditor.test.tsx
git commit -m "feat: add fullscreen toggle to MarkdownEditor"
```

---

## Task 5: Add opt-in asset support to `MarkdownEditor`

Adds FileStrip + toolbar image upload (insert-at-cursor) gated by `enableAssets`. Hidden in fullscreen.

**Files:**
- Modify: `frontend/src/components/editor/MarkdownEditor.tsx`
- Test: `frontend/src/components/editor/__tests__/MarkdownEditor.test.tsx`

- [ ] **Step 1: Add failing tests**

At the top of `MarkdownEditor.test.tsx`, add a mock for the assets data hook and posts API used by `FileStrip`/`useFileUpload` (place these `vi.mock` calls next to the existing `useMarkdownPreview` mock):

```tsx
vi.mock('@/hooks/usePostAssets', () => ({
  usePostAssets: () => ({ data: { assets: [] }, error: undefined, mutate: vi.fn() }),
}))
vi.mock('@/api/posts', () => ({
  uploadAssets: vi.fn(),
  deletePostAsset: vi.fn(),
  renamePostAsset: vi.fn(),
}))
```

Then append inside the `describe('MarkdownEditor', …)` block:

```tsx
  it('does not render asset UI when enableAssets is omitted', () => {
    render(<MarkdownEditor value="x" onChange={() => {}} />)
    expect(screen.queryByLabelText(/^Image/)).not.toBeInTheDocument()
    expect(screen.queryByText(/^Files/)).not.toBeInTheDocument()
  })

  it('renders the file strip and an image button when assets are enabled', () => {
    render(
      <MarkdownEditor
        value="x"
        onChange={() => {}}
        enableAssets
        filePath="posts/a/index.md"
      />,
    )
    expect(screen.getByText(/^Files/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Image/)).toBeInTheDocument()
  })

  it('disables the image button with the given reason before the file path exists', () => {
    render(
      <MarkdownEditor
        value="x"
        onChange={() => {}}
        enableAssets
        filePath={null}
        assetDisabledReason="Save post first to add images"
      />,
    )
    const imageBtn = screen.getByLabelText(/^Image/)
    expect(imageBtn).toBeDisabled()
    expect(imageBtn).toHaveAttribute('title', 'Save post first to add images')
  })
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/editor/__tests__/MarkdownEditor.test.tsx`
Expected: FAIL — image button / file strip not rendered.

- [ ] **Step 3: Implement asset support**

In `frontend/src/components/editor/MarkdownEditor.tsx`:

(a) Add imports near the other editor imports:

```tsx
import FileStrip from './FileStrip'
import { useFileUpload } from './useFileUpload'
```

(b) Extend `MarkdownEditorProps`:

```tsx
  filePath?: string | null
  enableAssets?: boolean
  assetDisabledReason?: string
  editorHeight?: string
```

and destructure the new props (with defaults) in the function signature:

```tsx
  filePath = null,
  enableAssets = false,
  assetDisabledReason,
  editorHeight = '80vh',
```

(c) After the `const [isFullscreen, …]` block, add the asset wiring:

```tsx
  const [fileRefreshToken, setFileRefreshToken] = useState(0)
  const imageUploadEnabled = enableAssets && filePath !== null
  const imageDisabledReason =
    enableAssets && filePath === null ? assetDisabledReason : undefined

  function insertAtCursor(text: string) {
    const textarea = textareaRef.current
    if (!textarea) {
      onChange(value + '\n' + text)
      return
    }
    const pos = textarea.selectionStart
    onChange(value.slice(0, pos) + text + value.slice(pos))
  }

  const {
    triggerUpload: triggerImageUpload,
    uploading: imageUploading,
    inputProps: imageInputProps,
  } = useFileUpload({
    filePath: imageUploadEnabled ? filePath : null,
    accept: 'image/*',
    multiple: false,
    onSuccess: (filenames) => {
      for (const name of filenames) {
        insertAtCursor(`![${name}](${name})`)
      }
      setFileRefreshToken((prev) => prev + 1)
    },
  })
```

(d) Add the image-upload keyboard shortcut to `handleKeyDown` — insert this branch immediately after the `Cmd/Ctrl+S` block (before the `let actionKey` line):

```tsx
    if ((e.key === 'i' || e.key === 'I') && e.shiftKey) {
      if (imageUploadEnabled) {
        e.preventDefault()
        triggerImageUpload()
      }
      return
    }
```

(e) Render the FileStrip + hidden file input. Immediately **before** the mobile-tabs `<div className="flex lg:hidden …">`, add (FileStrip is hidden in fullscreen):

```tsx
      {enableAssets && !isFullscreen && (
        <div className="mb-4">
          <FileStrip
            filePath={filePath}
            body={value}
            onBodyChange={onChange}
            onInsertAtCursor={insertAtCursor}
            disabled={disabled}
            refreshToken={fileRefreshToken}
          />
        </div>
      )}
```

(f) Wire the image button into the toolbar. Replace the `<MarkdownToolbar … />` element so it passes the image props, and add the hidden input right after it:

```tsx
        <MarkdownToolbar
          textareaRef={textareaRef}
          value={value}
          onChange={onChange}
          disabled={disabled}
          {...(onSave !== undefined && { onSave })}
          saving={saving}
          canSave={canSave}
          isFullscreen={isFullscreen}
          onToggleFullscreen={() => setIsFullscreen((f) => !f)}
          {...(enableAssets && {
            onImageClick: imageUploadEnabled ? triggerImageUpload : undefined,
            imageUploading,
            ...(imageDisabledReason !== undefined && { imageDisabledReason }),
          })}
        />
        {enableAssets && <input {...imageInputProps} />}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/editor/__tests__/MarkdownEditor.test.tsx`
Expected: PASS (15 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/editor/MarkdownEditor.tsx frontend/src/components/editor/__tests__/MarkdownEditor.test.tsx
git commit -m "feat: add opt-in asset support to MarkdownEditor"
```

---

## Task 6: Integrate `MarkdownEditor` into `EditorPage`

Replace the bespoke editor surface with the component. Metadata, header Save, autosave, and cross-post stay.

**Files:**
- Modify: `frontend/src/pages/EditorPage.tsx`
- Test: `frontend/src/pages/__tests__/EditorPage.test.tsx`

- [ ] **Step 1: Swap in the component**

In `frontend/src/pages/EditorPage.tsx`:

(a) Replace everything from the `<div className="mb-4"> <FileStrip … /> </div>` block through the end of the editor/preview grid (the `<div className="grid grid-cols-1 lg:grid-cols-[1fr_2.5rem_1fr] gap-4"> … </div>`, i.e. the current lines starting at the FileStrip wrapper and ending at the closing `</div>` of that grid) with a single element:

```tsx
      <MarkdownEditor
        value={body}
        onChange={setBody}
        disabled={saving}
        onSave={() => void handleSave()}
        saving={saving}
        canSave={title.trim().length > 0}
        filePath={effectiveFilePath}
        enableAssets
        assetDisabledReason="Save post first to add images"
      />
```

(b) Remove now-unused code and imports:
- Imports: `useCodeBlockEnhance`, `useFileUpload`, `MarkdownToolbar`, `actions as toolbarActions`, `wrapSelection`, `FileStrip`, `useScrollSync`, `useRenderedHtml`, and the icons `Eye`, `ChevronRight`, `ChevronLeft` **only if** no longer referenced (note: `Eye` is still used by the "View post" button — keep it; remove `ChevronRight`/`ChevronLeft`).
- Add import: `import MarkdownEditor from '@/components/editor/MarkdownEditor'`.
- Delete the `KEY_MAP` constant.
- Delete state/refs no longer used: `preview`, `previewError`, `renderedPreview`, `previewRequestRef`, `previewRef`, `textareaRef`, `mobileTab`, `fileStripRefreshToken`, the `useScrollSync` call, `useCodeBlockEnhance` call, the preview-render `useEffect`, `handleInsertAtCursor`, `handleEditorKeyDown`, the image `useFileUpload` block (`triggerImageUpload`/`imageUploading`/`imageInputProps`), and `imageUploadEnabled`/`imageDisabledReason`.
- Keep: `title`, `subtitle`, `body`, `labels`, `isDraft`, autosave wiring, `handleSave`, `effectiveFilePath`, `savedFilePath`, cross-post state/dialog, header buttons.

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc -p tsconfig.json --noEmit`
Expected: no errors. (Fixes any leftover unused-import or missing-reference issues from Step 1.)

- [ ] **Step 3: Run the EditorPage test suite (regression net)**

Run: `cd frontend && npx vitest run src/pages/__tests__/EditorPage.test.tsx`
Expected: PASS. The textarea (`role="textbox"`), the header **Save** button, the image button (`/^Image/`), scroll-sync buttons, and the file strip all still render with identical labels, so behavior-level tests stay green. If a test queried a now-removed duplicate or relied on the textarea's old `h-[80vh]` class, update that query to target the role/label instead. Do **not** weaken assertions — only adjust selectors that referenced removed structural details.

> Note: `EditorPage.test.tsx` mocks `@/hooks/useKatex` and `@/api/posts`, and `@/api/client` as `{ default: { post }, HTTPError }`. `useMarkdownPreview` uses the same `api.post('render/preview')` path the old effect used, so existing preview mocking continues to apply.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/EditorPage.tsx frontend/src/pages/__tests__/EditorPage.test.tsx
git commit -m "refactor: use shared MarkdownEditor in post editor"
```

---

## Task 7: Integrate `MarkdownEditor` into `PagesSection`; delete `PagePreview`

**Files:**
- Modify: `frontend/src/components/admin/PagesSection.tsx`
- Test: `frontend/src/components/admin/__tests__/PagesSection.test.tsx` (new)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/admin/__tests__/PagesSection.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { updateAdminPage } from '@/api/admin'
import type { AdminPageConfig } from '@/api/client'
import PagesSection from '../PagesSection'

vi.mock('@/api/admin', () => ({
  createAdminPage: vi.fn(),
  updateAdminPage: vi.fn().mockResolvedValue(undefined),
  updateAdminPageOrder: vi.fn(),
  deleteAdminPage: vi.fn(),
}))
vi.mock('@/stores/siteStore', () => ({ refreshSiteConfig: vi.fn() }))
vi.mock('@/hooks/useMarkdownPreview', () => ({
  useMarkdownPreview: () => ({ html: '', error: false, hasContent: false }),
}))

const mockUpdateAdminPage = vi.mocked(updateAdminPage)

const pages: AdminPageConfig[] = [
  { id: 'about', title: 'About', file: 'about.md', is_builtin: false, content: '# About' },
]

function renderSection() {
  return render(
    <PagesSection
      initialPages={pages}
      busy={false}
      onSaving={() => {}}
      onPagesChange={() => {}}
      onDirtyChange={() => {}}
    />,
  )
}

beforeEach(() => {
  mockUpdateAdminPage.mockClear()
})

describe('PagesSection editor integration', () => {
  it('edits page content through the shared MarkdownEditor and saves via its toolbar', async () => {
    const user = userEvent.setup()
    renderSection()

    await user.click(screen.getByText('About'))
    const textarea = screen.getByRole('textbox', { name: '' }) as HTMLTextAreaElement
    // The content textarea holds the page markdown.
    expect(textarea).toHaveValue('# About')

    await user.clear(textarea)
    await user.type(textarea, '# Updated')
    await user.click(screen.getByLabelText('Save'))

    await waitFor(() =>
      expect(mockUpdateAdminPage).toHaveBeenCalledWith('about', { content: '# Updated' }),
    )
  })
})
```

> If `getByRole('textbox', { name: '' })` is ambiguous because the title `<input>` is also a textbox, scope it: query the title input by its label first, then use `screen.getAllByRole('textbox')` and select the `<textarea>` (the second textbox), or add an `aria-label` to the page-content editor's textarea via a wrapping label. Prefer scoping in the test over changing component markup.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/admin/__tests__/PagesSection.test.tsx`
Expected: FAIL — no `Save` toolbar button (still the old textarea + PagePreview).

- [ ] **Step 3: Replace the content editor and delete `PagePreview`**

In `frontend/src/components/admin/PagesSection.tsx`:

(a) Delete the entire `PagePreview` component (the `function PagePreview({ markdown }: …) { … }` block) and remove the now-unused imports `api` (`import api from '@/api/client'`) and `useRenderedHtml` (`import { useRenderedHtml } from '@/hooks/useKatex'`). Add `import MarkdownEditor from '@/components/editor/MarkdownEditor'`.

(b) Replace the content editor block (the `<div> <label>Content</label> <div className="grid grid-cols-1 lg:grid-cols-2 gap-4"> <textarea … /> <div …><PagePreview markdown={editContent} /></div> </div> </div>`) with:

```tsx
                {/* Content editor for non-builtin pages with files */}
                {!BUILTIN_PAGE_IDS.has(page.id) && page.file !== null && (
                  <div>
                    <label className="block text-xs font-medium text-muted mb-1">Content</label>
                    <MarkdownEditor
                      value={editContent}
                      onChange={(v) => {
                        setEditContent(v)
                        setPageEditSuccess(null)
                      }}
                      disabled={busy}
                      onSave={() => void handleSavePage()}
                      saving={savingPage}
                      canSave={editTitle.trim().length > 0}
                      editorHeight="24rem"
                    />
                  </div>
                )}
```

(c) Leave the existing "Save Page" button in place — built-in pages (which render no `MarkdownEditor`) still need it to save the title. For non-built-in pages the toolbar save and the "Save Page" button both call `handleSavePage`, mirroring the post editor's dual-save pattern.

- [ ] **Step 4: Run test + type-check**

Run: `cd frontend && npx vitest run src/components/admin/__tests__/PagesSection.test.tsx && npx tsc -p tsconfig.json --noEmit`
Expected: PASS, no type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/admin/PagesSection.tsx frontend/src/components/admin/__tests__/PagesSection.test.tsx
git commit -m "refactor: use shared MarkdownEditor for page editing"
```

---

## Task 8: Documentation

**Files:**
- Modify: `docs/arch/frontend.md`
- Create: `docs/arch/editor.md`

- [ ] **Step 1: Add a brief mention to `frontend.md`**

In `docs/arch/frontend.md`, replace the **Editing Architecture** section body with a version that names the shared component and points to the new doc. Keep it concise and in the existing style:

```markdown
## Editing Architecture

Post and page authoring share one reusable editing surface, `MarkdownEditor`
(`frontend/src/components/editor/`). It owns the toolbar, textarea, debounced
live preview, editor↔preview scroll sync, keyboard shortcuts, mobile tabs,
fullscreen mode, and opt-in asset management; hosts own metadata, autosave, and
save handling. Preview rendering is delegated to the backend so the editor and
the published site share one rendering and sanitization pipeline. See
[editor.md](editor.md).
```

Add `editor.md` to the "What To Read Next" list in `docs/arch/index.md`:

```markdown
- Read [editor.md](editor.md) for the shared markdown editing component used by post and page authoring.
```

- [ ] **Step 2: Create `docs/arch/editor.md`**

Create `docs/arch/editor.md` (concise, matches the arch-doc style):

```markdown
# Markdown Editor Architecture

`MarkdownEditor` (`frontend/src/components/editor/MarkdownEditor.tsx`) is the
single reusable editing surface used by both post authoring (`EditorPage`) and
page authoring (`PagesSection`).

## Boundary

The component is controlled via `value`/`onChange`: it performs all editing
interactions (typing, toolbar formatting, asset-reference rewrites on rename)
and reports each new markdown string upward. It does not store the markdown
itself, so hosts retain it for autosave, save payloads, and dirty tracking.

**Component owns:** the toolbar (formatting actions + save + fullscreen toggle),
textarea, live preview, scroll sync, keyboard shortcuts (formatting +
Cmd/Ctrl+S), mobile edit/preview tabs, the fullscreen overlay, and — when
`enableAssets` is set — file attachment management (upload/delete/rename) plus
toolbar image upload. Assets are hidden in fullscreen.

**Host owns:** metadata fields, autosave, the `onSave` handler and error
banners.

## Pieces

- `MarkdownEditor.tsx` — orchestrator and layout.
- `MarkdownToolbar.tsx` — formatting, image, save, and fullscreen buttons.
- `useMarkdownPreview` (`frontend/src/hooks/`) — debounced backend
  `render/preview` call plus KaTeX hydration and code-block enhancement; the
  single source of preview behavior.
- Supporting units: `wrapSelection`/`toolbarActions` (formatting transforms),
  `useScrollSync` (editor↔preview alignment), `useFileUpload` + `FileStrip` +
  `markdownAssetReferences` (assets).

## Usage

- Posts: `enableAssets` on, `filePath` is the post path (null until first save,
  which disables image upload with a reason). The post page also keeps a header
  Save button wired to the same handler.
- Pages: text-only (no `enableAssets`); saved via the toolbar save button.

Preview HTML is rendered and sanitized server-side; the component mounts it via
`dangerouslySetInnerHTML`.
```

- [ ] **Step 3: Commit**

```bash
git add docs/arch/frontend.md docs/arch/index.md docs/arch/editor.md
git commit -m "docs: document shared MarkdownEditor architecture"
```

---

## Task 9: Full gate + browser verification

**Files:** none (verification only).

- [ ] **Step 1: Run the frontend gate**

Run: `just check-frontend`
Expected: ESLint clean, type-check clean, all tests pass, coverage meets thresholds.

- [ ] **Step 2: Fix any gate failures**

If coverage on `MarkdownEditor.tsx` / `useMarkdownPreview.ts` is below threshold, add targeted tests for the uncovered branch (e.g. insert-at-cursor with no textarea, image shortcut when assets disabled). If ESLint flags an unused import left over from Task 6/7, remove it. Re-run `just check-frontend`.

- [ ] **Step 3: Browser end-to-end check (per frontend CLAUDE.md)**

Start the dev server and verify both flows with Playwright MCP:

```bash
just start && just health
```

Verify:
1. Post editor (`/editor/new`): type markdown → preview updates; toolbar bold/heading work; toolbar **and** header Save both save; fullscreen toggle enters/exits and Esc exits; after first save, image upload + file strip work.
2. Page editor (admin → Pages → expand a non-builtin page): markdown editor renders with toolbar + preview; edit content → preview updates; toolbar Save persists; fullscreen works; no file strip / image button (text-only).

Remove any leftover `*.png` screenshots. Then:

```bash
just stop
```

- [ ] **Step 4: Final commit (if Step 2 produced changes)**

```bash
git add -A
git commit -m "test: cover MarkdownEditor branches and fix gate"
```

---

## Self-Review Notes (verified during planning)

- **Spec coverage:** controlled `value`/`onChange` (Task 3), save in toolbar + Cmd/Ctrl+S (Tasks 2–3), header Save coexists for posts (Task 6), fullscreen covering only the editing surface with Esc (Task 4), assets opt-in/hidden in fullscreen (Task 5), text-only pages (Task 7), `useMarkdownPreview` dedup with KaTeX + code-block enhancement parity (Task 1), `PagePreview` deleted (Task 7), docs incl. new `editor.md` (Task 8). All covered.
- **Type consistency:** `MarkdownEditorProps` field names (`onSave`, `saving`, `canSave`, `filePath`, `enableAssets`, `assetDisabledReason`, `editorHeight`) are used identically in Tasks 3–7. Toolbar prop names (`onSave`, `canSave`, `saving`, `isFullscreen`, `onToggleFullscreen`, `onImageClick`, `imageUploading`, `imageDisabledReason`) match between Task 2 and Tasks 3/5. `useMarkdownPreview` returns `{ html, error, hasContent }` everywhere it is consumed/mocked.
- **No placeholders:** every code step contains complete code or exact edit instructions.
```
