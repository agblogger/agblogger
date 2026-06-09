# Footnote and Note Toolbar Buttons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Footnote (`^[...]`) and Note (`::: {.note}`) toolbar buttons in a new Annotations group, with a `calloutAction` factory for extensibility and CSS-styled note boxes.

**Architecture:** Both actions use the existing `WrapAction` shape via a new `calloutAction(type)` factory exported from `toolbarActions.ts`. The Footnote button gets a `Mod+Shift+F` keyboard shortcut wired in `MarkdownEditor.tsx`. Note box appearance is driven entirely by `.prose .note` CSS rules — no backend changes required (the sanitizer already allows `<div class="note">`).

**Tech Stack:** React, TypeScript, Tailwind CSS, Lucide icons (`Superscript`, `StickyNote`), Vitest + Testing Library.

---

### Task 1: `calloutAction` factory and new actions in `toolbarActions.ts`

**Files:**
- Modify: `frontend/src/components/editor/toolbarActions.ts`
- Test: `frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx`

- [ ] **Step 1: Write failing tests for the new actions**

Add the following inside the existing `describe('new toolbar actions', ...)` block in `MarkdownToolbar.test.tsx`, after the existing tests:

```typescript
it('footnote wraps selection in ^[...] syntax', () => {
  const result = wrapSelection('hello world', 6, 11, {
    before: '^[',
    after: ']',
    placeholder: 'footnote text',
  })
  expect(result.newValue).toBe('hello ^[world]')
  expect(result.cursorStart).toBe(8)
  expect(result.cursorEnd).toBe(13)
})

it('footnote inserts placeholder when nothing is selected', () => {
  const result = wrapSelection('hello ', 6, 6, {
    before: '^[',
    after: ']',
    placeholder: 'footnote text',
  })
  expect(result.newValue).toBe('hello ^[footnote text]')
  expect(result.cursorStart).toBe(8)
  expect(result.cursorEnd).toBe(21)
})
```

Also add a new import at the top of the file:

```typescript
import { calloutAction } from '../toolbarActions'
```

And add these tests inside `describe('new toolbar actions', ...)`:

```typescript
it('calloutAction generates a WrapAction with the correct shape', () => {
  const action = calloutAction('note')
  expect(action).toEqual({
    before: '::: {.note}\n',
    after: '\n:::',
    placeholder: 'note text',
    block: true,
  })
})

it('note action inserts fenced div at document start', () => {
  const action = calloutAction('note')
  const result = wrapSelection('', 0, 0, action)
  expect(result.newValue).toBe('::: {.note}\nnote text\n:::')
  expect(result.cursorStart).toBe(12)
  expect(result.cursorEnd).toBe(21)
})

it('note action adds leading newline when not at line start', () => {
  const action = calloutAction('note')
  const result = wrapSelection('some text', 9, 9, action)
  expect(result.newValue).toBe('some text\n::: {.note}\nnote text\n:::')
  expect(result.cursorStart).toBe(22)
  expect(result.cursorEnd).toBe(31)
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
just test-frontend 2>&1 | grep -A3 "calloutAction\|footnote wraps\|footnote inserts\|note action"
```

Expected: failures with "calloutAction is not a function" or similar.

- [ ] **Step 3: Implement `calloutAction` and new actions in `toolbarActions.ts`**

Replace the entire file with:

```typescript
import type { WrapAction } from './wrapSelection'

export function calloutAction(type: string): WrapAction {
  return {
    before: `::: {.${type}}\n`,
    after: '\n:::',
    placeholder: `${type} text`,
    block: true,
  }
}

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
  footnote: { before: '^[', after: ']', placeholder: 'footnote text' },
  note: calloutAction('note'),
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
just test-frontend 2>&1 | grep -A3 "calloutAction\|footnote wraps\|footnote inserts\|note action"
```

