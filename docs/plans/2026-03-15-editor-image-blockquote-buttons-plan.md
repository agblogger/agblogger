# Editor Image and Blockquote Toolbar Buttons — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Image and Blockquote buttons to the markdown editor toolbar, between Link and Code.

**Architecture:** Extend the existing `WrapAction` system with a `linePrefix` mode for blockquote. Extract a shared `useFileUpload` hook from `FileStrip` for the image upload flow. The image toolbar button triggers a file picker restricted to images, uploads via the existing asset API, and inserts `![name](name)` at cursor.

**Tech Stack:** React, TypeScript, Vitest, Lucide icons, existing `uploadAssets` API.

**Spec:** `docs/specs/2026-03-15-editor-image-blockquote-buttons-design.md`

---

## Chunk 1: Blockquote — `linePrefix` in `wrapSelection`

### Task 1: Add `linePrefix` support to `wrapSelection`

**Files:**
- Modify: `frontend/src/components/editor/wrapSelection.ts`
- Modify: `frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx`

- [ ] **Step 1: Write failing unit tests for `linePrefix` mode**

Add these tests to the existing `describe('wrapSelection', ...)` block in `frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx`:

```ts
it('linePrefix mode prefixes a single line with the given string', () => {
  const result = wrapSelection('hello world', 6, 11, {
    before: '',
    after: '',
    placeholder: 'quote text',
    linePrefix: '> ',
  })
  expect(result.newValue).toBe('hello > world')
  expect(result.cursorStart).toBe(6)
  expect(result.cursorEnd).toBe(13)
})

it('linePrefix mode prefixes each line of a multi-line selection', () => {
  const result = wrapSelection('line one\nline two\nline three', 0, 28, {
    before: '',
    after: '',
    placeholder: 'quote text',
    linePrefix: '> ',
  })
  expect(result.newValue).toBe('> line one\n> line two\n> line three')
  expect(result.cursorStart).toBe(0)
  expect(result.cursorEnd).toBe(34)
})

it('linePrefix mode uses placeholder when nothing is selected', () => {
  const result = wrapSelection('hello ', 6, 6, {
    before: '',
    after: '',
    placeholder: 'quote text',
    linePrefix: '> ',
  })
  expect(result.newValue).toBe('hello > quote text')
  expect(result.cursorStart).toBe(6)
  expect(result.cursorEnd).toBe(18)
})

it('linePrefix mode with block adds leading newline when not at line start', () => {
  const result = wrapSelection('some text', 9, 9, {
    before: '',
    after: '',
    placeholder: 'quote text',
    linePrefix: '> ',
    block: true,
  })
  expect(result.newValue).toBe('some text\n> quote text')
  expect(result.cursorStart).toBe(10)
  expect(result.cursorEnd).toBe(22)
})

it('linePrefix mode with block does not add newline at line start', () => {
  const result = wrapSelection('', 0, 0, {
    before: '',
    after: '',
    placeholder: 'quote text',
    linePrefix: '> ',
    block: true,
  })
  expect(result.newValue).toBe('> quote text')
  expect(result.cursorStart).toBe(0)
  expect(result.cursorEnd).toBe(12)
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-frontend` (unsandboxed)
Expected: 5 new tests FAIL (linePrefix not implemented yet)

- [ ] **Step 3: Implement `linePrefix` support in `wrapSelection`**

Modify `frontend/src/components/editor/wrapSelection.ts`:

```ts
export interface WrapAction {
  before: string
  after: string
  placeholder: string
  block?: boolean
  linePrefix?: string
}

export function wrapSelection(
  value: string,
  selectionStart: number,
  selectionEnd: number,
  action: WrapAction,
): { newValue: string; cursorStart: number; cursorEnd: number } {
  const selected = value.slice(selectionStart, selectionEnd)
  const text = selected.length > 0 ? selected : action.placeholder

  let blockPrefix = ''
  if (action.block === true && selectionStart > 0 && value[selectionStart - 1] !== '\n') {
    blockPrefix = '\n'
  }

  if (action.linePrefix !== undefined) {
    const prefixed = text
      .split('\n')
      .map((line) => action.linePrefix + line)
      .join('\n')
    const inserted = blockPrefix + prefixed
    const newValue = value.slice(0, selectionStart) + inserted + value.slice(selectionEnd)
    const cursorStart = selectionStart + blockPrefix.length
    const cursorEnd = cursorStart + prefixed.length
    return { newValue, cursorStart, cursorEnd }
  }

  let before = blockPrefix + action.before
  const inserted = before + text + action.after
  const newValue = value.slice(0, selectionStart) + inserted + value.slice(selectionEnd)
  const cursorStart = selectionStart + before.length
  const cursorEnd = cursorStart + text.length
  return { newValue, cursorStart, cursorEnd }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-frontend` (unsandboxed)
