# Content Storage Quota Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional `MAX_CONTENT_SIZE` environment variable that caps the total size of files under `content/`, rejecting uploads that would exceed the limit with a generic 413 response.

**Architecture:** A running byte counter is computed at startup by walking `content/`, stored in app state, and checked/updated in the three existing write paths (post upload, asset upload, sync commit). The counter is maintained incrementally inside the write lock and recomputed after sync cache rebuilds. The deployment script gains a new interactive prompt and CLI argument.

**Tech Stack:** Python, FastAPI, pydantic-settings, pytest

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `backend/config.py` | Modify | Add `max_content_size` setting with human-readable size parsing |
| `backend/services/storage_quota.py` | Create | `ContentSizeTracker` class: compute, check, adjust counter |
| `backend/main.py` | Modify | Initialize tracker at startup after cache rebuild |
| `backend/api/deps.py` | Modify | Add `get_content_size_tracker` dependency |
| `backend/api/posts.py` | Modify | Quota checks in `upload_post`, `upload_assets`, `delete_post_endpoint`, `delete_asset` |
| `backend/api/sync.py` | Modify | Quota check before writes, recompute after cache rebuild |
| `cli/deploy_production.py` | Modify | Add interactive prompt, CLI arg, env var output |
| `.env.example` | Modify | Document `MAX_CONTENT_SIZE` |
| `tests/test_services/test_config.py` | Modify | Tests for size parsing |
| `tests/test_services/test_storage_quota.py` | Create | Unit tests for `ContentSizeTracker` |
| `tests/test_api/test_storage_quota.py` | Create | Integration tests for quota enforcement |
| `tests/test_cli/test_deploy_production.py` | Modify | Tests for new deploy config field |

---

### Task 1: Add `max_content_size` setting to config

**Files:**
- Modify: `backend/config.py:48-167`
- Test: `tests/test_services/test_config.py`

- [ ] **Step 1: Write failing tests for size parsing**

```python
# tests/test_services/test_config.py — add to end of file

class TestMaxContentSize:
    def test_default_is_none(self) -> None:
        s = Settings(_env_file=None)
        assert s.max_content_size is None

    def test_parse_gigabytes(self) -> None:
        s = Settings(_env_file=None, max_content_size="2G")
        assert s.max_content_size == 2 * 1024 * 1024 * 1024

    def test_parse_megabytes(self) -> None:
        s = Settings(_env_file=None, max_content_size="500M")
        assert s.max_content_size == 500 * 1024 * 1024

    def test_parse_plain_bytes(self) -> None:
        s = Settings(_env_file=None, max_content_size="1073741824")
        assert s.max_content_size == 1073741824

    def test_parse_case_insensitive(self) -> None:
        s = Settings(_env_file=None, max_content_size="2g")
        assert s.max_content_size == 2 * 1024 * 1024 * 1024

    def test_parse_zero_rejected(self) -> None:
        with pytest.raises(ValueError):
            Settings(_env_file=None, max_content_size="0")

    def test_parse_negative_rejected(self) -> None:
        with pytest.raises(ValueError):
            Settings(_env_file=None, max_content_size="-1G")

    def test_parse_invalid_suffix_rejected(self) -> None:
        with pytest.raises(ValueError):
            Settings(_env_file=None, max_content_size="2X")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_services/test_config.py::TestMaxContentSize -v`
Expected: FAIL — `max_content_size` field does not exist on Settings

- [ ] **Step 3: Implement size parsing and setting**

Add a validator function and field to `backend/config.py`. Add before the `Settings` class definition:

```python
def parse_human_size(value: str) -> int:
    """Parse a human-readable size string (e.g., '2G', '500M') into bytes."""
    value = value.strip()
    if not value:
        raise ValueError("Empty size string")
    suffixes = {"G": 1024 ** 3, "M": 1024 ** 2, "K": 1024}
    upper = value.upper()
    for suffix, multiplier in suffixes.items():
        if upper.endswith(suffix):
            num_str = value[: -len(suffix)].strip()
            result = int(num_str) * multiplier
            if result <= 0:
                raise ValueError(f"Size must be positive: {value}")
            return result
    result = int(value)
    if result <= 0:
        raise ValueError(f"Size must be positive: {value}")
    return result
```

