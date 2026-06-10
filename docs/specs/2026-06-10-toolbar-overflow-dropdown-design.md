# Editor Toolbar Overflow Dropdown

## Overview

The markdown editor toolbar has ~20 formatting buttons. On narrow containers the buttons overflow the available width. This spec describes adding an overflow dropdown so the toolbar always stays on a single row, with Save and Fullscreen always visible on the right.

## Behaviour

- The toolbar renders on a single row at all times.
- Formatting buttons are laid out left-to-right. Any button that would not fit in the available space is hidden from the inline row and moved into an overflow dropdown.
- Save and Fullscreen (the right-side group) are always visible and never overflow. Their container is `flex-shrink-0`.
- A `…` button sits between the formatting buttons and the right-side group. It is always rendered (so its width is always measurable for the overflow calculation) but is `visibility: hidden` when nothing overflows.
- Clicking `…` opens an absolutely-positioned dropdown anchored below the `…` button. Clicking again, clicking outside the dropdown, or pressing `Escape` closes it.
- The dropdown lists overflow items vertically: Lucide icon + label text per button. Where separators fall in the overflow range, an `<hr>` divider is shown in the dropdown.
- Clicking an overflow item fires its action and closes the dropdown.

## Overflow Detection

A `ResizeObserver` watches the toolbar container div. On each observation (and on mount) it:

1. Computes available width: `container.offsetWidth − rightGroup.offsetWidth − overflowButtonWidth − accumulated gaps`.
2. Iterates button refs left-to-right, summing `offsetWidth + gap` until the sum exceeds available width.
3. The first index that would exceed the budget becomes `overflowFrom`. All `items[overflowFrom..]` are hidden from the inline row.
4. If all buttons fit, `overflowFrom` is set to `items.length` (nothing overflows, `…` hidden).

Button refs are collected via a `useRef` array indexed in parallel with the `items` array. The right-side group has its own `ref` for width measurement. The `…` button has a ref for dropdown anchor positioning.

## Component Changes

All changes are confined to `MarkdownToolbar.tsx`. No new files are required.

New state:
- `overflowFrom: number` — first item index that does not fit inline; defaults to `items.length`.
- `dropdownOpen: boolean` — whether the overflow dropdown is visible.

New refs:
- `containerRef` — the outer toolbar `div`, watched by `ResizeObserver`.
- `buttonRefs` — `useRef<(HTMLButtonElement | null)[]>([])`, one entry per `items` entry.
- `overflowBtnRef` — the `…` button, used as dropdown anchor.
- `rightGroupRef` — the Save/Fullscreen container, measured to compute available width.

The existing `items` array, `handleAction`, and Save/Fullscreen rendering are unchanged except:
- Each formatting button gains a `ref` callback into `buttonRefs`.
- The right-side container gains `ref={rightGroupRef}` and `flex-shrink-0`.
- Buttons with index `>= overflowFrom` render with `visibility: hidden` (not `display: none`, so widths remain measurable for recalculation).
- The `…` button is always rendered; it uses `visibility: hidden` (not `display: none`) when `overflowFrom === items.length`.

## Testing

- Unit tests in `MarkdownToolbar.test.tsx` cover: all buttons visible when container is wide; overflow buttons absent from toolbar and present in dropdown when container is narrow; Save and Fullscreen always rendered; dropdown opens/closes on `…` click, outside click, and Escape.
- Existing toolbar tests must continue to pass.
