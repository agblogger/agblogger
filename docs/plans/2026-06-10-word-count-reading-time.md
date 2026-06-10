# Word Count & Reading Time Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add word count and estimated reading time to the post page header, computed from the markdown body at cache time and displayed as "N min read · X words".

**Architecture:** A new `count_words` backend utility strips code blocks then splits on whitespace; the result is stored in `PostCache` (a CacheBase table — no migration needed) and surfaced through `PostDetail`. The frontend derives reading time via a `readingTime(wordCount)` utility and renders it in the existing metadata row using the `Clock` icon.

**Tech Stack:** Python (Hypothesis for property-based tests), FastAPI/SQLAlchemy, React/TypeScript, Vitest, Tailwind, lucide-react.

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `backend/utils/text.py` | Create | `count_words` pure utility |
| `backend/models/post.py` | Modify | Add `word_count` column to `PostCache` |
| `backend/schemas/post.py` | Modify | Add `word_count` field to `PostDetail` |
| `backend/services/post_service.py` | Modify | Pass `word_count` in `PostDetail` response |
| `backend/services/cache_service.py` | Modify | Call `count_words` when building `PostCache` rows |
| `tests/test_utils/test_text.py` | Create | Hypothesis property-based tests for `count_words` |
| `tests/test_api/test_api_integration.py` | Modify | Assert `word_count` present + positive in post detail |
| `frontend/src/api/client.ts` | Modify | Add `word_count: number` to `PostDetail` interface |
| `frontend/src/utils/readingTime.ts` | Create | `readingTime(wordCount)` utility |
| `frontend/src/utils/__tests__/readingTime.test.ts` | Create | Unit tests for `readingTime` |
| `frontend/src/pages/PostPage.tsx` | Modify | Render reading time in metadata row |
| `frontend/src/pages/__tests__/PostPage.test.tsx` | Modify | Assert reading time rendered for non-zero `word_count` |

---

### Task 1: `count_words` utility + tests

**Files:**
- Create: `backend/utils/text.py`
- Create: `tests/test_utils/test_text.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_utils/test_text.py
"""Tests for text utility functions."""

from __future__ import annotations

import string

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from backend.utils.text import count_words

_WORD = st.text(alphabet=string.ascii_letters + string.digits, min_size=1, max_size=15)
_PROSE = st.lists(_WORD, min_size=0, max_size=100)


def test_empty_string_returns_zero() -> None:
    assert count_words("") == 0


def test_plain_prose() -> None:
    assert count_words("Hello world this is a post") == 6


def test_fenced_code_block_excluded() -> None:
    body = "Before code.\n```\nsome code tokens here\n```\nAfter code."
    assert count_words(body) == 4  # "Before", "code.", "After", "code."


def test_inline_code_excluded() -> None:
    body = "Use `foo = 1` to assign"
    # strip "`foo = 1`" → "Use  to assign" → 3 words
    assert count_words(body) == 3


def test_multiple_fenced_blocks_excluded() -> None:
    body = "First.\n```\ncode1\n```\nMiddle.\n```\ncode2\n```\nLast."
    assert count_words(body) == 3  # "First.", "Middle.", "Last."


@given(_PROSE)
@settings(max_examples=200)
def test_plain_prose_word_count_property(words: list[str]) -> None:
    body = " ".join(words)
    assert count_words(body) == len(words)


@given(
    st.text(alphabet=string.ascii_letters + " \n", min_size=0, max_size=200),
    st.text(alphabet=string.ascii_letters, min_size=1, max_size=50),
)
@settings(max_examples=200)
def test_fenced_code_excluded_property(prose: str, code: str) -> None:
    body = f"{prose}\n```\n{code}\n```\n"
    prose_count = len(prose.split())
    assert count_words(body) == prose_count
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
just test-backend -- tests/test_utils/test_text.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.utils.text'`

- [ ] **Step 3: Implement `count_words`**

```python
# backend/utils/text.py
"""Text processing utilities."""

from __future__ import annotations

import re


def count_words(body: str) -> int:
    """Count prose words in a markdown body.

    Strips fenced code blocks and inline code before counting so that
    code tokens do not inflate the reading-time estimate.
    """
    body = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
    body = re.sub(r"`[^`\n]*`", "", body)
    return len(body.split())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
just test-backend -- tests/test_utils/test_text.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/utils/text.py tests/test_utils/test_text.py
git commit -m "feat: add count_words utility with property-based tests"
```

---

### Task 2: Add `word_count` column to `PostCache`

**Files:**
- Modify: `backend/models/post.py`

Note: `PostCache` uses `CacheBase` — the table is dropped and recreated on every startup, so **no Alembic migration is needed**.

- [ ] **Step 1: Add the column**

In `backend/models/post.py`, add `word_count` after the `content_hash` column:

```python
# before:
content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
rendered_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)

