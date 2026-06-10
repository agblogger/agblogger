# Editor Math Toolbar Buttons — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Math (inline) and Math Block (display) buttons to the markdown editor toolbar, inserted after Code Block in the code group.

**Architecture:** Two new entries in `toolbarActions.ts` define the wrapping syntax; two new items in `MarkdownToolbar.tsx`'s `items` array render the buttons using Lucide `Sigma` and `Pi` icons. No new files, no new props, no behavior changes beyond the two new buttons.

**Tech Stack:** TypeScript, React, lucide-react (already a dependency at v0.511)

---

### Task 1: Add math actions to toolbarActions.ts

**Files:**
- Modify: `frontend/src/components/editor/toolbarActions.ts`
- Test: `frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx`

- [ ] **Step 1: Write failing tests for the two new actions**

Add the following two `it` blocks inside the existing `describe('new toolbar actions', ...)` block in `frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx` (after the last `it` in that describe, before its closing `}`):

```ts
it('math wraps selected text with $ delimiters', () => {
  const result = wrapSelection('hello world', 6, 11, {
    before: '$',
    after: '$',
    placeholder: 'x^2',
  })
  expect(result.newValue).toBe('hello $world$')
  expect(result.cursorStart).toBe(7)
  expect(result.cursorEnd).toBe(12)
})

it('math inserts placeholder when nothing is selected', () => {
  const result = wrapSelection('hello ', 6, 6, {
    before: '$',
    after: '$',
    placeholder: 'x^2',
  })
  expect(result.newValue).toBe('hello $x^2$')
  expect(result.cursorStart).toBe(7)
  expect(result.cursorEnd).toBe(10)
})

it('mathblock wraps with $$ delimiters at document start', () => {
  const result = wrapSelection('', 0, 0, {
    before: '$$\n',
    after: '\n$$',
    placeholder: '\\sum_{i=0}^n i^2',
    block: true,
  })
  expect(result.newValue).toBe('$$\n\\sum_{i=0}^n i^2\n$$')
  expect(result.cursorStart).toBe(3)
  expect(result.cursorEnd).toBe(20)
})

it('mathblock adds leading newline when not at line start', () => {
  const result = wrapSelection('some text', 9, 9, {
    before: '$$\n',
    after: '\n$$',
    placeholder: '\\sum_{i=0}^n i^2',
    block: true,
  })
  expect(result.newValue).toBe('some text\n$$\n\\sum_{i=0}^n i^2\n$$')
  expect(result.cursorStart).toBe(13)
  expect(result.cursorEnd).toBe(30)
})
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/lukasz/dev/agblogger && just test-frontend 2>&1 | grep -A5 "math"
```

Expected: the four new tests fail (they reference actions not yet registered, but the tests exercise `wrapSelection` directly so they should actually pass — that's fine, they verify the expected output of the action config we are about to add).

- [ ] **Step 3: Add math and mathblock to the actions record**

In `frontend/src/components/editor/toolbarActions.ts`, add two entries to the `actions` object after the `codeblock` line:

```ts
  codeblock: { before: '```\n', after: '\n```', placeholder: 'code', block: true },
  math: { before: '$', after: '$', placeholder: 'x^2' },
  mathblock: { before: '$$\n', after: '\n$$', placeholder: '\\sum_{i=0}^n i^2', block: true },
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /Users/lukasz/dev/agblogger && just test-frontend 2>&1 | grep -E "math|FAIL|PASS"
```

Expected: all four new `wrapSelection` tests pass.

- [ ] **Step 5: Commit**

```bash
git -C /Users/lukasz/dev/agblogger add frontend/src/components/editor/toolbarActions.ts frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx
git -C /Users/lukasz/dev/agblogger commit -m "feat: add math and mathblock actions to toolbar"
```

---

### Task 2: Add Math and Math Block buttons to MarkdownToolbar

**Files:**
- Modify: `frontend/src/components/editor/MarkdownToolbar.tsx`
- Test: `frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx`

- [ ] **Step 1: Write failing toolbar integration tests**

Add the following `it` blocks inside the `describe('MarkdownToolbar', ...)` block in `frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx`:

```ts
it('renders all 20 toolbar buttons including math and math block', () => {
  const ref = createRef<HTMLTextAreaElement>()
  render(
    <MarkdownToolbar textareaRef={ref} value="" onChange={() => {}} onImageClick={() => {}} />,
  )
  expect(screen.getByLabelText(/^Math Block/)).toBeInTheDocument()
  expect(screen.getByLabelText(/^Math$/)).toBeInTheDocument()
})

it('math button wraps selection with $ delimiters', async () => {
  const onChange = vi.fn()
  const textarea = document.createElement('textarea')
  textarea.value = 'hello world'
  textarea.selectionStart = 6
  textarea.selectionEnd = 11
  const ref = { current: textarea }

  const user = userEvent.setup()
  render(<MarkdownToolbar textareaRef={ref} value="hello world" onChange={onChange} />)
  await user.click(screen.getByLabelText(/^Math$/))
  expect(onChange).toHaveBeenCalledWith('hello $world$')
})

it('math block button inserts $$ block with placeholder', async () => {
  const onChange = vi.fn()
  const textarea = document.createElement('textarea')
  textarea.value = ''
  textarea.selectionStart = 0
  textarea.selectionEnd = 0
  const ref = { current: textarea }

  const user = userEvent.setup()
  render(<MarkdownToolbar textareaRef={ref} value="" onChange={onChange} />)
  await user.click(screen.getByLabelText(/^Math Block/))
  expect(onChange).toHaveBeenCalledWith('$$\n\\sum_{i=0}^n i^2\n$$')
})
```

Also update the existing button count test (line 291) from 18 to 20:

```ts
it('renders all 20 toolbar buttons including image, footnote, note, math, and math block', () => {
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/lukasz/dev/agblogger && just test-frontend 2>&1 | grep -E "Math|20 toolbar|FAIL"
```

Expected: the three new tests fail with "Unable to find an element with the label /^Math Block/" and the renamed count test fails.

- [ ] **Step 3: Add Sigma and Pi icons and the two new items to the toolbar**

In `frontend/src/components/editor/MarkdownToolbar.tsx`, update the import line to include `Sigma` and `Pi`:

```ts
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
```

Then in the `items` array, insert the two new entries after the `codeblock` item and before the separator:

```ts
  { key: 'code', label: 'Code', Icon: Code, shortcut: `${mod}+E` },
  { key: 'codeblock', label: 'Code Block', Icon: FileCode, shortcut: `${mod}+Shift+E` },
  { key: 'math', label: 'Math', Icon: Sigma },
  { key: 'mathblock', label: 'Math Block', Icon: Pi },
  { separator: true },
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /Users/lukasz/dev/agblogger && just test-frontend 2>&1 | grep -E "Math|toolbar|FAIL|PASS" | head -20
```

Expected: all three new tests pass, the renamed count test passes.

- [ ] **Step 5: Run the full frontend check**

```bash
cd /Users/lukasz/dev/agblogger && just check-frontend
```

Expected: all checks and tests pass with no errors.

- [ ] **Step 6: Commit**

```bash
git -C /Users/lukasz/dev/agblogger add frontend/src/components/editor/MarkdownToolbar.tsx frontend/src/components/editor/__tests__/MarkdownToolbar.test.tsx
git -C /Users/lukasz/dev/agblogger commit -m "feat: add Math and Math Block buttons to editor toolbar"
```