Expected: All tests PASS (existing + 5 new)

- [ ] **Step 5: Update property tests to cover `linePrefix`**

In `frontend/src/components/editor/__tests__/wrapSelection.property.test.ts`, update the `actionArb` to include `linePrefix`:

```ts
const actionArb: fc.Arbitrary<WrapAction> = fc.record({
  before: fc.string({ maxLength: 8 }),
  after: fc.string({ maxLength: 8 }),
  placeholder: fc.string({ minLength: 1, maxLength: 32 }),
  block: fc.boolean(),
  linePrefix: fc.option(fc.string({ minLength: 1, maxLength: 4 }), { nil: undefined }),
})
```

Update the first property test (`'always performs a deterministic splice/wrap transformation'`) to handle the `linePrefix` branch. When `action.linePrefix` is defined, the expected result is different from the wrap branch:

```ts
(value, startRaw, endRaw, action) => {
  const [selectionStart, selectionEnd] = normalizedSelection(value.length, startRaw, endRaw)

  const selected = value.slice(selectionStart, selectionEnd)
  const insertedText = selected.length > 0 ? selected : action.placeholder

  let blockPrefix = ''
  if (action.block === true && selectionStart > 0 && value[selectionStart - 1] !== '\n') {
    blockPrefix = '\n'
  }

  let expectedNewValue: string
  let expectedCursorStart: number
  let expectedCursorEnd: number

  if (action.linePrefix !== undefined) {
    const prefixed = insertedText
      .split('\n')
      .map((line) => action.linePrefix + line)
      .join('\n')
    expectedNewValue = value.slice(0, selectionStart) + blockPrefix + prefixed + value.slice(selectionEnd)
    expectedCursorStart = selectionStart + blockPrefix.length
    expectedCursorEnd = expectedCursorStart + prefixed.length
  } else {
    const expectedBefore = blockPrefix + action.before
    expectedNewValue =
      value.slice(0, selectionStart) +
      expectedBefore +
      insertedText +
      action.after +
      value.slice(selectionEnd)
    expectedCursorStart = selectionStart + expectedBefore.length
    expectedCursorEnd = expectedCursorStart + insertedText.length
  }

  const result = wrapSelection(value, selectionStart, selectionEnd, action)

  expect(result.newValue).toBe(expectedNewValue)
  expect(result.cursorStart).toBe(expectedCursorStart)
  expect(result.cursorEnd).toBe(expectedCursorEnd)
}
```

Apply the same `linePrefix` branch logic to the `'preserves untouched prefix/suffix'` and `'injects an extra leading newline only for block actions'` property tests so they account for the `linePrefix` code path.

- [ ] **Step 6: Run tests to verify property tests pass**

Run: `just test-frontend` (unsandboxed)
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/editor/wrapSelection.ts \
       frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx \
       frontend/src/components/editor/__tests__/wrapSelection.property.test.ts
