# Codebase Simplification Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate blocking sync git operations, deduplicate share components, split the AdminPage monolith, and add type safety to CrossPost status strings.

**Architecture:** Four independent refactors: (1) GitService methods become async via `asyncio.to_thread`, (2) shared `useShareHandlers` hook replaces duplicated logic in ShareBar/ShareButton, (3) AdminPage sections extracted into dedicated components, (4) `CrossPostStatus` StrEnum/union replaces bare strings.

**Tech Stack:** Python asyncio, React hooks, TypeScript unions, Pydantic StrEnum

---

### Task 1: Make GitService async

**Files:**
- Modify: `backend/services/git_service.py`

**Step 1: Add `asyncio` import and convert `_run` to async**

Change `_run` from sync to async by wrapping `subprocess.run` in `asyncio.to_thread`:

```python
import asyncio

# ... existing imports ...

class GitService:
    # ...

    async def _run(
        self,
        *args: str,
        check: bool = True,
        capture_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run a git command in the content directory."""
        return await asyncio.to_thread(
            subprocess.run,
            ["git", *args],
            cwd=self.content_dir,
            check=check,
            capture_output=capture_output,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
```

**Step 2: Convert all methods that call `_run` to async**

Every method that calls `self._run(...)` must become `async def` and `await self._run(...)`:

- `init_repo` → `async def init_repo`
- `commit_all` → `async def commit_all` (also `await self.head_commit()` inside)
- `try_commit` → `async def try_commit` (also `await self.commit_all(...)` inside)
- `head_commit` → `async def head_commit`
- `commit_exists` → `async def commit_exists`
- `show_file_at_commit` → `async def show_file_at_commit`

**Step 3: Convert `merge_file_content` to async**

Wrap the entire method body (temp file creation + subprocess) in `to_thread` since it also does sync file I/O:

```python
async def merge_file_content(self, base: str, ours: str, theirs: str) -> tuple[str, bool]:
    """Three-way merge of text content using git merge-file."""
    return await asyncio.to_thread(self._merge_file_content_sync, base, ours, theirs)

def _merge_file_content_sync(self, base: str, ours: str, theirs: str) -> tuple[str, bool]:
    """Sync implementation of merge_file_content for use with to_thread."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        base_f = tmp / "base"
        ours_f = tmp / "ours"
        theirs_f = tmp / "theirs"
        base_f.write_text(base, encoding="utf-8")
        ours_f.write_text(ours, encoding="utf-8")
        theirs_f.write_text(theirs, encoding="utf-8")

        result = subprocess.run(
            ["git", "merge-file", "-p", str(ours_f), str(base_f), str(theirs_f)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=GIT_TIMEOUT_SECONDS,
        )
        if result.returncode < 0 or result.returncode >= 128:
            raise subprocess.CalledProcessError(
                result.returncode, "git merge-file", result.stdout, result.stderr
            )
        return result.stdout, result.returncode > 0
```

**Step 4: Run backend tests to verify**

Run: `just test-backend`
Expected: Tests will fail because call sites and test fixtures don't await yet. That's expected — we fix those in tasks 2-3.

**Step 5: Commit**

```
git commit -m "refactor: make GitService methods async via asyncio.to_thread"
```

---

### Task 2: Update all GitService call sites to await

**Files:**
- Modify: `backend/main.py:188` — `await git_service.init_repo()`
- Modify: `backend/api/posts.py:341,411,510,688,732` — `await git_service.try_commit(...)`
- Modify: `backend/api/labels.py:78` — `await git_service.try_commit(...)`
- Modify: `backend/api/admin.py:89,123,147,170,194` — `await git_service.try_commit(...)`
- Modify: `backend/api/sync.py:150,285,288,352,401` — `await` on head_commit, commit_all, etc.
- Modify: `backend/services/sync_service.py:347-416` — `merge_post_file` and `merge_file_content`
- Modify: `backend/api/sync.py:407-430` — `_get_base_content` helper

