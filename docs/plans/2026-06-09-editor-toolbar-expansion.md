# Editor Toolbar Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add underline, strikethrough, highlight, H3, H4, bullet list, ordered list, and YouTube embed buttons to the markdown editor toolbar, organised into five groups with visual separators.

**Architecture:** All changes are frontend-only. New actions are added to `toolbarActions.ts` using the existing `WrapAction` shape. `MarkdownToolbar.tsx` gains a `ButtonDef | { separator: true }` union type for its items array and renders separator divs between groups. Keyboard shortcuts for the four common new actions are wired in `MarkdownEditor.tsx` alongside the existing bindings. A single CSS rule in `index.css` covers underline rendering in both the editor preview and published post views (both use the `.prose` class).

**Tech Stack:** React, TypeScript, Tailwind CSS, Lucide React icons, Vitest + Testing Library

---

## File Map

| File | Change |
|---|---|
| `frontend/src/components/editor/toolbarActions.ts` | Add 8 new `WrapAction` entries |
| `frontend/src/index.css` | Add `.prose .underline { text-decoration: underline }` |
| `frontend/src/components/editor/MarkdownToolbar.tsx` | New `ButtonDef \| { separator: true }` union type, restructured items array with separators, updated render loop, new Lucide icon imports |
| `frontend/src/components/editor/MarkdownEditor.tsx` | Add `u: 'underline'` to `KEY_MAP`; add `Mod+Shift+X/8/7` branches in `handleKeyDown` |
| `frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx` | Update button-count test, fix heading label regex, add tests for new buttons and separators |
| `frontend/src/components/editor/__tests__/MarkdownEditor.test.tsx` | Add 4 keyboard shortcut tests |

---

### Task 1: Add 8 new actions to toolbarActions.ts (TDD)

**Files:**
- Modify: `frontend/src/components/editor/toolbarActions.ts`
- Test: `frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx`

- [ ] **Step 1: Write failing wrapSelection tests for the 8 new actions**

Add this `describe` block inside the existing `describe('wrapSelection', ...)` in `__tests__/MarkdownToolbar.test.tsx`:

```typescript
describe('new toolbar actions', () => {
  it('underline wraps selection with bracketed span syntax', () => {
    const result = wrapSelection('hi', 0, 2, {
      before: '[',
      after: ']{.underline}',
      placeholder: 'underlined text',
    })
    expect(result.newValue).toBe('[hi]{.underline}')
    expect(result.cursorStart).toBe(1)
    expect(result.cursorEnd).toBe(3)
  })

  it('strikethrough wraps selection with tilde markers', () => {
    const result = wrapSelection('hi', 0, 2, {
      before: '~~',
      after: '~~',
      placeholder: 'strikethrough text',
    })
    expect(result.newValue).toBe('~~hi~~')
    expect(result.cursorStart).toBe(2)
    expect(result.cursorEnd).toBe(4)
  })

  it('highlight wraps selection with equals markers', () => {
    const result = wrapSelection('hi', 0, 2, {
      before: '==',
      after: '==',
      placeholder: 'highlighted text',
    })
    expect(result.newValue).toBe('==hi==')
    expect(result.cursorStart).toBe(2)
    expect(result.cursorEnd).toBe(4)
  })

  it('h3 inserts block with leading newline and ### prefix', () => {
    const result = wrapSelection('some text', 9, 9, {
      before: '### ',
      after: '',
      placeholder: 'Heading 3',
      block: true,
    })
    expect(result.newValue).toBe('some text\n### Heading 3')
    expect(result.cursorStart).toBe(14)
    expect(result.cursorEnd).toBe(23)
  })

  it('h4 inserts block with leading newline and #### prefix', () => {
    const result = wrapSelection('some text', 9, 9, {
      before: '#### ',
      after: '',
      placeholder: 'Heading 4',
      block: true,
    })
    expect(result.newValue).toBe('some text\n#### Heading 4')
    expect(result.cursorStart).toBe(15)
    expect(result.cursorEnd).toBe(24)
  })

  it('bulletList prefixes each selected line with "- "', () => {
    const result = wrapSelection('line one\nline two', 0, 17, {
      before: '',
      after: '',
      placeholder: 'list item',
      linePrefix: '- ',
      block: true,
    })
    expect(result.newValue).toBe('- line one\n- line two')
    expect(result.cursorStart).toBe(0)
    expect(result.cursorEnd).toBe(21)
  })

  it('orderedList prefixes each selected line with "1. "', () => {
    const result = wrapSelection('line one\nline two', 0, 17, {
      before: '',
      after: '',
      placeholder: 'list item',
      linePrefix: '1. ',
      block: true,
    })
    expect(result.newValue).toBe('1. line one\n1. line two')
    expect(result.cursorStart).toBe(0)
    expect(result.cursorEnd).toBe(23)
  })

  it('youtube inserts iframe block with VIDEO_ID placeholder selected', () => {
    const result = wrapSelection('some text', 9, 9, {
      before: '<iframe src="https://www.youtube.com/embed/',
      after: '" allowfullscreen></iframe>',
      placeholder: 'VIDEO_ID',
      block: true,
    })
    expect(result.newValue).toBe(
      'some text\n<iframe src="https://www.youtube.com/embed/VIDEO_ID" allowfullscreen></iframe>',
    )
    expect(result.cursorStart).toBe(53)
    expect(result.cursorEnd).toBe(61)
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
just test-frontend 2>&1 | grep -E "FAIL|PASS|new toolbar actions" | head -20
```

