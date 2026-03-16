# Live Search Dropdown Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live search dropdown to the header search input that shows results as the user types, replacing the current enter-to-search-only model.

**Architecture:** The header search input gains debounced live search that fetches results via the existing search API (`limit=5`) and renders them in a new `SearchDropdown` component. All state is local to the header. The existing `/search` page is unchanged.

**Tech Stack:** React, TypeScript, Tailwind CSS, ky (HTTP client), Vitest + Testing Library

**Spec:** `docs/specs/2026-03-16-live-search-dropdown-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `frontend/src/api/posts.ts:43-47` | Add optional `AbortSignal` param to `searchPosts()` |
| Create | `frontend/src/components/search/SearchDropdown.tsx` | Dropdown UI: result list, footer, empty state |
| Create | `frontend/src/components/search/highlightMatch.ts` | Pure function: highlight query terms in title text |
| Create | `frontend/src/components/search/__tests__/SearchDropdown.test.tsx` | Tests for dropdown rendering and interactions |
| Create | `frontend/src/components/search/__tests__/highlightMatch.test.ts` | Tests for highlight logic |
| Modify | `frontend/src/components/layout/Header.tsx` | Integrate live search: debounce, state, keyboard nav, dropdown |
| Modify | `frontend/src/components/layout/__tests__/Header.test.tsx` | Tests for live search integration in header |

---

## Chunk 1: API Signal Support + Highlight Utility

### Task 1: Add AbortSignal support to `searchPosts()`

**Files:**
- Modify: `frontend/src/api/posts.ts:43-47`

- [ ] **Step 1: Add signal parameter**

This adds an optional third parameter — no existing callers break. The signal forwarding is tested in Task 4's Header integration tests (`expect(mockSearchPosts).toHaveBeenCalledWith('he', 5, expect.any(AbortSignal))`). Since no dedicated test file exists for API wrappers and this is a backward-compatible additive change, the TDD cycle for this specific change runs in Task 4.



In `frontend/src/api/posts.ts`, change `searchPosts`:

```typescript
export async function searchPosts(
  query: string,
  limit = 20,
  signal?: AbortSignal,
): Promise<SearchResult[]> {
  return api
    .get('posts/search', { searchParams: { q: query, limit: String(limit) }, signal })
    .json<SearchResult[]>()
}
```

- [ ] **Step 2: Verify existing SearchPage tests still pass**

Run: `just test-frontend`
Expected: All existing tests pass (SearchPage calls `searchPosts` with 2 args, new third arg is optional).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/posts.ts
git commit -m "feat: add AbortSignal support to searchPosts()"
```

---

### Task 2: Create `highlightMatch` utility

**Files:**
- Create: `frontend/src/components/search/highlightMatch.ts`
- Create: `frontend/src/components/search/__tests__/highlightMatch.test.ts`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/components/search/__tests__/highlightMatch.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { highlightMatch } from '../highlightMatch'