# after:
content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
rendered_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
```

`Integer` is already imported at the top of the file.

- [ ] **Step 2: Run static checks**

```bash
just check-static
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/models/post.py
git commit -m "feat: add word_count column to PostCache"
```

---

### Task 3: Expose `word_count` in `PostDetail` schema and service

**Files:**
- Modify: `backend/schemas/post.py`
- Modify: `backend/services/post_service.py`

- [ ] **Step 1: Add `word_count` to `PostDetail`**

In `backend/schemas/post.py`, add to `PostDetail`:

```python
class PostDetail(PostSummary):
    """Full post detail with rendered HTML."""

    rendered_html: str
    content: str | None = None
    word_count: int = 0
    warnings: list[str] = Field(default_factory=list)
```

- [ ] **Step 2: Pass `word_count` in `post_service.py`**

In `backend/services/post_service.py`, locate the `PostDetail(...)` constructor call (around line 260) and add `word_count`:

```python
return PostDetail(
    id=post.id,
    file_path=post.file_path,
    title=post.title,
    subtitle=post.subtitle,
    author=display_author,
    created_at=format_iso(post.created_at),
    modified_at=format_iso(post.modified_at),
    is_draft=post.is_draft,
    rendered_excerpt=post.rendered_excerpt,
    labels=post_label_ids,
    rendered_html=post.rendered_html or "",
    content=None,  # Raw content not included in public view; use the /edit endpoint
    word_count=post.word_count,
)
```

- [ ] **Step 3: Run static checks**

```bash
just check-static
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/schemas/post.py backend/services/post_service.py
git commit -m "feat: expose word_count in PostDetail schema and service"
```

---

### Task 4: Compute `word_count` in the cache builder

**Files:**
- Modify: `backend/services/cache_service.py`

- [ ] **Step 1: Import `count_words`**

At the top of `backend/services/cache_service.py`, add the import alongside the existing `backend.filesystem` import:

```python
from backend.utils.text import count_words
```

- [ ] **Step 2: Use `count_words` when creating `PostCache` rows**

Locate the `PostCache(...)` constructor in `backend/services/cache_service.py` (around line 149) and add `word_count`:

```python
post = PostCache(
    file_path=post_data.file_path,
    title=post_data.title,
    subtitle=post_data.subtitle,
    author=post_data.author,
    created_at=post_data.created_at,
    modified_at=post_data.modified_at,
    is_draft=post_data.is_draft,
    content_hash=content_h,
    word_count=count_words(post_data.content),
    rendered_excerpt=rendered_excerpt,
    rendered_html=rendered_html,
)
```

- [ ] **Step 3: Run static checks**

```bash
just check-static
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/services/cache_service.py
git commit -m "feat: compute and cache word_count during post indexing"
```

---

### Task 5: Backend integration test for `word_count` in API response

**Files:**
- Modify: `tests/test_api/test_api_integration.py`

- [ ] **Step 1: Add assertion to existing post detail test**

Find `test_get_post` in `tests/test_api/test_api_integration.py` (around line 156):

```python
@pytest.mark.asyncio
async def test_get_post(self, client: AsyncClient) -> None:
    resp = await client.get("/api/posts/posts/hello/index.md")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Hello World"
    assert "rendered_html" in data
    assert "word_count" in data
    assert isinstance(data["word_count"], int)
    assert data["word_count"] > 0
```

- [ ] **Step 2: Run the test**

```bash
just test-backend -- tests/test_api/test_api_integration.py::TestPostAPI::test_get_post -v
```

Expected: PASS

- [ ] **Step 3: Run full backend test suite**

```bash
just test-backend
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_api/test_api_integration.py
git commit -m "test: assert word_count present in post detail API response"
```

---

### Task 6: Add `word_count` to the frontend `PostDetail` type

**Files:**
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Extend the interface**

In `frontend/src/api/client.ts`, update `PostDetail`:

```typescript
export interface PostDetail extends PostSummary {
  rendered_html: string
  content: string | null
  word_count: number
}
```

- [ ] **Step 2: Run frontend static checks**

```bash
just check-frontend
```

Expected: TypeScript errors for missing `word_count` in test mock objects — that is expected and will be resolved in Task 8. If there are errors only in test files (not production code), that is fine at this point.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "feat: add word_count field to PostDetail TypeScript interface"
```

---

### Task 7: `readingTime` frontend utility + tests

**Files:**
- Create: `frontend/src/utils/readingTime.ts`
- Create: `frontend/src/utils/__tests__/readingTime.test.ts`

- [ ] **Step 1: Write the failing tests**

```typescript
// frontend/src/utils/__tests__/readingTime.test.ts
import { describe, expect, it } from 'vitest'
import { readingTime } from '../readingTime'

describe('readingTime', () => {
  it('returns 1 min read for zero words', () => {
    expect(readingTime(0)).toBe(`1 min read · ${(0).toLocaleString()} words`)
  })

  it('returns 1 min read for a short post (under 200 words)', () => {
    expect(readingTime(150)).toBe(`1 min read · ${(150).toLocaleString()} words`)
  })

  it('returns 1 min read for exactly 200 words', () => {
    expect(readingTime(200)).toBe(`1 min read · ${(200).toLocaleString()} words`)
  })

  it('returns 2 min read for 201 words', () => {
    expect(readingTime(201)).toBe(`2 min read · ${(201).toLocaleString()} words`)
  })

  it('returns 5 min read for a 1000-word post', () => {
    expect(readingTime(1000)).toBe(`5 min read · ${(1000).toLocaleString()} words`)
  })

  it('uses locale-formatted word count', () => {
    const result = readingTime(12345)
    expect(result).toContain((12345).toLocaleString())
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
just test-frontend -- src/utils/__tests__/readingTime.test.ts
```