Expected: 8 failures in the `new toolbar actions` describe block.

- [ ] **Step 3: Add the 8 new actions to toolbarActions.ts**

Replace the entire file content:

```typescript
import type { WrapAction } from './wrapSelection'

export const actions: Record<string, WrapAction> = {
  bold: { before: '**', after: '**', placeholder: 'bold text' },
  italic: { before: '_', after: '_', placeholder: 'italic text' },
  underline: { before: '[', after: ']{.underline}', placeholder: 'underlined text' },
  strikethrough: { before: '~~', after: '~~', placeholder: 'strikethrough text' },
  highlight: { before: '==', after: '==', placeholder: 'highlighted text' },
  heading: { before: '## ', after: '', placeholder: 'Heading', block: true },
  h3: { before: '### ', after: '', placeholder: 'Heading 3', block: true },
  h4: { before: '#### ', after: '', placeholder: 'Heading 4', block: true },
  bulletList: { before: '', after: '', placeholder: 'list item', linePrefix: '- ', block: true },
  orderedList: { before: '', after: '', placeholder: 'list item', linePrefix: '1. ', block: true },
  link: { before: '[', after: '](url)', placeholder: 'link text' },
  blockquote: { before: '', after: '', placeholder: 'quote text', linePrefix: '> ', block: true },
  code: { before: '`', after: '`', placeholder: 'code' },
  codeblock: { before: '```\n', after: '\n```', placeholder: 'code', block: true },
  youtube: {
    before: '<iframe src="https://www.youtube.com/embed/',
    after: '" allowfullscreen></iframe>',
    placeholder: 'VIDEO_ID',
    block: true,
  },
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
just test-frontend 2>&1 | grep -E "FAIL|PASS|new toolbar actions" | head -20
```

Expected: all 8 tests in `new toolbar actions` pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/editor/toolbarActions.ts frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx
git commit -m "feat: add 8 new toolbar action definitions"
```

---

### Task 2: Add .prose .underline CSS rule

**Files:**
- Modify: `frontend/src/index.css`

- [ ] **Step 1: Add the underline rule after the existing .dark .prose mark block**

In `frontend/src/index.css`, locate the block that ends with:
```css
.dark .prose mark {
    background: rgba(217, 164, 6, 0.35);
    color: #e0ddd8;
}
```

Add immediately after it:
```css
.prose .underline {
    text-decoration: underline;
}
```

- [ ] **Step 2: Verify no static check errors**

```bash
just check-static 2>&1 | tail -10
```

Expected: clean exit.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/index.css
git commit -m "feat: add prose underline style for pandoc span output"
```