describe('highlightMatch', () => {
  it('wraps matching substring in mark tags', () => {
    expect(highlightMatch('Database Migration Guide', 'migrat')).toBe(
      'Database <mark>Migrat</mark>ion Guide',
    )
  })

  it('highlights multiple terms', () => {
    expect(highlightMatch('Running Migrations in Production', 'running prod')).toBe(
      '<mark>Running</mark> Migrations in <mark>Prod</mark>uction',
    )
  })

  it('is case-insensitive', () => {
    expect(highlightMatch('Hello World', 'hello')).toBe('<mark>Hello</mark> World')
  })

  it('returns original text when no match', () => {
    expect(highlightMatch('Hello World', 'xyz')).toBe('Hello World')
  })

  it('returns original text for empty query', () => {
    expect(highlightMatch('Hello World', '')).toBe('Hello World')
    expect(highlightMatch('Hello World', '   ')).toBe('Hello World')
  })

  it('escapes HTML in title text', () => {
    expect(highlightMatch('<script>alert(1)</script>', 'script')).toBe(
      '&lt;<mark>script</mark>&gt;alert(1)&lt;/<mark>script</mark>&gt;',
    )
  })

  it('handles overlapping match regions by taking first match', () => {
    // "test" and "testing" both match — the first term's match takes priority
    expect(highlightMatch('testing', 'test testing')).toBe('<mark>testing</mark>')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-frontend`
Expected: FAIL — module `../highlightMatch` not found.

- [ ] **Step 3: Implement `highlightMatch`**

Create `frontend/src/components/search/highlightMatch.ts`:

```typescript
/**
 * Highlight query term matches in a title string.
 * Returns an HTML string with matches wrapped in <mark> tags.
 * The title text is HTML-escaped before processing.
 */
export function highlightMatch(title: string, query: string): string {
  const terms = query.trim().split(/\s+/).filter(Boolean)
  if (terms.length === 0) return escapeHtml(title)

  // Build a single regex matching any term (longest first to prefer longer matches)
  const sorted = [...terms].sort((a, b) => b.length - a.length)
  const pattern = new RegExp(
    `(${sorted.map(escapeRegex).join('|')})`,
    'gi',
  )

  // split() with a capture group returns alternating [non-match, match, non-match, ...]
  // Odd-indexed parts are always matches.
  const parts = title.split(pattern)
  return parts
    .map((part, i) => (i % 2 === 1 ? `<mark>${escapeHtml(part)}</mark>` : escapeHtml(part)))
    .join('')
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-frontend`
Expected: All `highlightMatch` tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/search/highlightMatch.ts frontend/src/components/search/__tests__/highlightMatch.test.ts
git commit -m "feat: add highlightMatch utility for search dropdown"
```

---

## Chunk 2: SearchDropdown Component

### Task 3: Create `SearchDropdown` component

**Files:**
- Create: `frontend/src/components/search/SearchDropdown.tsx`
- Create: `frontend/src/components/search/__tests__/SearchDropdown.test.tsx`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/components/search/__tests__/SearchDropdown.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi } from 'vitest'
import SearchDropdown from '../SearchDropdown'
import type { SearchResult } from '@/api/client'

const results: SearchResult[] = [
  { id: 1, file_path: 'posts/hello.md', title: 'Hello World', rendered_excerpt: null, created_at: '2026-02-01 12:00:00+00:00', rank: 1.0 },
  { id: 2, file_path: 'posts/react.md', title: 'React Guide', rendered_excerpt: null, created_at: '2026-02-02 12:00:00+00:00', rank: 0.9 },
]

function renderDropdown(props: Partial<React.ComponentProps<typeof SearchDropdown>> = {}) {
  const defaults = {
    results,
    query: 'hello',
    highlightIndex: -1,
    onSelect: vi.fn(),
    onFooterClick: vi.fn(),
  }
  return render(
    <MemoryRouter>
      <SearchDropdown {...defaults} {...props} />
    </MemoryRouter>,
  )
}

describe('SearchDropdown', () => {
  it('renders result titles', () => {
    renderDropdown()
    expect(screen.getByText('Hello World')).toBeInTheDocument()
    expect(screen.getByText('React Guide')).toBeInTheDocument()
  })

  it('renders "View all results" footer when results exist', () => {
    renderDropdown()
    expect(screen.getByText('View all results')).toBeInTheDocument()
  })

  it('renders "No results found" with no footer when empty', () => {
    renderDropdown({ results: [] })
    expect(screen.getByText('No results found')).toBeInTheDocument()
    expect(screen.queryByText('View all results')).not.toBeInTheDocument()
  })

  it('highlights the item at highlightIndex', () => {
    renderDropdown({ highlightIndex: 0 })
    const options = screen.getAllByRole('option')
    expect(options[0]).toHaveAttribute('aria-selected', 'true')
    expect(options[1]).toHaveAttribute('aria-selected', 'false')
  })

  it('calls onSelect with file_path on mousedown', async () => {
    const onSelect = vi.fn()
    renderDropdown({ onSelect })
    const option = screen.getAllByRole('option')[0]!
    // Use fireEvent for mousedown (userEvent doesn't have mousedown)
    option.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    expect(onSelect).toHaveBeenCalledWith('posts/hello.md')
  })

  it('calls onFooterClick on footer mousedown', () => {
    const onFooterClick = vi.fn()
    renderDropdown({ onFooterClick })
    const footer = screen.getByText('View all results')
    footer.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    expect(onFooterClick).toHaveBeenCalled()
  })

  it('uses role=listbox with correct ARIA attributes', () => {
    renderDropdown()
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    const options = screen.getAllByRole('option')
    expect(options).toHaveLength(2)
    expect(options[0]).toHaveAttribute('id', 'search-result-0')
    expect(options[1]).toHaveAttribute('id', 'search-result-1')
  })

  it('renders dates for results', () => {
    renderDropdown()
    expect(screen.getByText('Feb 1, 2026')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-frontend`
Expected: FAIL — module `../SearchDropdown` not found.

- [ ] **Step 3: Implement `SearchDropdown`**

Create `frontend/src/components/search/SearchDropdown.tsx`:

```tsx
import type { SearchResult } from '@/api/client'
import { formatRelativeDate } from '@/utils/date'
import { highlightMatch } from './highlightMatch'

interface SearchDropdownProps {
  results: SearchResult[]
  query: string
  highlightIndex: number
  onSelect: (filePath: string) => void
  onFooterClick: () => void
}

export default function SearchDropdown({
  results,
  query,
  highlightIndex,
  onSelect,
  onFooterClick,
}: SearchDropdownProps) {
  if (results.length === 0) {
    return (
      <div
        className="absolute top-full left-0 right-0 mt-1 bg-paper border border-border
                   rounded-lg shadow-lg z-[60] overflow-hidden"
      >
        <div className="px-3 py-2 text-sm text-muted">No results found</div>
      </div>
    )
  }

  return (
    <div
      className="absolute top-full left-0 right-0 mt-1 bg-paper border border-border
                 rounded-lg shadow-lg z-[60] overflow-hidden"
    >
      <ul id="search-results-listbox" role="listbox">
        {results.map((result, i) => (
          <li
            key={result.id}
            id={`search-result-${i}`}
            role="option"
            aria-selected={i === highlightIndex}
            className={`px-3 py-2 cursor-pointer transition-colors ${
              i === highlightIndex ? 'bg-accent/10' : 'hover:bg-paper-warm'
            }`}
            onMouseDown={(e) => {
              e.preventDefault()
              onSelect(result.file_path)
            }}
          >
            <div
              className="text-sm font-medium text-ink truncate"
              dangerouslySetInnerHTML={{ __html: highlightMatch(result.title, query) }}
            />
            <div className="text-xs text-muted mt-0.5">
              {formatRelativeDate(result.created_at)}
            </div>
          </li>
        ))}
      </ul>
      <div
        className="px-3 py-2 text-center border-t border-border cursor-pointer
                   hover:bg-paper-warm transition-colors"
        onMouseDown={(e) => {
          e.preventDefault()
          onFooterClick()
        }}
      >
        <span className="text-xs text-accent">View all results</span>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-frontend`
Expected: All `SearchDropdown` tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/search/SearchDropdown.tsx frontend/src/components/search/__tests__/SearchDropdown.test.tsx
git commit -m "feat: add SearchDropdown component"
```

---

## Chunk 3: Header Integration

### Task 4: Integrate live search into Header

**Files:**
- Modify: `frontend/src/components/layout/Header.tsx`
- Modify: `frontend/src/components/layout/__tests__/Header.test.tsx`

This is the core integration task. The header search form gains:
- Debounced live search on input change (300ms, min 2 chars)
- AbortController to cancel in-flight requests
- Dropdown display with keyboard navigation
- ARIA combobox attributes

- [ ] **Step 1: Write failing tests for live search behavior**

Add the following tests to the existing `Header.test.tsx`. These require mocking the `searchPosts` API:

At the top of `Header.test.tsx`, add the mock (after existing mocks):

```typescript
import type { SearchResult } from '@/api/client'

const mockSearchPosts = vi.fn<(q: string, limit?: number, signal?: AbortSignal) => Promise<SearchResult[]>>()

vi.mock('@/api/posts', () => ({
  searchPosts: (...args: [string, number?, AbortSignal?]) => mockSearchPosts(...args),
}))
```

Add inside the `describe('Header', ...)` block, after the existing `beforeEach` — add `mockSearchPosts.mockReset()` to `beforeEach`.

Then add the new test cases:

```typescript
describe('live search dropdown', () => {
  const results: SearchResult[] = [
    { id: 1, file_path: 'posts/hello.md', title: 'Hello World', rendered_excerpt: null, created_at: '2026-02-01 12:00:00+00:00', rank: 1.0 },
    { id: 2, file_path: 'posts/react.md', title: 'React Guide', rendered_excerpt: null, created_at: '2026-02-02 12:00:00+00:00', rank: 0.9 },
  ]

  it('shows dropdown after typing 2+ chars with debounce', async () => {
    mockSearchPosts.mockResolvedValue(results)
    renderHeader()
    await userEvent.click(screen.getByLabelText('Search'))
    await userEvent.type(screen.getByPlaceholderText('Search posts...'), 'he')

    await waitFor(() => {
      expect(screen.getByRole('listbox')).toBeInTheDocument()
    })
    expect(mockSearchPosts).toHaveBeenCalledWith('he', 5, expect.any(AbortSignal))
  })

  it('does not search with fewer than 2 chars', async () => {
    renderHeader()
    await userEvent.click(screen.getByLabelText('Search'))
    await userEvent.type(screen.getByPlaceholderText('Search posts...'), 'h')

    // Wait a bit to ensure debounce would have fired
    await new Promise((r) => setTimeout(r, 400))
    expect(mockSearchPosts).not.toHaveBeenCalled()
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('navigates to post on result click', async () => {
    mockSearchPosts.mockResolvedValue(results)
    renderHeader()
    await userEvent.click(screen.getByLabelText('Search'))
    await userEvent.type(screen.getByPlaceholderText('Search posts...'), 'hello')

    await waitFor(() => {
      expect(screen.getByRole('listbox')).toBeInTheDocument()
    })

    // mousedown on first result
    const options = screen.getAllByRole('option')
    options[0]!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))

    // Search should close after navigation
    await waitFor(() => {
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    })
  })

  it('Enter with no highlight goes to search page', async () => {
    mockSearchPosts.mockResolvedValue(results)
    renderHeader()
    await userEvent.click(screen.getByLabelText('Search'))
    await userEvent.type(screen.getByPlaceholderText('Search posts...'), 'hello')

    await waitFor(() => {
      expect(screen.getByRole('listbox')).toBeInTheDocument()
    })

    await userEvent.keyboard('{Enter}')
    // Search input should close (navigated to /search page)
    expect(screen.queryByPlaceholderText('Search posts...')).not.toBeInTheDocument()
  })

  it('arrow down highlights first result, enter navigates to it', async () => {
    mockSearchPosts.mockResolvedValue(results)
    renderHeader()
    await userEvent.click(screen.getByLabelText('Search'))
    await userEvent.type(screen.getByPlaceholderText('Search posts...'), 'hello')

    await waitFor(() => {
      expect(screen.getByRole('listbox')).toBeInTheDocument()
    })

    await userEvent.keyboard('{ArrowDown}')
    const options = screen.getAllByRole('option')
    expect(options[0]).toHaveAttribute('aria-selected', 'true')
  })

  it('arrow down past last result wraps to no selection', async () => {
    mockSearchPosts.mockResolvedValue(results)
    renderHeader()
    await userEvent.click(screen.getByLabelText('Search'))
    await userEvent.type(screen.getByPlaceholderText('Search posts...'), 'hello')

    await waitFor(() => {
      expect(screen.getByRole('listbox')).toBeInTheDocument()
    })

    // Down twice to select each, third time wraps to -1
    await userEvent.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}')
    const options = screen.getAllByRole('option')
    options.forEach((opt) => expect(opt).toHaveAttribute('aria-selected', 'false'))
  })

  it('ESC closes dropdown', async () => {
    mockSearchPosts.mockResolvedValue(results)
    renderHeader()
    await userEvent.click(screen.getByLabelText('Search'))
    await userEvent.type(screen.getByPlaceholderText('Search posts...'), 'hello')

    await waitFor(() => {
      expect(screen.getByRole('listbox')).toBeInTheDocument()
    })

    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('clears dropdown when input is cleared', async () => {
    mockSearchPosts.mockResolvedValue(results)
    renderHeader()
    await userEvent.click(screen.getByLabelText('Search'))
    const input = screen.getByPlaceholderText('Search posts...')
    await userEvent.type(input, 'hello')

    await waitFor(() => {
      expect(screen.getByRole('listbox')).toBeInTheDocument()
    })

    await userEvent.clear(input)
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('arrow up from first result wraps to no selection', async () => {
    mockSearchPosts.mockResolvedValue(results)
    renderHeader()
    await userEvent.click(screen.getByLabelText('Search'))
    await userEvent.type(screen.getByPlaceholderText('Search posts...'), 'hello')

    await waitFor(() => {
      expect(screen.getByRole('listbox')).toBeInTheDocument()
    })

    // Down to select first, then Up to deselect
    await userEvent.keyboard('{ArrowDown}{ArrowUp}')
    const options = screen.getAllByRole('option')
    options.forEach((opt) => expect(opt).toHaveAttribute('aria-selected', 'false'))
  })

  it('footer click navigates to search page', async () => {
    mockSearchPosts.mockResolvedValue(results)
    renderHeader()
    await userEvent.click(screen.getByLabelText('Search'))
    await userEvent.type(screen.getByPlaceholderText('Search posts...'), 'hello')

    await waitFor(() => {
      expect(screen.getByRole('listbox')).toBeInTheDocument()
    })

    const footer = screen.getByText('View all results')
    footer.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))

    // Search should close after footer navigation
    await waitFor(() => {
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    })
  })

  it('closes dropdown silently on API error', async () => {
    mockSearchPosts.mockRejectedValue(new Error('fail'))
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    renderHeader()
    await userEvent.click(screen.getByLabelText('Search'))
    await userEvent.type(screen.getByPlaceholderText('Search posts...'), 'hello')

    // Wait for debounce + request
    await new Promise((r) => setTimeout(r, 400))
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    consoleSpy.mockRestore()
  })
})
```

Add `waitFor` to the import from `@testing-library/react` at top of file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-frontend`
Expected: FAIL — new tests fail because Header doesn't have live search yet.

- [ ] **Step 3: Implement live search in Header**

Modify `frontend/src/components/layout/Header.tsx`. Key changes:

1. Add imports:
```typescript
import { useCallback, useEffect, useRef, useState } from 'react'
import { searchPosts } from '@/api/posts'
import type { SearchResult } from '@/api/client'
import SearchDropdown from '@/components/search/SearchDropdown'
```

2. Add state inside `Header()` (alongside existing search state):
```typescript
const [dropdownResults, setDropdownResults] = useState<SearchResult[]>([])
const [dropdownOpen, setDropdownOpen] = useState(false)
const [highlightIndex, setHighlightIndex] = useState(-1)
const abortRef = useRef<AbortController | null>(null)
const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
const searchContainerRef = useRef<HTMLDivElement>(null)
```

3. Add debounced search callback:
```typescript
const doSearch = useCallback((query: string) => {
  // Clear pending debounce
  if (debounceRef.current) clearTimeout(debounceRef.current)
  // Cancel in-flight request
  if (abortRef.current) abortRef.current.abort()

  if (query.trim().length < 2) {
    setDropdownResults([])
    setDropdownOpen(false)
    setHighlightIndex(-1)
    return
  }

  debounceRef.current = setTimeout(() => {
    const controller = new AbortController()
    abortRef.current = controller
    searchPosts(query.trim(), 5, controller.signal)
      .then((results) => {
        if (!controller.signal.aborted) {
          setDropdownResults(results)
          setDropdownOpen(true)
          setHighlightIndex(-1)
        }
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        console.error('Search dropdown error:', err)
        setDropdownOpen(false)
      })
  }, 300)
}, [])
```

4. Update `onChange` handler on search input:
```typescript
onChange={(e) => {
  setSearchQuery(e.target.value)
  doSearch(e.target.value)
}}
```

5. Add keyboard handler on input — replace simple form submit with `onKeyDown`:
```typescript
onKeyDown={(e) => {
  if (e.key === 'Escape') {
    setDropdownOpen(false)
    return
  }
  if (!dropdownOpen || dropdownResults.length === 0) return

  if (e.key === 'ArrowDown') {
    e.preventDefault()
    setHighlightIndex((prev) =>
      prev >= dropdownResults.length - 1 ? -1 : prev + 1
    )
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    setHighlightIndex((prev) =>
      prev <= -1 ? -1 : prev - 1
    )
  } else if (e.key === 'Enter' && highlightIndex >= 0) {
    e.preventDefault()
    const result = dropdownResults[highlightIndex]
    if (result) {
      void navigate(`/post/${result.file_path}`)
      closeSearch()
    }
  }
}}
```

6. Add a `closeSearch` helper (define before `handleSearch`):
```typescript
function closeSearch() {
  setSearchOpen(false)
  setSearchQuery('')
  setDropdownResults([])
  setDropdownOpen(false)
  setHighlightIndex(-1)
  if (debounceRef.current) clearTimeout(debounceRef.current)
  if (abortRef.current) abortRef.current.abort()
}
```

7. Replace the existing `handleSearch` to use `closeSearch`:
```typescript
function handleSearch(e: React.FormEvent) {
  e.preventDefault()
  if (searchQuery.trim()) {
    void navigate(`/search?q=${encodeURIComponent(searchQuery.trim())}`)
    closeSearch()
  }
}
```

Also update the close button `onClick` to call `closeSearch()` instead of separate setters. Update the existing `onBlur` handler on the input to also close the dropdown:
```typescript
onBlur={(e) => {
  if (e.relatedTarget === closeSearchRef.current) return
  if (!searchQuery) {
    closeSearch()
  } else {
    setDropdownOpen(false)
    setHighlightIndex(-1)
  }
}}
```
When the input has a query and loses focus (click outside), the dropdown closes but the search input stays visible. When the query is empty and focus leaves, everything closes.

8. Add ARIA attributes to search input:
```typescript
role="combobox"
aria-expanded={dropdownOpen}
aria-controls="search-results-listbox"
aria-activedescendant={highlightIndex >= 0 ? `search-result-${highlightIndex}` : undefined}
aria-autocomplete="list"
```

9. Wrap the search form in a `relative` positioned container and render `SearchDropdown` below the input:
```tsx
<div ref={searchContainerRef} className="relative">
  <form onSubmit={handleSearch} className="flex items-center gap-1">
    {/* existing input + close button */}
  </form>
  {dropdownOpen && (
    <SearchDropdown
      results={dropdownResults}
      query={searchQuery}
      highlightIndex={highlightIndex}
      onSelect={(filePath) => {
        void navigate(`/post/${filePath}`)
        closeSearch()
      }}
      onFooterClick={() => {
        if (searchQuery.trim()) {
          void navigate(`/search?q=${encodeURIComponent(searchQuery.trim())}`)
        }
        closeSearch()
      }}
    />
  )}
</div>
```

10. Clean up debounce/abort on unmount:
```typescript
useEffect(() => {
  return () => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (abortRef.current) abortRef.current.abort()
  }
}, [])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-frontend`
Expected: All tests pass, including existing Header tests and new live search tests.

- [ ] **Step 5: Run static checks**

Run: `just check-frontend`
Expected: No lint or type errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/layout/Header.tsx frontend/src/components/layout/__tests__/Header.test.tsx
git commit -m "feat: integrate live search dropdown into header"
```

---

## Chunk 4: Manual Verification + Docs

### Task 5: End-to-end browser verification

**Files:** None (manual testing)

- [ ] **Step 1: Start dev server**

Run: `just start`

- [ ] **Step 2: Browser test with Playwright MCP**

Verify using the Playwright MCP tools:
1. Navigate to the app
2. Click search icon — input appears
3. Type 2+ characters — dropdown appears with results
4. Arrow down — first result highlights
5. Arrow down past last — wraps to no selection
6. ESC — dropdown closes
7. Type query, press Enter with no highlight — navigates to `/search?q=...`
8. Type query, arrow to result, press Enter — navigates to post
9. Type query, click a result — navigates to post
10. Click "View all results" footer — navigates to search page

- [ ] **Step 3: Stop dev server and clean up screenshots**

Run: `just stop`
Delete any `*.png` screenshot files created during testing.

- [ ] **Step 4: Commit any adjustments**

If browser testing revealed issues, fix and commit them.

### Task 6: Update architecture docs

**Files:**
- Modify: `docs/arch/frontend.md`

- [ ] **Step 1: Update frontend.md**

Add a brief mention of the live search dropdown to the "Application Shape" or "Code Entry Points" section, noting `frontend/src/components/search/` as the search dropdown components location.

- [ ] **Step 2: Commit**

```bash
git add docs/arch/frontend.md
git commit -m "docs: add search dropdown to frontend architecture docs"
```

### Task 7: Final gate

- [ ] **Step 1: Run full check**

Run: `just check`
Expected: All static checks and tests pass.