**Step 1: Update `backend/main.py`**

Line 188: change `git_service.init_repo()` to `await git_service.init_repo()`.

**Step 2: Update `backend/api/posts.py`**

Add `await` before every `git_service.try_commit(...)` call (5 occurrences at lines 341, 411, 510, 688, 732).

**Step 3: Update `backend/api/labels.py`**

Line 78: `await git_service.try_commit(commit_message)`.

**Step 4: Update `backend/api/admin.py`**

Add `await` before every `git_service.try_commit(...)` call (5 occurrences at lines 89, 123, 147, 170, 194).

**Step 5: Update `backend/api/sync.py`**

- Line 150 (sync_status): `server_commit=await git_service.head_commit()`
- Line 352: `await git_service.commit_all(...)`
- Line 401: `commit_hash=None if git_failed else await git_service.head_commit()`
- Lines 407-430: Convert `_get_base_content` to `async def _get_base_content(...)` and `await` its git calls. Update call site at line 285 to `await _get_base_content(...)`.

**Step 6: Update `backend/services/sync_service.py`**

Convert `merge_post_file` to `async def merge_post_file(...)`:
- Line 402: `await git_service.merge_file_content(...)`
- Update call site in `backend/api/sync.py:287` to `await merge_post_file(...)`.

**Step 7: Run backend tests**

Run: `just test-backend`
Expected: Most tests pass. Test fixtures may need async conversion (Task 3).

**Step 8: Commit**

```
git commit -m "refactor: await async GitService at all call sites"
```

---

### Task 3: Update test fixtures for async GitService

**Files:**
- Modify: `tests/conftest.py:194-196,305-309` — fixtures calling `init_repo()`
- Modify: `tests/test_services/test_git_service.py` — all test methods
- Modify: `tests/test_services/test_git_merge_file.py` — all test methods
- Modify: `tests/test_services/test_hybrid_merge.py` — `merge_post_file` calls
- Modify: `tests/test_services/test_ensure_content_dir.py:109-113` — git_service assertions

**Step 1: Update `tests/conftest.py` fixtures**

Line 194-196 (`create_test_client`): already in async context, just add `await`:
```python
git_service = GitService(content_dir=settings.content_dir)
await git_service.init_repo()
app.state.git_service = git_service
```

Line 305-309 (`git_service` fixture): convert to async fixture:
```python
@pytest.fixture
async def git_service(tmp_content_dir: Path) -> GitService:
    """Create a git service for the temporary content directory."""
    gs = GitService(tmp_content_dir)
    await gs.init_repo()
    return gs
```

**Step 2: Update `test_git_service.py`**

Convert all test methods to `async def` and add `await` before every GitService method call. Example:

```python
class TestGitServiceInit:
    async def test_init_creates_repo(self, tmp_path: Path) -> None:
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        await gs.init_repo()
        assert (tmp_path / ".git").is_dir()
```

