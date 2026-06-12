# Word Count & Reading Time — Design

## Overview

Display word count and estimated reading time in the post page header, giving readers an upfront sense of a post's length before they begin.

## Scope

Post pages (`/post/<slug>`) and timeline cards. The post page shows the full
`"N min read · X words"` string; timeline cards show the compact `"N min read"`
form (see Frontend below). Search results and other listing views remain out of
scope.

## Backend

### Word count computation

A new pure utility function `count_words(body: str) -> int` in `backend/utils/text.py`:

1. Strip fenced code blocks (` ``` ... ``` `) — code tokens inflate the count beyond what a reader actually reads.
2. Strip inline code (`` `...` ``).
3. Split on whitespace and return `len(tokens)`.

### Cache storage

`PostCache` (a `CacheBase` table — no Alembic migration required) gains:

```python
word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
```

`cache_service.py` calls `count_words(post_data.content)` alongside the existing hash and render steps when building each `PostCache` row.

### API schema

`PostSummary` (in `backend/schemas/post.py`) gains:

```python
word_count: int = 0
```

`PostDetail` inherits it from `PostSummary`, so both the list and detail
responses carry `word_count`. `post_service.py` passes `post.word_count` through
when constructing both the `PostSummary` list items and the `PostDetail` response.

## Frontend

### Utility

`frontend/src/utils/readingTime.ts` exports:

```ts
export function readingTimeShort(wordCount: number): string
export function readingTime(wordCount: number): string
```

- Reading speed: 200 WPM; minutes = `Math.ceil(wordCount / 200)`, minimum 1.
- `readingTimeShort` returns just `"5 min read"` (used on timeline cards).
- `readingTime` appends the word count: `"5 min read · 1 234 words"`. Word count
  formatted with `wordCount.toLocaleString()` (browser locale, no hardcoded
  separator); used in the post page header.

### PostPage display

A new metadata item is inserted into the existing `flex items-center gap-4 flex-wrap` row in `PostPage.tsx`, using the `Clock` icon from lucide-react:

```tsx
{post.word_count > 0 && (
  <div className="flex items-center gap-1.5">
    <Clock size={14} aria-hidden="true" />
    <span>{readingTime(post.word_count)}</span>
  </div>
)}
```

Placed after the author item and before the view count, matching the temporal left-to-right reading of the metadata row.

### Timeline card display

`PostCard.tsx` adds a compact reading-time item to its `date · author · labels`
metadata row, using `readingTimeShort` (no icon, matching the card's text-only
metadata style):

```tsx
{post.word_count > 0 && (
  <>
    <span className="text-border-dark">·</span>
    <span className="text-xs text-muted">{readingTimeShort(post.word_count)}</span>
  </>
)}
```

Placed after the author item and before the labels, mirroring the post page
ordering.

## Testing

### Backend

- `tests/utils/test_text.py` (new): Hypothesis property-based tests for `count_words` — empty string returns 0; plain prose counts whitespace-delimited tokens; fenced code blocks excluded; inline code excluded.
- `tests/api/test_posts.py`: existing post detail tests assert `word_count` is present and positive.

### Frontend

- `frontend/src/utils/__tests__/readingTime.test.ts` (new): unit tests for `readingTime` — zero input skipped, short post yields "1 min read", multi-minute post, locale-formatted word count.
- `frontend/src/pages/__tests__/PostPage.test.tsx`: existing tests gain assertion that the reading time string is rendered when mock post has non-zero `word_count`.
