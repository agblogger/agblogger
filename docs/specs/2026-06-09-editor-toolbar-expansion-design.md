# Editor Toolbar Expansion Design

## Overview

Add eight new buttons to the markdown editor toolbar: underline, strikethrough, highlight, H3, H4, bullet list, ordered list, and YouTube embed. Reorganise the toolbar into five groups separated by thin vertical dividers. All changes are frontend-only — the backend sanitizer already allows every tag these buttons produce.

## Toolbar Layout

Single row with group separators. Left to right:

| Group | Buttons | Keyboard shortcuts |
|---|---|---|
| Inline formatting | Bold, Italic, Underline, Strikethrough, Highlight | Mod+B, Mod+I, Mod+U, Mod+Shift+X, — |
| Headings | H2, H3, H4 | Mod+H, —, — |
| Lists | Bullet, Ordered | Mod+Shift+8, Mod+Shift+7 |
| Media | Link, Image, YouTube | Mod+K, Mod+Shift+I, — |
| Block | Blockquote, Code, Code Block | Mod+Shift+., Mod+E, Mod+Shift+E |

Save and Fullscreen remain pinned to the right, unchanged.

Separators are `{ separator: true }` sentinel objects in the buttons config, rendered as a thin vertical line (`w-px h-4 bg-border`). The `buttons` array type becomes a union: `ButtonDef | { separator: true }`.

## Markdown Syntax

All new actions are handled in `toolbarActions.ts` using the existing `WrapAction` shape. No backend changes are needed.

| Button | Action config | Rendered HTML | Notes |
|---|---|---|---|
| Underline | `before: '['`, `after: ']{.underline}'`, `placeholder: 'underlined text'` | `<span class="underline">text</span>` | Pandoc `bracketed_spans` (on by default); `span`+`class` already sanitizer-allowed |
| Strikethrough | `before: '~~'`, `after: '~~'`, `placeholder: 'strikethrough text'` | `<del>text</del>` | Pandoc `strikeout` (default); `del` already allowed |
| Highlight | `before: '=='`, `after: '=='`, `placeholder: 'highlighted text'` | `<mark>text</mark>` | `+mark` already in format string; `mark` already allowed |
| H3 | `before: '### '`, `after: ''`, `placeholder: 'Heading 3'`, `block: true` | `<h3>` | Standard markdown |
| H4 | `before: '#### '`, `after: ''`, `placeholder: 'Heading 4'`, `block: true` | `<h4>` | Standard markdown |
| Bullet list | `linePrefix: '- '`, `placeholder: 'list item'`, `block: true` | `<ul><li>` | Uses existing `linePrefix` mode; prefixes every selected line |
| Ordered list | `linePrefix: '1. '`, `placeholder: 'list item'`, `block: true` | `<ol><li>` | Same |
| YouTube | `before: '<iframe src="https://www.youtube.com/embed/'`, `after: '" allowfullscreen></iframe>'`, `placeholder: 'VIDEO_ID'`, `block: true` | `<iframe …>` | Cursor selects `VIDEO_ID` so user pastes/types immediately; YouTube iframes already sanitizer-handled |

## Keyboard Shortcuts

Shortcuts are wired in `MarkdownEditor.tsx`, not the toolbar (toolbar shows them as tooltip text only).

**Add to `KEY_MAP`** (Mod+key, no shift):
- `u: 'underline'`

**Add to `handleKeyDown`** (before the `KEY_MAP` lookup, shift-combos):
- `Mod+Shift+X` → `strikethrough`
- `Mod+Shift+8` → `bulletList`
- `Mod+Shift+7` → `orderedList`

Highlight, H3, H4, and YouTube get no shortcuts.

## CSS

`[text]{.underline}` renders as `<span class="underline">text</span>`. This needs a CSS rule in two places:

1. **Preview styles** — wherever the editor preview panel's prose styles are defined
2. **Published post styles** — wherever rendered post HTML is styled for readers

Rule: `.underline { text-decoration: underline; }`

The exact file paths are confirmed during implementation by locating where existing prose/preview CSS lives in the frontend.

## Files Changed

Frontend only:

- `frontend/src/components/editor/toolbarActions.ts` — 8 new action entries
- `frontend/src/components/editor/MarkdownToolbar.tsx` — separator type support, 8 new buttons in 5 groups with dividers
- `frontend/src/components/editor/MarkdownEditor.tsx` — 4 new shortcut bindings
- Preview CSS file — `.underline` rule
- Published post CSS file — `.underline` rule

## Testing

Follow TDD: write failing tests first, then implement.

**`wrapSelection` unit tests** — one per new action verifying the inserted markdown string, cursor start, and cursor end for both the selection and no-selection cases. Cover the YouTube action's `before`/`after` split positioning `VIDEO_ID` as the selected range.

**`MarkdownToolbar` tests:**
- Updated button-count assertion (8 → 16 formatting buttons)
- Each new button calls `onChange` with correct markdown (sample the most non-obvious: underline, youtube, ordered list)
- Separators render as non-interactive divider elements

**`MarkdownEditor` keyboard shortcut tests** — fire `keydown` events for the 4 new bindings and assert `onChange` is called with the expected wrapped text.