Add to the `Settings` class, after the `admin_display_name` field (line 100):

```python
    # Storage quota
    max_content_size: int | None = None
```

Add a Pydantic field validator in the `Settings` class:

```python
    @field_validator("max_content_size", mode="before")
    @classmethod
    def _parse_max_content_size(cls, v: str | int | None) -> int | None:
        if v is None or v == "":
            return None
        if isinstance(v, int):
            if v <= 0:
                raise ValueError(f"max_content_size must be positive: {v}")
            return v
        return parse_human_size(v)
```

Add the import for `field_validator` from pydantic at the top of the file:

```python
from pydantic import Field, field_validator
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_services/test_config.py::TestMaxContentSize -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/config.py tests/test_services/test_config.py
git commit -m "feat: add max_content_size setting with human-readable parsing"
```

---

### Task 2: Create `ContentSizeTracker`

**Files:**
- Create: `backend/services/storage_quota.py`
- Test: `tests/test_services/test_storage_quota.py`

- [ ] **Step 1: Write failing tests for ContentSizeTracker**

```python
# tests/test_services/test_storage_quota.py
"""Tests for content storage quota tracking."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.services.storage_quota import ContentSizeTracker


class TestContentSizeTracker:
    def test_compute_from_empty_directory(self, tmp_path: Path) -> None:
        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=None)
        tracker.recompute()
        assert tracker.current_usage == 0

    def test_compute_sums_file_sizes(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_bytes(b"x" * 100)
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.txt").write_bytes(b"y" * 200)
        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=None)
        tracker.recompute()
        assert tracker.current_usage == 300

    def test_check_no_limit_always_passes(self, tmp_path: Path) -> None:
        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=None)
        tracker.recompute()
        # No limit means any size is fine
        assert tracker.check(999_999_999) is True

    def test_check_within_limit_passes(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_bytes(b"x" * 100)
        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=500)
        tracker.recompute()
        assert tracker.check(400) is True

    def test_check_exceeding_limit_fails(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_bytes(b"x" * 100)
        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=500)
        tracker.recompute()
        assert tracker.check(401) is False

    def test_check_at_exact_limit_passes(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_bytes(b"x" * 100)
        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=500)
        tracker.recompute()
        assert tracker.check(400) is True

    def test_adjust_increments(self, tmp_path: Path) -> None:
        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=1000)
        tracker.recompute()
        tracker.adjust(500)
        assert tracker.current_usage == 500

    def test_adjust_decrements(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_bytes(b"x" * 500)
        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=1000)
        tracker.recompute()
        tracker.adjust(-500)
        assert tracker.current_usage == 0

    def test_adjust_does_not_go_negative(self, tmp_path: Path) -> None:
        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=1000)
        tracker.recompute()
        tracker.adjust(-100)
        assert tracker.current_usage == 0

    def test_recompute_resets_to_actual(self, tmp_path: Path) -> None:
        tracker = ContentSizeTracker(content_dir=tmp_path, max_size=1000)
        tracker.recompute()
        tracker.adjust(9999)  # drift the counter
        tracker.recompute()
        assert tracker.current_usage == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_services/test_storage_quota.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement ContentSizeTracker**

```python
# backend/services/storage_quota.py
"""Content directory size tracking for storage quota enforcement."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ContentSizeTracker:
    """Tracks total byte usage under the content directory.

    The counter is computed once via ``recompute()`` and then maintained
    incrementally via ``adjust()``.  All callers must hold the content
    write lock before calling ``check`` or ``adjust``.
    """

    def __init__(self, *, content_dir: Path, max_size: int | None) -> None:
        self._content_dir = content_dir
        self._max_size = max_size
        self._current_usage: int = 0

    @property
    def current_usage(self) -> int:
        return self._current_usage

    def recompute(self) -> None:
        """Walk the content directory and recompute total size."""
        total = 0
        try:
            for path in self._content_dir.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    try:
                        total += path.stat().st_size
                    except OSError:
                        pass
        except OSError as exc:
            logger.error("Failed to walk content directory for size computation: %s", exc)
        self._current_usage = total
        if self._max_size is not None:
            logger.info(
                "Content usage: %d bytes of %d byte limit (%.1f%%)",
                total,
                self._max_size,
                (total / self._max_size) * 100 if self._max_size else 0,
            )

    def check(self, incoming_bytes: int) -> bool:
        """Return True if writing incoming_bytes would stay within the quota."""
        if self._max_size is None:
            return True
        return self._current_usage + incoming_bytes <= self._max_size

    def adjust(self, delta: int) -> None:
        """Adjust the counter by delta bytes (positive for writes, negative for deletes)."""
        self._current_usage = max(0, self._current_usage + delta)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_services/test_storage_quota.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/storage_quota.py tests/test_services/test_storage_quota.py
git commit -m "feat: add ContentSizeTracker for storage quota enforcement"
```

---

### Task 3: Initialize tracker at startup

**Files:**
- Modify: `backend/main.py:283-292`
- Modify: `backend/api/deps.py`

- [ ] **Step 1: Add dependency accessor in deps.py**

Add to `backend/api/deps.py`, after the `get_content_write_lock` function (after line 129):

```python
def get_content_size_tracker(request: Request) -> ContentSizeTracker:
    """Get the content size tracker from app state."""
    from backend.services.storage_quota import ContentSizeTracker

    return cast(
        "ContentSizeTracker",
        _require_app_state(request, "content_size_tracker", _SERVICE_UNAVAILABLE),
    )
```

- [ ] **Step 2: Initialize tracker in lifespan after cache rebuild**

In `backend/main.py`, after the cache rebuild block (after line 292, before `yield`), add:

```python
        from backend.services.storage_quota import ContentSizeTracker

        content_size_tracker = ContentSizeTracker(
            content_dir=settings.content_dir,
            max_size=settings.max_content_size,
        )
        content_size_tracker.recompute()
        app.state.content_size_tracker = content_size_tracker
```

- [ ] **Step 3: Run full backend checks to verify nothing broke**

Run: `just check-backend`
Expected: PASS — no functional changes yet, just wiring

- [ ] **Step 4: Commit**

```bash
git add backend/main.py backend/api/deps.py
git commit -m "feat: initialize content size tracker at startup"
```

---

### Task 4: Enforce quota on post upload

**Files:**
- Modify: `backend/api/posts.py:251-412` (upload_post)
- Test: `tests/test_api/test_storage_quota.py`

- [ ] **Step 1: Write failing integration test**

```python
# tests/test_api/test_storage_quota.py
"""Tests for content storage quota enforcement."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backend.config import Settings
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient


@pytest.fixture
def quota_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Settings with a small storage quota."""
    db_path = tmp_path / "test.db"
    return Settings(
        secret_key="test-secret-key-with-at-least-32-characters",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        content_dir=tmp_content_dir,
        frontend_dir=tmp_path / "frontend",
        admin_username="admin",
        admin_password="admin123",
        max_content_size=5000,
    )


@pytest.fixture
async def client(quota_settings: Settings) -> AsyncGenerator[AsyncClient]:
    async with create_test_client(quota_settings) as ac:
        yield ac


async def _login(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": "admin", "password": "admin123"},
    )
    return resp.json()["access_token"]


class TestPostUploadQuota:
    @pytest.mark.asyncio
    async def test_upload_within_quota_succeeds(self, client: AsyncClient) -> None:
        token = await _login(client)
        md = b"---\ntitle: Small Post\n---\n\nHello.\n"
        resp = await client.post(
            "/api/posts/upload",
            files=[("files", ("index.md", md, "text/markdown"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_upload_exceeding_quota_returns_413(self, client: AsyncClient) -> None:
        token = await _login(client)
        # Create a file larger than the 5000-byte quota
        md = b"---\ntitle: Big Post\n---\n\n" + b"x" * 5000
        resp = await client.post(
            "/api/posts/upload",
            files=[("files", ("index.md", md, "text/markdown"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 413
        assert resp.json()["detail"] == "Storage limit reached"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_api/test_storage_quota.py::TestPostUploadQuota -v`
Expected: FAIL — no quota enforcement yet, upload succeeds

- [ ] **Step 3: Add quota check to upload_post**

In `backend/api/posts.py`, add the import and dependency parameter to `upload_post`:

Add import at the top of the file:
```python
from backend.api.deps import get_content_size_tracker
```

Add parameter to the `upload_post` function signature (after `content_write_lock`):
```python
    content_size_tracker: Annotated[ContentSizeTracker, Depends(get_content_size_tracker)],
```

Add the import for the type:
```python
from backend.services.storage_quota import ContentSizeTracker
```

Inside the `async with content_write_lock:` block, before the `post_dir.mkdir` call (before the line `post_dir = post_path.parent`), add:

```python
        if not content_size_tracker.check(total_size):
            raise HTTPException(status_code=413, detail="Storage limit reached")
```

After the successful `await session.commit()` (after line 400), add:

```python
        content_size_tracker.adjust(total_size)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_api/test_storage_quota.py::TestPostUploadQuota -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/posts.py tests/test_api/test_storage_quota.py
git commit -m "feat: enforce storage quota on post upload"
```

---

### Task 5: Enforce quota on asset upload

**Files:**
- Modify: `backend/api/posts.py:438-499` (upload_assets)
- Test: `tests/test_api/test_storage_quota.py`

- [ ] **Step 1: Write failing integration test**

Add to `tests/test_api/test_storage_quota.py`:

```python
POST_PATH = "posts/2026-01-01-seed-post/index.md"


@pytest.fixture
def quota_settings_with_post(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Settings with a quota and a pre-existing post."""
    post_dir = tmp_content_dir / "posts" / "2026-01-01-seed-post"
    post_dir.mkdir(parents=True)
    (post_dir / "index.md").write_text(
        "---\ntitle: Seed Post\ncreated_at: 2026-01-01 00:00:00+00\n"
        "author: admin\nlabels: []\n---\n\nSeed.\n"
    )
    db_path = tmp_path / "test.db"
    return Settings(
        secret_key="test-secret-key-with-at-least-32-characters",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        content_dir=tmp_content_dir,
        frontend_dir=tmp_path / "frontend",
        admin_username="admin",
        admin_password="admin123",
        max_content_size=5000,
    )


