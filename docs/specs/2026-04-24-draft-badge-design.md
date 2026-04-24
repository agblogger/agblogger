# Draft Badge Visibility & Consistency

**Date:** 2026-04-24  
**Status:** Approved

## Problem

Draft state is shown in two places — the post list (PostCard) and the post detail page (PostPage) — but with inconsistent and insufficiently visible styles:

- **PostCard**: subtle gray monospace badge (`bg-muted/10 text-muted border-muted/30`) — easy to miss
- **PostPage**: small amber pill (`bg-amber-100 text-amber-700 rounded-full`) — more visible but stylistically different

## Design

### PostCard — amber mono badge

Replace the gray badge with an amber monospace badge. Same position (inline with the title), same size and shape — only the color changes.

**Before:** `bg-muted/10 text-muted border border-muted/30 rounded`  
**After:** `bg-amber-100 dark:bg-amber-900/20 text-amber-800 dark:text-amber-300 border border-amber-300/50 dark:border-amber-700/50 rounded`

Typography stays the same: `font-mono text-[10px] font-semibold uppercase tracking-widest`.  
Text: "Draft" (unchanged).

### PostPage — draft banner (replacing the current inline badge)

Replace the current small pill + flex row with a more prominent bordered banner below the subtitle. The Publish button moves into the banner.

**Banner structure:**
```
┌─────────────────────────────────────────────────────────┐
│  DRAFT                                    [Publish]      │
│  This post is not publicly visible yet                   │
└─────────────────────────────────────────────────────────┘
```

- Container: `mt-3 px-4 py-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-300 dark:border-amber-700 rounded-lg flex items-center justify-between gap-4`
- Label: `font-mono text-[10px] font-semibold uppercase tracking-widest text-amber-800 dark:text-amber-300`
- Description: `text-xs text-amber-700 dark:text-amber-400 mt-0.5`
- Publish button: unchanged (`px-4 py-2 text-sm font-medium text-white bg-accent hover:bg-accent/90 rounded-lg transition-colors disabled:opacity-50`)

The banner is only shown when `user && post.is_draft` (no change to visibility logic).

## Files Changed

- `frontend/src/components/posts/PostCard.tsx` — badge color classes only
- `frontend/src/pages/PostPage.tsx` — replace pill+row with banner component

## Testing

- Existing PostCard draft badge test updated to expect amber classes
- Existing PostPage draft indicator test updated to expect banner structure and description text
- No new behaviour: visibility logic, publish flow, and dark mode coverage are unchanged