git commit -m "feat: add linePrefix mode to wrapSelection for blockquote support"
```

---

### Task 2: Add blockquote action and toolbar button

**Files:**
- Modify: `frontend/src/components/editor/toolbarActions.ts`
- Modify: `frontend/src/components/editor/MarkdownToolbar.tsx`
- Modify: `frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx`

- [ ] **Step 1: Write failing tests for blockquote toolbar button**

Add to the `describe('MarkdownToolbar', ...)` block in `frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx`:

```ts
it('renders all 8 toolbar buttons including image and blockquote', () => {
  const ref = createRef<HTMLTextAreaElement>()
  render(
    <MarkdownToolbar textareaRef={ref} value="" onChange={() => {}} />,
  )
  expect(screen.getByLabelText(/^Bold/)).toBeInTheDocument()
  expect(screen.getByLabelText(/^Italic/)).toBeInTheDocument()
  expect(screen.getByLabelText(/^Heading/)).toBeInTheDocument()
  expect(screen.getByLabelText(/^Link/)).toBeInTheDocument()
  expect(screen.getByLabelText(/^Image/)).toBeInTheDocument()
  expect(screen.getByLabelText(/^Blockquote/)).toBeInTheDocument()
  expect(screen.getByLabelText(/^Code \(/)).toBeInTheDocument()
  expect(screen.getByLabelText(/^Code Block/)).toBeInTheDocument()
})

it('blockquote button inserts with linePrefix mode', async () => {
  const onChange = vi.fn()
  const textarea = document.createElement('textarea')
  textarea.value = 'line one\nline two'
  textarea.selectionStart = 0
  textarea.selectionEnd = 17
  const ref = { current: textarea }

  const user = userEvent.setup()
  render(
    <MarkdownToolbar textareaRef={ref} value="line one\nline two" onChange={onChange} />,
  )

  await user.click(screen.getByLabelText(/^Blockquote/))

  expect(onChange).toHaveBeenCalledWith('> line one\n> line two')
})
```

Update the existing `'renders all 6 toolbar buttons'` test to expect 8 buttons (or remove it since the new test supersedes it).

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-frontend` (unsandboxed)
Expected: New blockquote tests FAIL (button doesn't exist yet)

- [ ] **Step 3: Add blockquote action to `toolbarActions.ts`**

```ts
import type { WrapAction } from './wrapSelection'

export const actions: Record<string, WrapAction> = {
  bold: { before: '**', after: '**', placeholder: 'bold text' },
  italic: { before: '_', after: '_', placeholder: 'italic text' },
  heading: { before: '## ', after: '', placeholder: 'Heading', block: true },
  link: { before: '[', after: '](url)', placeholder: 'link text' },
  blockquote: { before: '', after: '', placeholder: 'quote text', linePrefix: '> ', block: true },
  code: { before: '`', after: '`', placeholder: 'code' },
  codeblock: { before: '```\n', after: '\n```', placeholder: 'code', block: true },
}
```

- [ ] **Step 4: Add Blockquote button to `MarkdownToolbar.tsx`**

Update imports to add `TextQuote`:

```ts
import { Bold, Italic, Heading2, Link, ImagePlus, TextQuote, Code, FileCode } from 'lucide-react'
```

Update the `buttons` array — insert blockquote between link and code. Also add the image button entry (it will be wired up in Task 4, but needs to be in the array now for the button count test). The image button uses a special `key: 'image'` that won't match any action in `toolbarActions`, so `handleAction` will no-op for it — the real handler comes via `onImageClick` prop in Task 4:

```ts
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `just test-frontend` (unsandboxed)
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/editor/toolbarActions.ts \
       frontend/src/components/editor/MarkdownToolbar.tsx \
       frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx
git commit -m "feat: add blockquote toolbar button with linePrefix mode"
```

---

### Task 3: Add blockquote keyboard shortcut

**Files:**
- Modify: `frontend/src/pages/EditorPage.tsx`

- [ ] **Step 1: Refactor `handleEditorKeyDown` to support blockquote and image shortcuts**

The current handler maps `e.key.toLowerCase()` through `keyMap` without checking `shiftKey`, so `Cmd+Shift+I` would incorrectly trigger italic. Refactor the handler in `EditorPage.tsx`:

Replace the entire `handleEditorKeyDown` function:

```ts
function handleEditorKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
  const isMod = e.metaKey || e.ctrlKey
  if (!isMod) return

  let actionKey: string | undefined

  if (e.key === 'e' || e.key === 'E') {
    actionKey = e.shiftKey ? 'codeblock' : 'code'
  } else if ((e.key === '>' || e.key === '.') && e.shiftKey) {
    actionKey = 'blockquote'
  } else if (!e.shiftKey) {
    const keyMap: Record<string, string> = {
      b: 'bold',
      i: 'italic',
      h: 'heading',
      k: 'link',
    }
    actionKey = keyMap[e.key.toLowerCase()]
  }

  if (actionKey === undefined) return
  const action = toolbarActions[actionKey]
  if (action === undefined) return

  e.preventDefault()
  const textarea = textareaRef.current
  if (!textarea) return

  const { newValue, cursorStart, cursorEnd } = wrapSelection(
    body,
    textarea.selectionStart,
    textarea.selectionEnd,
    action,
  )
  setBody(newValue)
  requestAnimationFrame(() => {
    textarea.focus()
    textarea.setSelectionRange(cursorStart, cursorEnd)
  })
}
```

Key changes:
- Check `(e.key === '>' || e.key === '.') && e.shiftKey` for blockquote
- Move the `keyMap` lookup inside `!e.shiftKey` guard so `Cmd+Shift+I` no longer triggers italic
- Image shortcut (`Cmd+Shift+I`) will be added in Task 4 — it needs `triggerImageUpload` which doesn't exist yet

- [ ] **Step 2: Run tests to verify nothing is broken**

Run: `just test-frontend` (unsandboxed)
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/EditorPage.tsx
git commit -m "feat: add blockquote keyboard shortcut and guard shiftKey in key handler"
```

---

## Chunk 2: Image Upload — shared hook, FileStrip refactor, toolbar integration

### Task 4: Create `useFileUpload` hook

**Files:**
- Create: `frontend/src/components/editor/useFileUpload.ts`
- Create: `frontend/src/components/editor/__tests__/useFileUpload.test.ts`

- [ ] **Step 1: Write failing tests for the hook**

Create `frontend/src/components/editor/__tests__/useFileUpload.test.ts`:

```ts
import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { HTTPError } from '@/api/client'
import { uploadAssets } from '@/api/posts'
import { useFileUpload } from '../useFileUpload'

vi.mock('@/api/posts', () => ({
  uploadAssets: vi.fn(),
}))

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual('@/api/client')
  return { ...actual }
})