@pytest.fixture
async def client_with_post(quota_settings_with_post: Settings) -> AsyncGenerator[AsyncClient]:
    async with create_test_client(quota_settings_with_post) as ac:
        yield ac


class TestAssetUploadQuota:
    @pytest.mark.asyncio
    async def test_asset_upload_within_quota_succeeds(
        self, client_with_post: AsyncClient
    ) -> None:
        token = await _login(client_with_post)
        resp = await client_with_post.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[("files", ("photo.png", b"x" * 100, "image/png"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_asset_upload_exceeding_quota_returns_413(
        self, client_with_post: AsyncClient
    ) -> None:
        token = await _login(client_with_post)
        resp = await client_with_post.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[("files", ("photo.png", b"x" * 5000, "image/png"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 413
        assert resp.json()["detail"] == "Storage limit reached"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_api/test_storage_quota.py::TestAssetUploadQuota -v`
Expected: FAIL — no quota check on asset upload

- [ ] **Step 3: Add quota check to upload_assets**

Add `content_size_tracker` parameter to `upload_assets` function signature:

```python
    content_size_tracker: Annotated[ContentSizeTracker, Depends(get_content_size_tracker)],
```

Inside `async with content_write_lock:`, after the post existence check and before the write loop, add:

```python
        if not content_size_tracker.check(total_size):
            raise HTTPException(status_code=413, detail="Storage limit reached")
```

After the successful asset writes (after the `if uploaded:` git commit block, before the `return`), add:

```python
        content_size_tracker.adjust(total_size)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_api/test_storage_quota.py::TestAssetUploadQuota -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/posts.py tests/test_api/test_storage_quota.py
git commit -m "feat: enforce storage quota on asset upload"
```

---

### Task 6: Adjust counter on post edit, post delete, and asset delete

**Files:**
- Modify: `backend/api/posts.py` (update_post_endpoint, delete_post_endpoint, delete_asset)
- Test: `tests/test_api/test_storage_quota.py`

- [ ] **Step 1: Write failing test for delete freeing quota**

Add to `tests/test_api/test_storage_quota.py`:

```python
class TestDeleteFreesQuota:
    @pytest.mark.asyncio
    async def test_delete_post_frees_space_for_new_upload(
        self, client_with_post: AsyncClient, quota_settings_with_post: Settings
    ) -> None:
        token = await _login(client_with_post)
        # Upload an asset that nearly fills the quota
        resp = await client_with_post.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[("files", ("big.bin", b"x" * 3000, "application/octet-stream"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        # Delete the post (frees the post directory and its assets)
        resp = await client_with_post.delete(
            f"/api/posts/{POST_PATH}?delete_assets=true",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 204

        # Now a new upload should succeed since space was freed
        md = b"---\ntitle: New Post\n---\n\nAfter delete.\n"
        resp = await client_with_post.post(
            "/api/posts/upload",
            files=[("files", ("index.md", md, "text/markdown"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_api/test_storage_quota.py::TestDeleteFreesQuota -v`
Expected: FAIL — counter not decremented on delete, so second upload is rejected

- [ ] **Step 3: Add counter adjustments to update, delete_post, and delete_asset**

**update_post_endpoint:** Add `content_size_tracker` parameter. Before `content_manager.write_post(file_path, post_data)`, compute the old file size. After the write, adjust by delta:

```python
    content_size_tracker: Annotated[ContentSizeTracker, Depends(get_content_size_tracker)],
```

Before the `content_manager.write_post` call:
```python
        old_post_path = content_manager.content_dir / file_path
        old_size = old_post_path.stat().st_size if old_post_path.exists() else 0
```

After the successful `content_manager.write_post`:
```python
        new_size = (content_manager.content_dir / file_path).stat().st_size
        content_size_tracker.adjust(new_size - old_size)
```

Also add quota check before writing (for the case where an edit grows the file):
```python
        new_serialized_size = len(serialized.encode("utf-8"))
        edit_delta = new_serialized_size - old_size
        if edit_delta > 0 and not content_size_tracker.check(edit_delta):
            raise HTTPException(status_code=413, detail="Storage limit reached")
```

**delete_post_endpoint:** Add `content_size_tracker` parameter. Before the `content_manager.delete_post` call, compute directory size. After successful delete, adjust:

```python
    content_size_tracker: Annotated[ContentSizeTracker, Depends(get_content_size_tracker)],
```

Before the delete call, compute the size to free:
```python
        post_dir = (content_manager.content_dir / file_path).parent
        dir_size = sum(
            f.stat().st_size for f in post_dir.rglob("*")
            if f.is_file() and not f.is_symlink()
        ) if should_delete_assets and post_dir.is_dir() else (
            (content_manager.content_dir / file_path).stat().st_size
            if (content_manager.content_dir / file_path).exists() else 0
        )
```

After the delete (in the existing try/except, on success path):
```python
            content_size_tracker.adjust(-dir_size)
```

**delete_asset:** Add `content_size_tracker` parameter. Before `asset_path.unlink()`, get file size. After successful unlink, adjust:

```python
    content_size_tracker: Annotated[ContentSizeTracker, Depends(get_content_size_tracker)],
```

Before unlink:
```python
        asset_size = asset_path.stat().st_size
```

After successful unlink:
```python
        content_size_tracker.adjust(-asset_size)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_api/test_storage_quota.py -v`
Expected: PASS

- [ ] **Step 5: Run full upload and asset test suites to check for regressions**

Run: `just test-backend -- tests/test_api/test_post_upload.py tests/test_api/test_post_assets_upload.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/api/posts.py tests/test_api/test_storage_quota.py
git commit -m "feat: adjust storage counter on post edit, delete, and asset delete"
```

---

### Task 7: Enforce quota on sync commit and recompute after rebuild

**Files:**
- Modify: `backend/api/sync.py:191-462`
- Test: `tests/test_api/test_storage_quota.py`

- [ ] **Step 1: Write failing integration test**

Add to `tests/test_api/test_storage_quota.py`:

```python
class TestSyncQuota:
    @pytest.mark.asyncio
    async def test_sync_commit_exceeding_quota_returns_413(
        self, client: AsyncClient
    ) -> None:
        token = await _login(client)
        big_content = (
            "---\ntitle: Huge Sync Post\ncreated_at: 2026-01-01 00:00:00+00\n"
            "author: admin\nlabels: []\n---\n\n" + "x" * 5000
        )
        resp = await client.post(
            "/api/sync/commit",
            data={"metadata": '{"deleted_files":[],"last_sync_commit":null}'},
            files=[("files", ("posts/2026-01-01-huge/index.md", big_content.encode(), "text/plain"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 413
        assert resp.json()["detail"] == "Storage limit reached"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_api/test_storage_quota.py::TestSyncQuota -v`
Expected: FAIL — no quota check in sync

- [ ] **Step 3: Add quota check and recompute to sync**

In `backend/api/sync.py`, add imports:
```python
from backend.api.deps import get_content_size_tracker
from backend.services.storage_quota import ContentSizeTracker
```

Add `content_size_tracker` parameter to `sync_commit`:
```python
    content_size_tracker: Annotated[ContentSizeTracker, Depends(get_content_size_tracker)],
```

Pass it through to `_sync_commit_inner`:
```python
        return await _sync_commit_inner(
            ...,
            content_size_tracker=content_size_tracker,
        )
```

Add parameter to `_sync_commit_inner`:
```python
    content_size_tracker: ContentSizeTracker,
```

The sync handler reads file content in a per-file loop (line 284: `upload_content = await upload.read(...)`). Add a pre-read pass that computes total incoming size and checks the quota before any file processing. Before the `# ── Apply deletions ──` section (before line 256), add:

```python
    # ── Quota check ──
    total_incoming = 0
    for upload in upload_files:
        size = upload.size
        if size is not None:
            total_incoming += min(size, _MAX_UPLOAD_SIZE)
        else:
            total_incoming += _MAX_UPLOAD_SIZE  # conservative estimate
    if not content_size_tracker.check(total_incoming):
        raise HTTPException(status_code=413, detail="Storage limit reached")
```

This uses the `UploadFile.size` attribute (content-length per part) for a fast pre-check without reading file data. The per-file size limit is already enforced later.

After the cache rebuild (after `rebuild_cache` at line 432), add:

```python
        content_size_tracker.recompute()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_api/test_storage_quota.py::TestSyncQuota -v`
Expected: PASS

- [ ] **Step 5: Run full sync test suite**

Run: `just test-backend -- tests/test_services/test_sync_merge_integration.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/api/sync.py tests/test_api/test_storage_quota.py
git commit -m "feat: enforce storage quota on sync commit, recompute after rebuild"
```

---

### Task 8: Add deployment script prompt and CLI argument

**Files:**
- Modify: `cli/deploy_production.py:126-148` (DeployConfig), `250-284` (build_env_content), `2296-2453` (collect_config), `2459-2534` (config_from_args), `2566-2662` (_parse_args)
- Modify: `.env.example`
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_cli/test_deploy_production.py`:

```python
def test_build_env_content_includes_max_content_size() -> None:
    config = DeployConfig(
        secret_key="test-secret",
        admin_username="admin",
        admin_password="testpass123",
        trusted_hosts=["example.com"],
        trusted_proxy_ips=[],
        host_port=8000,
        host_bind_ip="127.0.0.1",
        caddy_config=None,
        caddy_public=False,
        expose_docs=False,
        max_content_size="2G",
    )
    env = build_env_content(config)
    assert "MAX_CONTENT_SIZE=2G" in env


def test_build_env_content_omits_max_content_size_when_none() -> None:
    config = DeployConfig(
        secret_key="test-secret",
        admin_username="admin",
        admin_password="testpass123",
        trusted_hosts=["example.com"],
        trusted_proxy_ips=[],
        host_port=8000,
        host_bind_ip="127.0.0.1",
        caddy_config=None,
        caddy_public=False,
        expose_docs=False,
    )
    env = build_env_content(config)
    assert "MAX_CONTENT_SIZE" not in env
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::test_build_env_content_includes_max_content_size tests/test_cli/test_deploy_production.py::test_build_env_content_omits_max_content_size_when_none -v`
Expected: FAIL — field does not exist

- [ ] **Step 3: Implement deployment script changes**

**DeployConfig:** Add field:
```python
    max_content_size: str | None = None
```

**build_env_content:** Before the `if config.image_ref` block (before line 282), add:
```python
    if config.max_content_size is not None:
        lines.append(f"MAX_CONTENT_SIZE={config.max_content_size}")
```

**collect_config:** After the `expose_docs` prompt (after line 2424), add:
```python
    max_content_size_raw = input(
        "Max content storage size (e.g., 2G, 500M) [unlimited]: "
    ).strip()
    max_content_size = max_content_size_raw or None
```

Pass to `DeployConfig`:
```python
        max_content_size=max_content_size,
```

**config_from_args:** Add to `DeployConfig` construction:
```python
        max_content_size=args.max_content_size,
```

**_parse_args:** Add CLI argument:
```python
    config_group.add_argument(
        "--max-content-size",
        help="Maximum total content storage size (e.g., 2G, 500M). Unlimited if omitted.",
    )
```

**.env.example:** Add after the `TRUSTED_PROXY_IPS` line:
```
# Maximum total content directory size (e.g., 2G, 500M). Unlimited if omitted.
# MAX_CONTENT_SIZE=
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::test_build_env_content_includes_max_content_size tests/test_cli/test_deploy_production.py::test_build_env_content_omits_max_content_size_when_none -v`
Expected: PASS

- [ ] **Step 5: Run the full deploy production test suite to check regressions**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add cli/deploy_production.py .env.example tests/test_cli/test_deploy_production.py
git commit -m "feat: add MAX_CONTENT_SIZE to deployment script and .env.example"
```

---

### Task 9: Run full check and update docs

**Files:**
- Modify: `docs/arch/backend.md` (if architecture doc needs update)

- [ ] **Step 1: Run full project checks**

Run: `just check`
Expected: PASS

- [ ] **Step 2: Update architecture docs if needed**

If storage quota is a significant enough architectural addition, add a brief mention in `docs/arch/backend.md` under the "API Surface" or "Write Coordination" section. A single sentence is sufficient:

> Content mutations can optionally be subject to a storage quota (`MAX_CONTENT_SIZE`) that caps the total size of files under `content/`.

- [ ] **Step 3: Commit any doc updates**

```bash
git add docs/arch/backend.md
git commit -m "docs: mention storage quota in backend architecture"
```
