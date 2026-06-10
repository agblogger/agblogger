# Editor Math Toolbar Buttons — Design

## Overview

Add two toolbar buttons to the markdown editor: **Math** (inline) and **Math Block** (display). KaTeX rendering is already supported end-to-end; this change exposes that capability through the toolbar UI.

## Placement

The new buttons are inserted after `codeblock` in the code group, before the next separator:

```
code | codeblock | math | mathblock  |  footnote | note
```

This mirrors the inline/block pairing of code, making discoverability intuitive for writers.

## Actions

Two new entries in `toolbarActions.ts`:

| Key         | `before`    | `after`  | `placeholder`           | `block` |
|-------------|-------------|----------|-------------------------|---------|
| `math`      | `$`         | `$`      | `x^2`                   | —       |
| `mathblock` | `$$\n`      | `\n$$`   | `\sum_{i=0}^n i^2`      | `true`  |

- Inline math wraps selection (or placeholder) with single `$` delimiters.
- Math block uses `block: true` so a leading newline is inserted when not at the start of a line.
- No keyboard shortcuts assigned.

## Icons

From `lucide-react` (already a project dependency, v0.511):

- **Math**: `Sigma` icon, label `"Math"`
- **Math Block**: `Pi` icon, label `"Math Block"`

## Toolbar Definition

In `MarkdownToolbar.tsx`, two `ButtonDef` entries are inserted after `codeblock`:

```ts
{ key: 'math',      label: 'Math',       Icon: Sigma },
{ key: 'mathblock', label: 'Math Block', Icon: Pi    },
```

No changes to `MarkdownToolbar`'s props or rendering logic are required.

## Testing

New unit tests in the existing `MarkdownToolbar.test.tsx` (wrapSelection section):

- `math` action wraps selected text with `$...$`
- `math` action inserts placeholder `$x^2$` when no selection
- `mathblock` action wraps with `$$\n...\n$$` and prepends newline when not at line start