---

### Task 3: Expand MarkdownToolbar with separators and new buttons (TDD)

**Files:**
- Modify: `frontend/src/components/editor/MarkdownToolbar.tsx`
- Modify: `frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx`

- [ ] **Step 1: Update existing tests that will break and add new toolbar tests**

In `__tests__/MarkdownToolbar.test.tsx`, make the following changes:

**a) Update the button-count test** — change the test name and assertions to cover all 16 buttons:

```typescript
it('renders all 16 toolbar buttons including image and blockquote', () => {
  const ref = createRef<HTMLTextAreaElement>()
  render(
    <MarkdownToolbar textareaRef={ref} value="" onChange={() => {}} onImageClick={() => {}} />,
  )
  expect(screen.getByLabelText(/^Bold/)).toBeInTheDocument()
  expect(screen.getByLabelText(/^Italic/)).toBeInTheDocument()
  expect(screen.getByLabelText(/^Underline/)).toBeInTheDocument()
  expect(screen.getByLabelText(/^Strikethrough/)).toBeInTheDocument()
  expect(screen.getByLabelText(/^Highlight/)).toBeInTheDocument()
  expect(screen.getByLabelText(/^Heading 2/)).toBeInTheDocument()
  expect(screen.getByLabelText(/^Heading 3/)).toBeInTheDocument()
  expect(screen.getByLabelText(/^Heading 4/)).toBeInTheDocument()
  expect(screen.getByLabelText(/^Bullet List/)).toBeInTheDocument()
  expect(screen.getByLabelText(/^Ordered List/)).toBeInTheDocument()
  expect(screen.getByLabelText(/^Link/)).toBeInTheDocument()
  expect(screen.getByLabelText(/^Image/)).toBeInTheDocument()
  expect(screen.getByLabelText(/^YouTube/)).toBeInTheDocument()
  expect(screen.getByLabelText(/^Blockquote/)).toBeInTheDocument()
  expect(screen.getByLabelText(/^Code \(/)).toBeInTheDocument()
  expect(screen.getByLabelText(/^Code Block/)).toBeInTheDocument()
})
```

**b) Fix the heading button test** — `getByLabelText(/^Heading/)` now matches three buttons, causing an error. Change to:

```typescript
// In the test 'heading button inserts with block mode newline':
await user.click(screen.getByLabelText(/^Heading 2/))
```

**c) Add tests for new buttons and separators** — append to the `describe('MarkdownToolbar', ...)` block:

```typescript
it('renders 4 group separators between button groups', () => {
  const ref = createRef<HTMLTextAreaElement>()
  render(<MarkdownToolbar textareaRef={ref} value="" onChange={() => {}} />)
  expect(screen.getAllByRole('separator')).toHaveLength(4)
})

it('underline button inserts bracketed span syntax', async () => {
  const onChange = vi.fn()
  const textarea = document.createElement('textarea')
  textarea.value = 'hello world'
  textarea.selectionStart = 6
  textarea.selectionEnd = 11
  const ref = { current: textarea }

  const user = userEvent.setup()
  render(<MarkdownToolbar textareaRef={ref} value="hello world" onChange={onChange} />)
  await user.click(screen.getByLabelText(/^Underline/))
  expect(onChange).toHaveBeenCalledWith('hello [world]{.underline}')
})

it('strikethrough button wraps selection with tilde markers', async () => {
  const onChange = vi.fn()
  const textarea = document.createElement('textarea')
  textarea.value = 'hello world'
  textarea.selectionStart = 6
  textarea.selectionEnd = 11
  const ref = { current: textarea }

  const user = userEvent.setup()
  render(<MarkdownToolbar textareaRef={ref} value="hello world" onChange={onChange} />)
  await user.click(screen.getByLabelText(/^Strikethrough/))
  expect(onChange).toHaveBeenCalledWith('hello ~~world~~')
})

it('highlight button wraps selection with equals markers', async () => {
  const onChange = vi.fn()
  const textarea = document.createElement('textarea')
  textarea.value = 'hello world'
  textarea.selectionStart = 6
  textarea.selectionEnd = 11
  const ref = { current: textarea }

  const user = userEvent.setup()
  render(<MarkdownToolbar textareaRef={ref} value="hello world" onChange={onChange} />)
  await user.click(screen.getByLabelText(/^Highlight/))
  expect(onChange).toHaveBeenCalledWith('hello ==world==')
})

it('ordered list button prefixes each selected line', async () => {
  const onChange = vi.fn()
  const textarea = document.createElement('textarea')
  textarea.value = 'line one\nline two'
  textarea.selectionStart = 0
  textarea.selectionEnd = 17
  const ref = { current: textarea }

  const user = userEvent.setup()
  render(<MarkdownToolbar textareaRef={ref} value="line one\nline two" onChange={onChange} />)
  await user.click(screen.getByLabelText(/^Ordered List/))
  expect(onChange).toHaveBeenCalledWith('1. line one\n1. line two')
})

it('youtube button inserts iframe placeholder with VIDEO_ID selected', async () => {
  const onChange = vi.fn()
  const textarea = document.createElement('textarea')
  textarea.value = ''
  textarea.selectionStart = 0
  textarea.selectionEnd = 0
  const ref = { current: textarea }

  const user = userEvent.setup()
  render(<MarkdownToolbar textareaRef={ref} value="" onChange={onChange} />)
  await user.click(screen.getByLabelText(/^YouTube/))
  expect(onChange).toHaveBeenCalledWith(
    '<iframe src="https://www.youtube.com/embed/VIDEO_ID" allowfullscreen></iframe>',
  )
})
```

- [ ] **Step 2: Run tests to verify failures are in the expected places**

```bash
just test-frontend 2>&1 | grep -E "FAIL|✓|×" | head -30
```

Expected: failures on the new tests (buttons not yet rendered) and the updated button-count test.

- [ ] **Step 3: Rewrite MarkdownToolbar.tsx**

Replace the entire file:

```typescript
import {
  Bold, Italic, Underline, Strikethrough, Highlighter,
  Heading2, Heading3, Heading4,
  List, ListOrdered,
  Link, ImagePlus, Youtube,
  TextQuote, Code, FileCode,
  Save, Maximize2, Minimize2,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
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

type ButtonDef = {
  key: string
  label: string
  Icon: LucideIcon
  shortcut?: string
}

type ToolbarItem = ButtonDef | { separator: true }

const items: readonly ToolbarItem[] = [
  { key: 'bold', label: 'Bold', Icon: Bold, shortcut: `${mod}+B` },
  { key: 'italic', label: 'Italic', Icon: Italic, shortcut: `${mod}+I` },
  { key: 'underline', label: 'Underline', Icon: Underline, shortcut: `${mod}+U` },
  { key: 'strikethrough', label: 'Strikethrough', Icon: Strikethrough, shortcut: `${mod}+Shift+X` },
  { key: 'highlight', label: 'Highlight', Icon: Highlighter },
  { separator: true },
  { key: 'heading', label: 'Heading 2', Icon: Heading2, shortcut: `${mod}+H` },
  { key: 'h3', label: 'Heading 3', Icon: Heading3 },
  { key: 'h4', label: 'Heading 4', Icon: Heading4 },
  { separator: true },
  { key: 'bulletList', label: 'Bullet List', Icon: List, shortcut: `${mod}+Shift+8` },
  { key: 'orderedList', label: 'Ordered List', Icon: ListOrdered, shortcut: `${mod}+Shift+7` },
  { separator: true },
  { key: 'link', label: 'Link', Icon: Link, shortcut: `${mod}+K` },
  { key: 'image', label: 'Image', Icon: ImagePlus, shortcut: `${mod}+Shift+I` },
  { key: 'youtube', label: 'YouTube', Icon: Youtube },
  { separator: true },
  { key: 'blockquote', label: 'Blockquote', Icon: TextQuote, shortcut: `${mod}+Shift+.` },
  { key: 'code', label: 'Code', Icon: Code, shortcut: `${mod}+E` },
  { key: 'codeblock', label: 'Code Block', Icon: FileCode, shortcut: `${mod}+Shift+E` },
]

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

  return (
    <div className="flex items-center gap-1 mb-2">
      {items.map((item, i) => {
        if ('separator' in item) {
          return (
            <div
              key={`sep-${i}`}
              role="separator"
              className="w-px h-4 bg-border mx-0.5 flex-shrink-0"
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
          : shortcut ? `${label} (${shortcut})` : label
        const ariaLabel = shortcut ? `${label} (${shortcut})` : label

        if (isImage && onImageClick === undefined && imageDisabledReason === undefined) {
          return null
        }

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
            aria-label={ariaLabel}
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

```bash
just test-frontend 2>&1 | grep -E "FAIL|PASS|MarkdownToolbar" | head -30
```

Expected: all toolbar tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/editor/MarkdownToolbar.tsx frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx
git commit -m "feat: expand toolbar with 8 new buttons and group separators"
```

---

### Task 4: Wire 4 new keyboard shortcuts in MarkdownEditor (TDD)

**Files:**
- Modify: `frontend/src/components/editor/MarkdownEditor.tsx`
- Modify: `frontend/src/components/editor/__tests__/MarkdownEditor.test.tsx`

- [ ] **Step 1: Write failing keyboard shortcut tests**

Append these 4 tests to the `describe('MarkdownEditor', ...)` block in `__tests__/MarkdownEditor.test.tsx`:

```typescript
it('applies underline shortcut (Ctrl+U) via onChange', async () => {
  const onChange = vi.fn()
  const user = userEvent.setup()
  render(<MarkdownEditor value="hi" onChange={onChange} />)
  const textarea = screen.getByRole<HTMLTextAreaElement>('textbox')
  textarea.focus()
  textarea.setSelectionRange(0, 2)
  await user.keyboard('{Control>}u{/Control}')
  expect(onChange).toHaveBeenCalledWith('[hi]{.underline}')
})

it('applies strikethrough shortcut (Ctrl+Shift+X) via onChange', async () => {
  const onChange = vi.fn()
  const user = userEvent.setup()
  render(<MarkdownEditor value="hi" onChange={onChange} />)
  const textarea = screen.getByRole<HTMLTextAreaElement>('textbox')
  textarea.focus()
  textarea.setSelectionRange(0, 2)
  await user.keyboard('{Control>}{Shift>}x{/Shift}{/Control}')
  expect(onChange).toHaveBeenCalledWith('~~hi~~')
})

it('applies bullet list shortcut (Ctrl+Shift+8) via onChange', async () => {
  const onChange = vi.fn()
  const user = userEvent.setup()
  render(<MarkdownEditor value="hi" onChange={onChange} />)
  const textarea = screen.getByRole<HTMLTextAreaElement>('textbox')
  textarea.focus()
  textarea.setSelectionRange(0, 2)
  await user.keyboard('{Control>}{Shift>}8{/Shift}{/Control}')
  expect(onChange).toHaveBeenCalledWith('- hi')
})

it('applies ordered list shortcut (Ctrl+Shift+7) via onChange', async () => {
  const onChange = vi.fn()
  const user = userEvent.setup()
  render(<MarkdownEditor value="hi" onChange={onChange} />)
  const textarea = screen.getByRole<HTMLTextAreaElement>('textbox')
  textarea.focus()
  textarea.setSelectionRange(0, 2)
  await user.keyboard('{Control>}{Shift>}7{/Shift}{/Control}')
  expect(onChange).toHaveBeenCalledWith('1. hi')
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
just test-frontend 2>&1 | grep -E "FAIL|underline shortcut|strikethrough shortcut|bullet list shortcut|ordered list shortcut"
```

