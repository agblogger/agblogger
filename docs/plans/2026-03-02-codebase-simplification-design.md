# Codebase Simplification — Design

## 1. Async GitService

Convert `GitService._run()` and `merge_file_content()` from blocking `subprocess.run` to `asyncio.to_thread(subprocess.run, ...)`. All public methods become `async def`, callers add `await`.

- `_run()` → `async _run()` wrapping `subprocess.run` in `to_thread`
- `merge_file_content()` → `async merge_file_content()` wrapping its `subprocess.run` in `to_thread`
- `init_repo`, `commit_all`, `try_commit`, `head_commit`, `commit_exists`, `show_file_at_commit` all become `async`
- ~18 call sites in `main.py`, `api/sync.py`, `api/posts.py`, `api/labels.py`, `api/admin.py`, `services/sync_service.py` add `await`

## 2. Share Handlers Hook

Extract duplicated state + handlers from `ShareBar` and `ShareButton` into `useShareHandlers()`.

Hook signature:
```typescript
function useShareHandlers(title: string, author: string, url: string, onAction?: () => void) {
  // State: copied, copyFailed, showMastodonPrompt, setShowMastodonPrompt
  // Handlers: handlePlatformClick, handleEmailClick, handleCopy, handleNativeShare
  // Derived: shareText
}
```

`onAction` callback lets `ShareButton` close its dropdown after any action. Both components become thin layout wrappers (~40-60 lines each) that call the hook and render their respective UIs.

New file: `frontend/src/components/share/useShareHandlers.ts`

## 3. AdminPage Section Extraction

Split the 996-line `AdminPage` into section components:

- `frontend/src/components/admin/SiteSettingsSection.tsx` — title/description/author/timezone form (~120 lines)
- `frontend/src/components/admin/PagesSection.tsx` — page CRUD, reordering, preview (~550 lines including PagePreview)
- `frontend/src/components/admin/PasswordSection.tsx` — change password form (~120 lines)

`AdminPage.tsx` becomes a layout shell (~150 lines) that fetches data, manages top-level loading/error state, and renders the sections. Each section receives its data and callbacks via props. The `busy` flag aggregation stays in AdminPage.

## 4. CrossPost Status Enum

Backend — new `CrossPostStatus(StrEnum)` in `backend/schemas/crosspost.py`:
```python
class CrossPostStatus(StrEnum):
    PENDING = "pending"
    POSTED = "posted"
    FAILED = "failed"
```

Used in: `CrossPostResponse.status`, `CrossPost` model default, all status assignments in `crosspost_service.py` and `api/crosspost.py`.

Frontend — string union in `frontend/src/api/crosspost.ts`:
```typescript
export type CrossPostStatus = 'pending' | 'posted' | 'failed'
```

Used in: `CrossPostResult.status`, all `=== 'posted'` / `=== 'failed'` comparisons in `CrossPostDialog` and `CrossPostHistory`.
