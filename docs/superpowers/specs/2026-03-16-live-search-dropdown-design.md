# Live Search Dropdown

## Problem

The current search requires users to type a query and press Enter with no visual indication that Enter is needed. The inline search input visually implies live/as-you-type behavior, but nothing happens until the user submits the form. This makes search unintuitive for new users.

## Solution

Add a live search dropdown to the header search input that shows results as the user types, while preserving the full search results page as the primary destination.

## Interaction Model

- Typing in the header search input triggers live search after a **300ms debounce** and a **minimum of 2 characters**.
- Results appear in a compact dropdown directly below the input: **title + date, up to 5 results**, with match highlighting in titles.
- Dropdown includes a **"View all results" footer** — clickable for mouse users, or press Enter when no result is arrow-key-highlighted.
- **No result is highlighted by default.** Arrow keys begin highlighting from the first result. This means Enter consistently navigates to the full search page unless the user explicitly arrow-keys to a specific result.
- **Enter** with no highlight → navigates to `/search?q=...` (full results page).
- **Enter** with a highlighted result → navigates to that post.
- **Arrow keys** (↑↓) navigate the dropdown results.
- **ESC** closes the dropdown.
- Clicking a result navigates to that post.
- Clicking outside the dropdown closes it.

## Backend

No backend changes. The existing `GET /api/posts/search?q=...&limit=...` endpoint is reused. The dropdown calls it with `limit=5`; the full search page continues using `limit=20`.

## Performance

- **300ms debounce** on input changes — cancels in-flight requests when the user keeps typing (AbortController).
- Minimum 2 characters before the first query fires.
- No loading spinner in the dropdown — FTS5 responses are sub-millisecond, results appear instantly.
- Only the latest query's response is rendered; stale responses from cancelled requests are discarded.

## Component Structure

- The search input stays in `Header.tsx` with local state for: query text, dropdown results, highlighted index, and open/closed.
- New component: `SearchDropdown.tsx` — renders the results list and footer, receives results and highlight index as props.
- The dropdown is positioned absolutely below the search input.
- No new stores or global state — entirely local to the header search interaction.
- `SearchPage.tsx` and `searchPosts()` API function are unchanged.

## Edge Cases

- **Empty results**: dropdown shows "No results found" with no footer link.
- **Query cleared / input emptied**: dropdown closes immediately.
- **API error**: dropdown closes silently — user can press Enter to go to the full search page which has its own error handling.
- **Fast typing**: debounce + AbortController prevents race conditions with stale results.

## Accessibility

- Dropdown uses `role="listbox"`, results use `role="option"` with `aria-selected` for the highlighted item.
- `aria-activedescendant` on the input tracks the current keyboard highlight.
- Click-outside closes the dropdown (existing behavior extended).