Expected: all new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/editor/toolbarActions.ts frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx
git commit -m "feat: add calloutAction factory, footnote and note actions to toolbarActions"
```

---

### Task 2: Footnote and Note buttons in `MarkdownToolbar.tsx`

**Files:**
- Modify: `frontend/src/components/editor/MarkdownToolbar.tsx`
- Test: `frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx`

- [ ] **Step 1: Write failing tests for the new buttons**

In `MarkdownToolbar.test.tsx`, update the existing button-count test and separator-count test, then add new button tests.

Update the test "renders all 16 toolbar buttons including image and blockquote":

```typescript
it('renders all 18 toolbar buttons including image, footnote, and note', () => {
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
  expect(screen.getByLabelText(/^Footnote/)).toBeInTheDocument()
  expect(screen.getByLabelText(/^Note/)).toBeInTheDocument()
})
```

Update the separator count test:

```typescript
it('renders 5 group separators between button groups', () => {
  const ref = createRef<HTMLTextAreaElement>()
  render(<MarkdownToolbar textareaRef={ref} value="" onChange={() => {}} />)
  expect(screen.getAllByRole('separator')).toHaveLength(5)
})
```

Add new button behaviour tests inside `describe('MarkdownToolbar', ...)`:

```typescript
it('footnote button wraps selection in ^[...] syntax', async () => {
  const onChange = vi.fn()
  const textarea = document.createElement('textarea')
  textarea.value = 'hello world'
  textarea.selectionStart = 6
  textarea.selectionEnd = 11
  const ref = { current: textarea }

  const user = userEvent.setup()
  render(<MarkdownToolbar textareaRef={ref} value="hello world" onChange={onChange} />)
  await user.click(screen.getByLabelText(/^Footnote/))
  expect(onChange).toHaveBeenCalledWith('hello ^[world]')
})

it('note button inserts fenced div', async () => {
  const onChange = vi.fn()
  const textarea = document.createElement('textarea')
  textarea.value = ''
  textarea.selectionStart = 0
  textarea.selectionEnd = 0
  const ref = { current: textarea }

  const user = userEvent.setup()
  render(<MarkdownToolbar textareaRef={ref} value="" onChange={onChange} />)
  await user.click(screen.getByLabelText(/^Note/))
  expect(onChange).toHaveBeenCalledWith('::: {.note}\nnote text\n:::')
})