Expected: `Cannot find module '../readingTime'`

- [ ] **Step 3: Implement `readingTime`**

```typescript
// frontend/src/utils/readingTime.ts
export function readingTime(wordCount: number): string {
  const minutes = Math.max(1, Math.ceil(wordCount / 200))
  return `${minutes} min read · ${wordCount.toLocaleString()} words`
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
just test-frontend -- src/utils/__tests__/readingTime.test.ts
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/readingTime.ts frontend/src/utils/__tests__/readingTime.test.ts
git commit -m "feat: add readingTime utility with unit tests"
```

---

### Task 8: Display reading time in `PostPage` + update tests

**Files:**
- Modify: `frontend/src/pages/PostPage.tsx`
- Modify: `frontend/src/pages/__tests__/PostPage.test.tsx`

- [ ] **Step 1: Update the test mock to include `word_count` and assert display**

In `frontend/src/pages/__tests__/PostPage.test.tsx`:

1. Add `word_count` to both `postDetail` and `draftPost` mock objects:

```typescript
const postDetail: PostDetail = {
  id: 1,
  file_path: 'posts/hello/index.md',
  title: 'Hello World',
  subtitle: null,
  author: 'Admin',
  created_at: '2026-02-01 12:00:00+00:00',
  modified_at: '2026-02-01 12:00:00+00:00',
  is_draft: false,
  rendered_excerpt: '<p>First post</p>',
  labels: [],
  rendered_html: '<p>Content here</p>',
  content: 'Content here',
  word_count: 400,
}

const draftPost: PostDetail = {
  id: 2,
  file_path: 'posts/2026-03-08-draft/index.md',
  title: 'My Draft',
  subtitle: null,
  author: 'Admin',
  created_at: '2026-03-08 10:00:00+00:00',
  modified_at: '2026-03-08 10:00:00+00:00',
  is_draft: true,
  rendered_excerpt: '<p>Draft excerpt</p>',
  labels: ['tech'],
  rendered_html: '<p>Draft content</p>',
  content: null,
  word_count: 250,
}
```

2. Add a test asserting the reading time is rendered:

```typescript
it('renders reading time when word_count is non-zero', async () => {
  mockFetchPost.mockResolvedValue(postDetail)
  mockFetchViewCount.mockResolvedValue({ views: 42 })
  renderPostPage()
  await waitFor(() => {
    expect(screen.getByText(/min read/)).toBeInTheDocument()
  })
  expect(screen.getByText(/400/)).toBeInTheDocument()
})
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
just test-frontend -- src/pages/__tests__/PostPage.test.tsx
```

Expected: TypeScript errors (missing `word_count` on mocks) and/or test assertion failure for "min read" not found.

- [ ] **Step 3: Update `PostPage.tsx`**

Add `Clock` to the lucide-react import and `readingTime` utility import:

```typescript
import { Calendar, Clock, User, PenLine, Trash2, Eye } from 'lucide-react'
import { readingTime } from '@/utils/readingTime'
```

Insert the reading time item into the metadata row, after the author block and before the view count block (around line 198 in the current file):

```tsx
{post.word_count > 0 && (
  <div className="flex items-center gap-1.5">
    <Clock size={14} aria-hidden="true" />
    <span>{readingTime(post.word_count)}</span>
  </div>
)}
```

The full metadata row should now read: Calendar → Author → **Reading time** → Views → Labels → Share.

- [ ] **Step 4: Run tests to verify they pass**

```bash
just test-frontend -- src/pages/__tests__/PostPage.test.tsx
```

Expected: all tests PASS

- [ ] **Step 5: Run full frontend checks**

```bash
just check-frontend
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/PostPage.tsx frontend/src/pages/__tests__/PostPage.test.tsx
git commit -m "feat: display reading time and word count on post page"
```

---

### Task 9: Final verification

- [ ] **Step 1: Run the full test and static check gate**

```bash
just check
```

Expected: all static checks and tests PASS

- [ ] **Step 2: Start dev server and verify in browser**

```bash
just start
```

Open a post at `http://localhost:5173/post/<slug>` and confirm:
- The metadata row shows e.g. "2 min read · 350 words" with a clock icon
- The word count uses the browser's locale separator
- The item does not appear on the timeline or search results pages

```bash
just stop
```

- [ ] **Step 3: Final commit (if any stray changes)**

If `just check` produced auto-fixes, commit them:

```bash
git add -p
git commit -m "chore: apply formatter fixes after word count feature"
```