Expected: 4 failures.

- [ ] **Step 3: Add the new shortcut bindings in MarkdownEditor.tsx**

In `frontend/src/components/editor/MarkdownEditor.tsx`:

**a)** Change `KEY_MAP` from:
```typescript
const KEY_MAP: Record<string, string> = { b: 'bold', i: 'italic', h: 'heading', k: 'link' }
```
to:
```typescript
const KEY_MAP: Record<string, string> = { b: 'bold', i: 'italic', h: 'heading', k: 'link', u: 'underline' }
```

**b)** In `handleKeyDown`, find the `actionKey` assignment block:
```typescript
let actionKey: string | undefined
if (e.key === 'e' || e.key === 'E') {
  actionKey = e.shiftKey ? 'codeblock' : 'code'
} else if ((e.key === '>' || e.key === '.') && e.shiftKey) {
  actionKey = 'blockquote'
} else if (!e.shiftKey) {
  actionKey = KEY_MAP[e.key.toLowerCase()]
}
```

Replace with:
```typescript
let actionKey: string | undefined
if (e.key === 'e' || e.key === 'E') {
  actionKey = e.shiftKey ? 'codeblock' : 'code'
} else if ((e.key === '>' || e.key === '.') && e.shiftKey) {
  actionKey = 'blockquote'
} else if ((e.key === 'x' || e.key === 'X') && e.shiftKey) {
  actionKey = 'strikethrough'
} else if (e.key === '8' && e.shiftKey) {
  actionKey = 'bulletList'
} else if (e.key === '7' && e.shiftKey) {
  actionKey = 'orderedList'
} else if (!e.shiftKey) {
  actionKey = KEY_MAP[e.key.toLowerCase()]
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
just test-frontend 2>&1 | grep -E "FAIL|PASS|shortcut" | head -20
```

Expected: all 4 new shortcut tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/editor/MarkdownEditor.tsx frontend/src/components/editor/__tests__/MarkdownEditor.test.tsx
git commit -m "feat: add underline, strikethrough, bullet list, ordered list keyboard shortcuts"
```

---

### Task 5: Run full frontend gate and final commit

- [ ] **Step 1: Run the full frontend check**

```bash
just check-frontend 2>&1 | tail -20
```

Expected: all static checks and tests pass with no errors.

- [ ] **Step 2: If any type errors appear, fix them**

Common issues to watch for:
- `LucideIcon` type not exported — if so, replace with `React.ComponentType<{ size?: number }>` for the `Icon` field type
- `role="separator"` not accepted on `<div>` — if so, cast with `role={"separator" as React.AriaRole}`
- Unused imports from old icon set

- [ ] **Step 3: Stop any running dev server, start fresh, and do a quick smoke test**

```bash
just stop && just start && just health
```

Open the editor in a browser and verify:
1. All 16 buttons are visible in a single row with 4 dividers
2. Click Underline on selected text — produces `[text]{.underline}` in the textarea
3. Click YouTube — inserts `<iframe ...VIDEO_ID...>` with VIDEO_ID visually selected
4. Preview pane shows underlined text (`.underline` CSS applied)
5. Keyboard shortcuts: Ctrl+U (underline), Ctrl+Shift+X (strikethrough), Ctrl+Shift+8 (bullet), Ctrl+Shift+7 (ordered list)

```bash
just stop
```
