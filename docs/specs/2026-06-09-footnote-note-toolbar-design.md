# Footnote and Note Toolbar Buttons Design

## Overview

Add two new toolbar buttons — Footnote and Note — in a new Annotations group at the end of the markdown editor toolbar. The footnote button inserts inline pandoc footnote syntax; the note button inserts a fenced div callout styled as a visible note box. Frontend-only change; no backend modifications required.

## Toolbar Layout

A new Annotations group is appended after the existing Block group (Blockquote, Code, Code Block), separated by a vertical divider:

| Group | Buttons | Shortcuts |
|---|---|---|
| Annotations | Footnote, Note | Mod+Shift+F, — |

Icons: `Superscript` (Lucide) for Footnote, `StickyNote` (Lucide) for Note.

## Markdown Syntax

### Footnote

Inline pandoc footnote syntax using the existing `WrapAction` shape:

```
{ before: '^[', after: ']', placeholder: 'footnote text' }
```

- No selection: inserts `^[footnote text]` with "footnote text" selected.
- With selection: selected text moves inside the brackets, becoming the footnote content.

### Note

Fenced div via a `calloutAction` factory in `toolbarActions.ts`:

```typescript
function calloutAction(type: string): WrapAction {
  return {
    before: `::: {.${type}}\n`,
    after: '\n:::',
    placeholder: `${type} text`,
    block: true,
  }
}
```

`calloutAction('note')` inserts:

```
::: {.note}
note text
:::
```

with "note text" selected. The factory makes adding future callout types (`.warning`, `.tip`) a one-liner.

Pandoc renders `::: {.note}` as `<div class="note">...</div>`. The sanitizer already permits this: `div` is in `_ALLOWED_TAGS` and `class` is in `_GLOBAL_ALLOWED_ATTRS` in `backend/pandoc/renderer.py`.

## CSS

Added to `frontend/src/index.css` under `.prose`:

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

Visually distinct from blockquote (which uses the accent color and italic text) while remaining consistent with the warm palette. The "NOTE" label is a CSS pseudo-element — purely presentational, not part of the markdown source.

## Keyboard Shortcut

Mod+Shift+F → `footnote`. Wired in `MarkdownEditor.tsx` alongside existing shift-combo shortcuts. No shortcut for Note.

## Files Changed

Frontend only:

| File | Change |
|---|---|
| `frontend/src/components/editor/toolbarActions.ts` | `calloutAction` factory, `footnote` action, `note: calloutAction('note')` |
| `frontend/src/components/editor/MarkdownToolbar.tsx` | `Superscript` + `StickyNote` imports, separator + 2 new buttons in items array |
| `frontend/src/components/editor/MarkdownEditor.tsx` | Mod+Shift+F shortcut binding |
| `frontend/src/index.css` | `.prose .note` styles |

## Testing

Follow TDD: write failing tests first, then implement.

**`wrapSelection` / `toolbarActions` unit tests:**
- `footnote` with selection: selected text wraps in `^[...]`
- `footnote` without selection: inserts `^[footnote text]` with correct cursor range
- `calloutAction('note')`: returns correct `WrapAction` shape
- `note` without selection: inserts fenced div block with "note text" selected
- `note` with existing text (block: true): prepends newline when not at line start

**`MarkdownToolbar` tests:**
- Footnote and Note buttons render
- Clicking Footnote calls `onChange` with footnote-wrapped markdown
- Clicking Note calls `onChange` with fenced div markdown

**`MarkdownEditor` keyboard shortcut test:**
- Mod+Shift+F fires the footnote action and calls `onChange` with correct output