The `subprocess.run` patch test at lines 169-174 needs updating — patch `asyncio.to_thread` or use `wraps` on `subprocess.run` (it's still called under the hood, so the existing patch should still work).

**Step 3: Update `test_git_merge_file.py`**

Convert all test methods to `async def` and add `await` before `git.init_repo()` and `git.merge_file_content(...)`.

**Step 4: Update `test_hybrid_merge.py`**

Convert tests calling `merge_post_file(...)` to `async def` and add `await`.

**Step 5: Update `test_ensure_content_dir.py`**

Lines 109-113: add `await` before `git_service.head_commit()` and `git_service.show_file_at_commit(...)`.

**Step 6: Run full backend tests**

Run: `just test-backend`
Expected: All tests pass.

**Step 7: Commit**

```
git commit -m "test: update git service tests for async methods"
```

---

### Task 4: Extract `useShareHandlers` hook

**Files:**
- Create: `frontend/src/components/share/useShareHandlers.ts`
- Modify: `frontend/src/components/share/ShareBar.tsx`
- Modify: `frontend/src/components/share/ShareButton.tsx`

**Step 1: Create `useShareHandlers.ts`**

```typescript
import { useState } from 'react'

import {
  copyToClipboard,
  getValidMastodonInstance,
  getShareText,
  getShareUrl,
  nativeShare,
} from './shareUtils'

interface ShareHandlers {
  shareText: string
  copied: boolean
  copyFailed: boolean
  showMastodonPrompt: boolean
  setShowMastodonPrompt: (show: boolean) => void
  handlePlatformClick: (platformId: string) => void
  handleEmailClick: () => void
  handleCopy: () => Promise<void>
  handleNativeShare: () => Promise<void>
}

export function useShareHandlers(
  title: string,
  author: string | null,
  url: string,
  onAction?: () => void,
): ShareHandlers {
  const [showMastodonPrompt, setShowMastodonPrompt] = useState(false)
  const [copied, setCopied] = useState(false)
  const [copyFailed, setCopyFailed] = useState(false)

  const shareText = getShareText(title, author, url)

  function handlePlatformClick(platformId: string) {
    if (platformId === 'mastodon') {
      const instance = getValidMastodonInstance()
      if (instance !== null) {
        const shareUrl = getShareUrl('mastodon', shareText, url, title, instance)
        window.open(shareUrl, '_blank', 'noopener,noreferrer')
        onAction?.()
      } else {
        setShowMastodonPrompt(true)
      }
      return
    }
    const shareUrl = getShareUrl(platformId, shareText, url, title)
    if (shareUrl !== '') {
      window.open(shareUrl, '_blank', 'noopener,noreferrer')
      onAction?.()
    }
  }

  function handleEmailClick() {
    const emailUrl = getShareUrl('email', shareText, url, title)
    window.open(emailUrl, '_self')
    onAction?.()
  }

  async function handleCopy() {
    const success = await copyToClipboard(url)
    if (success) {
      setCopied(true)
      setTimeout(() => {
        setCopied(false)
        onAction?.()
      }, 2000)
    } else {
      setCopyFailed(true)
      setTimeout(() => {
        setCopyFailed(false)
      }, 2000)
    }
  }

  async function handleNativeShare() {
    try {
      await nativeShare(title, shareText, url)
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        return
      }
      throw err
    }
  }

  return {
    shareText,
    copied,
    copyFailed,
    showMastodonPrompt,
    setShowMastodonPrompt,
    handlePlatformClick,
    handleEmailClick,
    handleCopy,
    handleNativeShare,
  }
}
```

**Step 2: Simplify `ShareBar.tsx`**

Replace all state and handler logic with the hook. The component becomes a thin layout wrapper:

```typescript
import { Check, Link, Mail, Share2, X as XIcon } from 'lucide-react'

import PlatformIcon from '@/components/crosspost/PlatformIcon'

import MastodonSharePrompt from './MastodonSharePrompt'
import { canNativeShare, SHARE_PLATFORMS } from './shareUtils'
import { useShareHandlers } from './useShareHandlers'

interface ShareBarProps {
  title: string
  author: string | null
  url: string
}

export default function ShareBar({ title, author, url }: ShareBarProps) {
  const {
    shareText,
    copied,
    copyFailed,
    showMastodonPrompt,
    setShowMastodonPrompt,
    handlePlatformClick,
    handleEmailClick,
    handleCopy,
    handleNativeShare,
  } = useShareHandlers(title, author, url)

  return (
    // ... existing JSX unchanged ...
  )
}
```

Remove the old `useState` imports for `copied`/`copyFailed`/`showMastodonPrompt`, the `getShareText` usage, and all handler function definitions. Keep all JSX rendering exactly as-is.

**Step 3: Simplify `ShareButton.tsx`**

Replace handler logic with the hook, passing `() => setShowDropdown(false)` as `onAction`:

```typescript
const {
  shareText,
  copied,
  copyFailed,
  showMastodonPrompt,
  setShowMastodonPrompt,
  handlePlatformClick,
  handleEmailClick,
  handleCopy,
  handleNativeShare,
} = useShareHandlers(title, author, url, () => setShowDropdown(false))
```

The `handleClick` function stays in ShareButton (it's unique — manages native share fallback to dropdown). But it now calls `handleNativeShare()` from the hook, catching non-abort errors to set dropdown visible:

```typescript
async function handleClick() {
  if (canNativeShare()) {
    try {
      await handleNativeShare()
    } catch {
      setShowDropdown(true)
    }
  } else {
    setShowDropdown((prev) => !prev)
  }
}
```

Remove: duplicate state declarations, duplicate handler functions, duplicate imports of shareUtils functions.
Keep: `showDropdown` state, `dropdownRef`, click-outside effect, `handleClick`, all JSX.

**Step 4: Run frontend tests**

Run: `just test-frontend`
Expected: Existing ShareBar and ShareButton tests pass (they test rendered behavior, not internals).

**Step 5: Commit**

```
git commit -m "refactor: extract useShareHandlers hook from ShareBar/ShareButton"
```

---

### Task 5: Extract AdminPage sections

**Files:**
- Create: `frontend/src/components/admin/SiteSettingsSection.tsx`
- Create: `frontend/src/components/admin/PagesSection.tsx`
- Create: `frontend/src/components/admin/PasswordSection.tsx`
- Modify: `frontend/src/pages/AdminPage.tsx`

**Step 1: Create `SiteSettingsSection.tsx`**

Extract lines 88-200 (state) and 473-590 (JSX) from AdminPage. Props interface:

```typescript
import { useState } from 'react'
import { Settings, Save } from 'lucide-react'

import { HTTPError } from '@/api/client'
import type { AdminSiteSettings } from '@/api/client'
import { updateAdminSiteSettings } from '@/api/admin'
import { useSiteStore } from '@/stores/siteStore'

interface SiteSettingsSectionProps {
  initialSettings: AdminSiteSettings
  busy: boolean
  onSaving: (saving: boolean) => void
}
```

Move `siteSettings`, `siteError`, `siteSuccess`, `savingSite` state and `handleSaveSiteSettings` into this component. Call `onSaving(true/false)` in the handler to propagate busy state up.

**Step 2: Create `PagesSection.tsx`**

Extract lines 99-121 (pages state), 202-382 (handlers), and 592-875 (JSX). Also move the `PagePreview` component (lines 39-77) into this file. Props:

```typescript
interface PagesSectionProps {
  initialPages: AdminPageConfig[]
  busy: boolean
  onSaving: (saving: boolean) => void
}
```

Move all page-related state (`pages`, `pagesError`, `pagesSuccess`, `savingOrder`, `orderDirty`, `showAddForm`, `newPageId`, `newPageTitle`, `creatingPage`, `expandedPageId`, `editTitle`, `editContent`, `savingPage`, `deletingPage`, `deleteConfirmId`, `pageEditError`, `pageEditSuccess`) and all page handlers into this component.

The `onSaving` callback should reflect the OR of `savingOrder || creatingPage || savingPage || deletingPage`.

**Step 3: Create `PasswordSection.tsx`**

Extract lines 122-128 (state), 384-431 (handler), and 878-990 (JSX). Props:

```typescript
interface PasswordSectionProps {
  busy: boolean
  onSaving: (saving: boolean) => void
}
```

Move password state and handler into this component.

**Step 4: Update `AdminPage.tsx`**

Replace the extracted sections with the new components. AdminPage becomes a layout shell:

```typescript
import { useEffect, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Settings, ArrowLeft } from 'lucide-react'

import { useAuthStore } from '@/stores/authStore'
import LoadingSpinner from '@/components/LoadingSpinner'
import { HTTPError } from '@/api/client'
import type { AdminSiteSettings, AdminPageConfig } from '@/api/client'
import { fetchAdminSiteSettings, fetchAdminPages } from '@/api/admin'
import SiteSettingsSection from '@/components/admin/SiteSettingsSection'
import PagesSection from '@/components/admin/PagesSection'
import PasswordSection from '@/components/admin/PasswordSection'
import SocialAccountsPanel from '@/components/crosspost/SocialAccountsPanel'

export default function AdminPage() {
  // Auth, loading, data fetch (same as before)
  // busy = siteSaving || pagesSaving || passwordSaving || socialBusy
  // Render guards (same as before)
  // Return layout with <SiteSettingsSection>, <PagesSection>, <PasswordSection>, <SocialAccountsPanel>
}
```

The BUILTIN_PAGE_IDS constant moves into PagesSection.

**Step 5: Run frontend tests**

Run: `just test-frontend`
Expected: All tests pass.

**Step 6: Commit**

```
git commit -m "refactor: extract AdminPage into section components"
```

---

### Task 6: Add CrossPostStatus enum

**Files:**
- Modify: `backend/schemas/crosspost.py`
- Modify: `backend/models/crosspost.py`
- Modify: `backend/services/crosspost_service.py`
- Modify: `backend/api/crosspost.py`
- Modify: `frontend/src/api/crosspost.ts`
- Modify: `frontend/src/components/crosspost/CrossPostDialog.tsx`
- Modify: `frontend/src/components/crosspost/CrossPostHistory.tsx`

**Step 1: Add `CrossPostStatus` StrEnum to backend schemas**

In `backend/schemas/crosspost.py`, add:

```python
from enum import StrEnum

class CrossPostStatus(StrEnum):
    PENDING = "pending"
    POSTED = "posted"
    FAILED = "failed"
```

Update `CrossPostResponse.status` field type from `str` to `CrossPostStatus`.

**Step 2: Update backend model default**

In `backend/models/crosspost.py` line 48, change:
```python
status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
```
to:
```python
status: Mapped[str] = mapped_column(String, nullable=False, default=CrossPostStatus.PENDING)
```

Add import: `from backend.schemas.crosspost import CrossPostStatus`

**Step 3: Update `backend/services/crosspost_service.py`**

Add import: `from backend.schemas.crosspost import CrossPostStatus`

Replace all string literals:
- `status="failed"` → `status=CrossPostStatus.FAILED` (lines 181, 222)
- `status="posted" if ... else "failed"` → `status=CrossPostStatus.POSTED if ... else CrossPostStatus.FAILED` (line 262)

**Step 4: Update `backend/api/crosspost.py`**

Add import: `from backend.schemas.crosspost import CrossPostStatus`

Line 192: `status="posted" if r.success else "failed"` → `status=CrossPostStatus.POSTED if r.success else CrossPostStatus.FAILED`

**Step 5: Add TypeScript union to frontend**

In `frontend/src/api/crosspost.ts`, add:

```typescript
export type CrossPostStatus = 'pending' | 'posted' | 'failed'
```

Update `CrossPostResult.status` from `string` to `CrossPostStatus`.

**Step 6: Update frontend components**

In `CrossPostDialog.tsx` and `CrossPostHistory.tsx`, update the import to include `CrossPostStatus` type if needed for type-checking. The existing `=== 'posted'` and `=== 'failed'` comparisons remain valid since the union narrows the type — no code changes needed in the comparison logic itself, just the import of the updated `CrossPostResult` type.

**Step 7: Run all tests**

Run: `just test`
Expected: All backend + frontend tests pass.

**Step 8: Commit**

```
git commit -m "refactor: add CrossPostStatus enum for type-safe status strings"
```

---

### Task 7: Run full check and verify

**Step 1: Run the full gate**

Run: `just check`
Expected: All static checks + all tests pass.

**Step 2: Fix any issues**

If ruff format fails, run `uv run ruff format` on affected files.
If type checks fail, fix type annotations.
If eslint/knip/dependency-cruiser fail, fix the reported issues.

**Step 3: Commit fixes if any**

```
git commit -m "fix: address lint and type issues from simplification refactor"
```