it('footnote button shows keyboard shortcut in title', () => {
  const ref = createRef<HTMLTextAreaElement>()
  render(<MarkdownToolbar textareaRef={ref} value="" onChange={() => {}} />)
  const btn = screen.getByRole('button', { name: /Footnote/ })
  expect(btn.title).toMatch(/Footnote \((Cmd|Ctrl)\+Shift\+F\)/)
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
just test-frontend 2>&1 | grep -A3 "18 toolbar\|5 group\|footnote button\|note button\|footnote.*shortcut"
```

Expected: failures referencing missing Footnote/Note buttons.

- [ ] **Step 3: Implement the new buttons in `MarkdownToolbar.tsx`**

Update the import line at the top:

```typescript
import {
  Bold, Italic, Underline, Strikethrough, Highlighter,
  Heading2, Heading3, Heading4,
  List, ListOrdered,
  Link, ImagePlus, Youtube,
  TextQuote, Code, FileCode,
  Superscript, StickyNote,
  Save, Maximize2, Minimize2,
} from 'lucide-react'
```

Add two entries to the `items` array, after the `{ key: 'codeblock', ... }` entry:

```typescript
  { separator: true },
  { key: 'footnote', label: 'Footnote', Icon: Superscript, shortcut: `${mod}+Shift+F` },
  { key: 'note', label: 'Note', Icon: StickyNote },
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
just test-frontend 2>&1 | grep -A3 "18 toolbar\|5 group\|footnote button\|note button\|footnote.*shortcut"
```

Expected: all new and updated tests PASS.

- [ ] **Step 5: Run full frontend test suite to check for regressions**

```bash
just check-frontend
```

Expected: all tests pass, no type errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/editor/MarkdownToolbar.tsx frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx
git commit -m "feat: add Footnote and Note buttons to markdown editor toolbar"
```

---

### Task 3: `Mod+Shift+F` keyboard shortcut in `MarkdownEditor.tsx`

**Files:**
- Modify: `frontend/src/components/editor/MarkdownEditor.tsx`
- Test: `frontend/src/components/editor/__tests__/MarkdownEditor.test.tsx`

- [ ] **Step 1: Write the failing test**

Add to `describe('MarkdownEditor', ...)` in `MarkdownEditor.test.tsx`:

```typescript
it('applies footnote shortcut (Ctrl+Shift+F) via onChange', async () => {
  const onChange = vi.fn()
  const user = userEvent.setup()
  render(<MarkdownEditor value="hi" onChange={onChange} />)
  const textarea = screen.getByRole<HTMLTextAreaElement>('textbox')
  textarea.focus()
  textarea.setSelectionRange(0, 2)
  await user.keyboard('{Control>}{Shift>}f{/Shift}{/Control}')
  expect(onChange).toHaveBeenCalledWith('^[hi]')
})
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
just test-frontend 2>&1 | grep -A3 "footnote shortcut"
```

Expected: FAIL — `onChange` is not called with `'^[hi]'`.

- [ ] **Step 3: Add the shortcut in `MarkdownEditor.tsx`**

In `handleKeyDown`, add a branch for `Shift+F` inside the shift-combo block. The existing pattern ends with:

```typescript
    } else if (e.key === '&' && e.shiftKey) {
      actionKey = 'orderedList'
    } else if (!e.shiftKey) {
      actionKey = KEY_MAP[e.key.toLowerCase()]
    }
```

Change it to:

```typescript
    } else if (e.key === '&' && e.shiftKey) {
      actionKey = 'orderedList'
    } else if ((e.key === 'f' || e.key === 'F') && e.shiftKey) {
      actionKey = 'footnote'
    } else if (!e.shiftKey) {
      actionKey = KEY_MAP[e.key.toLowerCase()]
    }
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
just test-frontend 2>&1 | grep -A3 "footnote shortcut"
```

Expected: PASS.

- [ ] **Step 5: Run full frontend checks**

```bash
just check-frontend
```

Expected: all tests pass, no type errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/editor/MarkdownEditor.tsx frontend/src/components/editor/__tests__/MarkdownEditor.test.tsx
git commit -m "feat: add Mod+Shift+F keyboard shortcut for footnote"
```

---

### Task 4: Note box CSS in `index.css`

**Files:**
- Modify: `frontend/src/index.css`

- [ ] **Step 1: Add the `.prose .note` styles**

In `frontend/src/index.css`, add after the `.prose blockquote p:last-child` block (around line 143):

```css
.prose .note {
    border: 1px solid var(--color-border-dark);
    border-left: 3px solid var(--color-muted);
    background: var(--color-paper-warm);
    border-radius: 4px;
    padding: 0.75rem 1.25rem;
    margin: 1.5rem 0;
}

.prose .note::before {
    content: "Note";
    display: block;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--color-muted);
    margin-bottom: 0.5rem;
}

.prose .note p:last-child {
    margin-bottom: 0;
}
```

- [ ] **Step 2: Run static checks**

```bash
just check-frontend
```

Expected: passes (CSS changes don't affect TS/lint checks).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/index.css
git commit -m "feat: add prose note callout box styles"
```

---

### Task 5: Final gate

- [ ] **Step 1: Run the full check suite**

```bash
just check
```

Expected: all backend and frontend checks pass with no errors.

- [ ] **Step 2: Start the dev server and verify visually**

```bash
just start
```

Open the editor on any post or page. Verify:
1. Two new buttons appear at the end of the toolbar (superscript icon for Footnote, sticky note icon for Note).
2. A 5th separator divides the Block group from the new Annotations group.
3. Clicking Footnote with selected text wraps it: `^[selected text]`.
4. Clicking Footnote with no selection inserts `^[footnote text]` with placeholder selected.
5. `Mod+Shift+F` triggers the footnote action.
6. Clicking Note inserts a `::: {.note}` fenced div.
7. In the preview pane, a note renders as a styled box with an uppercase "NOTE" label in muted colour and a left accent border.
8. Footnotes render as numbered superscripts linking to a footnotes section at the bottom of the preview.

```bash
just stop
```