const mockUploadAssets = vi.mocked(uploadAssets)
const httpErrorOptions = {} as ConstructorParameters<typeof HTTPError>[2]

describe('useFileUpload', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('triggerUpload is a no-op when filePath is null', () => {
    const { result } = renderHook(() =>
      useFileUpload({ filePath: null }),
    )
    // Should not throw
    act(() => result.current.triggerUpload())
    expect(result.current.uploading).toBe(false)
  })

  it('inputProps includes accept when provided', () => {
    const { result } = renderHook(() =>
      useFileUpload({ filePath: 'posts/test/index.md', accept: 'image/*' }),
    )
    expect(result.current.inputProps.accept).toBe('image/*')
  })

  it('inputProps does not include accept when not provided', () => {
    const { result } = renderHook(() =>
      useFileUpload({ filePath: 'posts/test/index.md' }),
    )
    expect(result.current.inputProps.accept).toBeUndefined()
  })

  it('inputProps includes multiple based on option', () => {
    const { result: multiResult } = renderHook(() =>
      useFileUpload({ filePath: 'posts/test/index.md', multiple: true }),
    )
    expect(multiResult.current.inputProps.multiple).toBe(true)

    const { result: singleResult } = renderHook(() =>
      useFileUpload({ filePath: 'posts/test/index.md', multiple: false }),
    )
    expect(singleResult.current.inputProps.multiple).toBe(false)
  })

  it('calls uploadAssets and onSuccess on successful upload', async () => {
    mockUploadAssets.mockResolvedValue({ uploaded: ['photo.png'] })
    const onSuccess = vi.fn()

    const { result } = renderHook(() =>
      useFileUpload({
        filePath: 'posts/test/index.md',
        onSuccess,
      }),
    )

    // Simulate file selection via the onChange handler
    const file = new File(['content'], 'photo.png', { type: 'image/png' })
    await act(async () => {
      result.current.inputProps.onChange({
        target: { files: [file], value: '' },
      } as unknown as React.ChangeEvent<HTMLInputElement>)
    })

    expect(mockUploadAssets).toHaveBeenCalledWith('posts/test/index.md', [file])
    expect(onSuccess).toHaveBeenCalledWith(['photo.png'])
    expect(result.current.uploading).toBe(false)
  })

  it('calls onError with parsed message on HTTPError', async () => {
    const errorResponse = new Response(JSON.stringify({ detail: 'File too large' }), {
      status: 413,
      statusText: 'Payload Too Large',
    })
    mockUploadAssets.mockRejectedValue(
      new HTTPError(errorResponse, new Request('http://test'), httpErrorOptions),
    )
    const onError = vi.fn()

    const { result } = renderHook(() =>
      useFileUpload({
        filePath: 'posts/test/index.md',
        onError,
      }),
    )

    const file = new File(['content'], 'big.png', { type: 'image/png' })
    await act(async () => {
      result.current.inputProps.onChange({
        target: { files: [file], value: '' },
      } as unknown as React.ChangeEvent<HTMLInputElement>)
    })

    expect(onError).toHaveBeenCalledWith('File too large')
    expect(result.current.uploading).toBe(false)
  })

  it('calls onError with generic message on non-HTTP error', async () => {
    mockUploadAssets.mockRejectedValue(new Error('Network failure'))
    const onError = vi.fn()

    const { result } = renderHook(() =>
      useFileUpload({
        filePath: 'posts/test/index.md',
        onError,
      }),
    )

    const file = new File(['content'], 'photo.png', { type: 'image/png' })
    await act(async () => {
      result.current.inputProps.onChange({
        target: { files: [file], value: '' },
      } as unknown as React.ChangeEvent<HTMLInputElement>)
    })

    expect(onError).toHaveBeenCalledWith('Failed to upload files')
    expect(result.current.uploading).toBe(false)
  })

  it('does nothing when no files are selected', async () => {
    const onSuccess = vi.fn()
    const { result } = renderHook(() =>
      useFileUpload({
        filePath: 'posts/test/index.md',
        onSuccess,
      }),
    )

    await act(async () => {
      result.current.inputProps.onChange({
        target: { files: [], value: '' },
      } as unknown as React.ChangeEvent<HTMLInputElement>)
    })

    expect(mockUploadAssets).not.toHaveBeenCalled()
    expect(onSuccess).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-frontend` (unsandboxed)
Expected: Tests FAIL (module not found)

- [ ] **Step 3: Implement `useFileUpload` hook**

Create `frontend/src/components/editor/useFileUpload.ts`:

```ts
import { useCallback, useRef, useState } from 'react'
import { HTTPError } from '@/api/client'
import { parseErrorDetail } from '@/api/parseError'
import { uploadAssets } from '@/api/posts'

interface UseFileUploadOptions {
  filePath: string | null
  accept?: string
  multiple?: boolean
  onStart?: () => void
  onSuccess?: (uploaded: string[]) => void
  onError?: (message: string) => void
}

export function useFileUpload({
  filePath,
  accept,
  multiple = true,
  onStart,
  onSuccess,
  onError,
}: UseFileUploadOptions) {
  const [uploading, setUploading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const triggerUpload = useCallback(() => {
    if (filePath === null) return
    inputRef.current?.click()
  }, [filePath])

  const handleChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      if (filePath === null) return
      const files = e.target.files
      if (files === null || files.length === 0) return

      setUploading(true)
      onStart?.()
      try {
        const result = await uploadAssets(filePath, Array.from(files))
        onSuccess?.(result.uploaded)
      } catch (err) {
        if (err instanceof HTTPError) {
          const detail = await parseErrorDetail(err.response, 'Failed to upload files')
          onError?.(detail)
        } else {
          onError?.('Failed to upload files')
        }
      } finally {
        setUploading(false)
        if (inputRef.current) {
          inputRef.current.value = ''
        }
      }
    },
    [filePath, onStart, onSuccess, onError],
  )

  const inputProps = {
    ref: inputRef,
    type: 'file' as const,
    accept,
    multiple,
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => void handleChange(e),
    className: 'hidden',
  }

  return { triggerUpload, uploading, inputProps }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-frontend` (unsandboxed)
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/editor/useFileUpload.ts \
       frontend/src/components/editor/__tests__/useFileUpload.test.ts
git commit -m "feat: add useFileUpload hook for shared upload logic"
```

---

### Task 5: Refactor FileStrip to use `useFileUpload`

**Files:**
- Modify: `frontend/src/components/editor/FileStrip.tsx`
- Modify: `frontend/src/components/editor/__tests__/FileStrip.test.tsx`

- [ ] **Step 1: Run existing FileStrip tests to confirm baseline**

Run: `just test-frontend` (unsandboxed)
Expected: All tests PASS

- [ ] **Step 2: Refactor FileStrip to use the hook**

In `frontend/src/components/editor/FileStrip.tsx`:

1. Remove `useRef` for `fileInputRef` (line 30)
2. Remove `handleUpload` function (lines 120-143)
3. Import and use the hook:

```ts
import { useFileUpload } from './useFileUpload'
```

Inside the component, after the existing state declarations, add:

```ts
const { triggerUpload, uploading: uploadOperating, inputProps: uploadInputProps } = useFileUpload({
  filePath,
  multiple: true,
  onStart: () => setError(null),
  onSuccess: () => void loadAssets(),
  onError: setError,
})
```

Update `controlsDisabled` to include `uploadOperating`:

```ts
const controlsDisabled = disabled || operating || uploadOperating
```

Replace the `<input>` element and the upload button's `onClick`:

```tsx
<button
  type="button"
  onClick={triggerUpload}
  disabled={controlsDisabled}
  className="w-20 h-20 rounded-lg border-2 border-dashed border-border flex items-center justify-center text-muted hover:border-accent hover:text-accent transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
  aria-label="Upload file"
>
  <Plus size={24} />
</button>

<input {...uploadInputProps} />
```

Remove the `useRef` import if no longer needed (check if other refs remain — `fileInputRef` was the only ref in FileStrip, but the hook manages its own ref internally).

Remove `uploadAssets` from the imports since the hook handles that now. Keep `fetchPostAssets`, `deletePostAsset`, `renamePostAsset`.

- [ ] **Step 3: Run existing FileStrip tests to verify refactor didn't break anything**

Run: `just test-frontend` (unsandboxed)
Expected: All tests PASS (the upload error test may need minor adjustment if the mock target changed — verify and fix if needed)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/editor/FileStrip.tsx \
       frontend/src/components/editor/__tests__/FileStrip.test.tsx
git commit -m "refactor: use useFileUpload hook in FileStrip"
```

---

### Task 6: Wire image button in MarkdownToolbar and EditorPage

**Files:**
- Modify: `frontend/src/components/editor/MarkdownToolbar.tsx`
- Modify: `frontend/src/pages/EditorPage.tsx`
- Modify: `frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx`

- [ ] **Step 1: Write failing tests for image button behavior in toolbar**

Add to `frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx`:

```ts
it('image button calls onImageClick when provided', async () => {
  const onImageClick = vi.fn()
  const ref = createRef<HTMLTextAreaElement>()
  const user = userEvent.setup()

  render(
    <MarkdownToolbar
      textareaRef={ref}
      value=""
      onChange={() => {}}
      onImageClick={onImageClick}
    />,
  )

  await user.click(screen.getByLabelText(/^Image/))
  expect(onImageClick).toHaveBeenCalledOnce()
})

it('image button is disabled when onImageClick is not provided', () => {
  const ref = createRef<HTMLTextAreaElement>()
  render(
    <MarkdownToolbar textareaRef={ref} value="" onChange={() => {}} />,
  )

  expect(screen.getByLabelText(/^Image/)).toBeDisabled()
})

it('image button is disabled when imageUploading is true', () => {
  const ref = createRef<HTMLTextAreaElement>()
  render(
    <MarkdownToolbar
      textareaRef={ref}
      value=""
      onChange={() => {}}
      onImageClick={() => {}}
      imageUploading
    />,
  )

  expect(screen.getByLabelText(/^Image/)).toBeDisabled()
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-frontend` (unsandboxed)
Expected: New tests FAIL (props not accepted yet)

- [ ] **Step 3: Update MarkdownToolbar to accept image props and handle image button specially**

In `frontend/src/components/editor/MarkdownToolbar.tsx`, update the props interface:

```ts
interface MarkdownToolbarProps {
  textareaRef: RefObject<HTMLTextAreaElement | null>
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  onImageClick?: () => void
  imageUploading?: boolean
}
```

Update the component to handle the image button as a special case:

```ts
export default function MarkdownToolbar({
  textareaRef,
  value,
  onChange,
  disabled,
  onImageClick,
  imageUploading,
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
    if (!onImageClick) return 'Save post first to add images'
    if (imageUploading) return 'Uploading...'
    return `Image (${shortcut})`
  }

  return (
    <div className="flex items-center gap-1 mb-2">
      {buttons.map(({ key, label, Icon, shortcut }) => {
        const isImage = key === 'image'
        const isDisabled = isImage
          ? disabled || !onImageClick || imageUploading
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
                       isImage && imageUploading ? ' animate-pulse' : ''
                     }`}
            title={title}
            aria-label={`${label} (${shortcut})`}
          >
            <Icon size={16} />
          </button>
        )
      })}
    </div>
  )
}
```

- [ ] **Step 4: Wire up image upload in EditorPage**

In `frontend/src/pages/EditorPage.tsx`:

Add import for the hook:

```ts
import { useFileUpload } from '@/components/editor/useFileUpload'
```

Inside the component, after `showFileStrip`, add:

```ts
const imageUploadEnabled = showFileStrip && effectiveFilePath !== null

const {
  triggerUpload: triggerImageUpload,
  uploading: imageUploading,
  inputProps: imageInputProps,
} = useFileUpload({
  filePath: imageUploadEnabled ? effectiveFilePath : null,
  accept: 'image/*',
  multiple: false,
  onSuccess: (filenames) => {
    for (const name of filenames) {
      handleInsertAtCursor(`![${name}](${name})`)
    }
  },
  onError: setError,
})
```

Add the image shortcut to `handleEditorKeyDown`. After the blockquote check and before the `!e.shiftKey` guard, add:

```ts
} else if ((e.key === 'I' || e.key === 'i') && e.shiftKey) {
  if (imageUploadEnabled) {
    e.preventDefault()
    triggerImageUpload()
  }
  return
}
```

Update the MarkdownToolbar usage in JSX to pass the new props:

```tsx
<MarkdownToolbar
  textareaRef={textareaRef}
  value={body}
  onChange={setBody}
  disabled={saving}
  onImageClick={imageUploadEnabled ? triggerImageUpload : undefined}
  imageUploading={imageUploading}
/>
```

Add the hidden file input right after the MarkdownToolbar:

```tsx
<input {...imageInputProps} />
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `just test-frontend` (unsandboxed)
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/editor/MarkdownToolbar.tsx \
       frontend/src/pages/EditorPage.tsx \
       frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx
git commit -m "feat: wire image toolbar button with file upload and keyboard shortcut"
```

---

## Chunk 3: Static checks, final verification, and docs

### Task 7: Run full quality gate and update architecture docs

**Files:**
- Modify: `docs/arch/frontend.md` (if editor toolbar section needs updating)

- [ ] **Step 1: Run full quality gate**

Run: `just check` (unsandboxed)
Expected: All checks PASS. Fix any lint/type errors before proceeding.

- [ ] **Step 2: Update architecture docs if needed**

Check `docs/arch/frontend.md` for any mentions of the editor toolbar or formatting buttons. If the toolbar is documented there, update the button list to include Image and Blockquote.

- [ ] **Step 3: Commit any doc updates**

```bash
git add docs/arch/frontend.md
git commit -m "docs: update frontend architecture with new toolbar buttons"
```

- [ ] **Step 4: Manual browser verification**

Start the dev server (`just start`, unsandboxed) and verify in the browser:

1. Navigate to the post editor (create a new post, save it first)
2. Confirm 8 toolbar buttons are visible in order: Bold, Italic, Heading, Link, Image, Blockquote, Code, Code Block
3. Click Blockquote with text selected — verify `> ` prefixes each line
4. Click Blockquote with no selection — verify `> quote text` placeholder is inserted
5. Click Image — verify file dialog opens with image filter
6. Select an image — verify it uploads and `![filename](filename)` appears at cursor
7. On an unsaved new post — verify Image button is disabled
8. Test keyboard shortcuts: Cmd+Shift+. for blockquote, Cmd+Shift+I for image
9. Verify Cmd+I still triggers italic (not image)

- [ ] **Step 5: Stop the dev server**

Run: `just stop` (unsandboxed)
