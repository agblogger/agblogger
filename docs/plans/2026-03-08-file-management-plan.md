# File Management Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a collapsible file strip to the editor for managing post assets (list, upload, delete, rename, insert).

**Architecture:** Three new backend endpoints (list/delete/rename assets) + two new frontend components (FileStrip, FileCard) integrated into EditorPage. Save-and-stay flow change so new posts stay on editor after save. View Post button with unsaved-changes dialog.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, React 19, TypeScript, Vitest, testing-library

---

### Task 1: Backend — List Assets Endpoint

**Files:**
- Modify: `backend/api/posts.py` (add endpoint after `upload_assets`, around line 439)
- Modify: `backend/schemas/post.py` (add response schema)
- Test: `tests/test_api/test_post_assets_upload.py` (extend with list tests)

**Step 1: Write failing tests**

Add to `tests/test_api/test_post_assets_upload.py`:

```python
class TestListAssets:
    @pytest.mark.asyncio
    async def test_list_assets_empty(self, client: AsyncClient) -> None:
        token = await _login(client)
        resp = await client.get(
            "/api/posts/posts/hello.md/assets",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["assets"] == []

    @pytest.mark.asyncio
    async def test_list_assets_after_upload(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        token = await _login(client)
        # Upload a file first
        await client.post(
            "/api/posts/posts/hello.md/assets",
            files=[("files", ("photo.png", b"fake-png", "image/png"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = await client.get(
            "/api/posts/posts/hello.md/assets",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assets = resp.json()["assets"]
        assert len(assets) == 1
        assert assets[0]["name"] == "photo.png"
        assert assets[0]["size"] > 0
        assert assets[0]["is_image"] is True

    @pytest.mark.asyncio
    async def test_list_assets_excludes_index_md(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        """index.md should never appear in the asset list."""
        token = await _login(client)
        # Create a post-per-directory post
        resp = await client.post(
            "/api/posts",
            json={"title": "Dir Post", "body": "Content", "labels": [], "is_draft": False},
            headers={"Authorization": f"Bearer {token}"},
        )
        file_path = resp.json()["file_path"]
        # Upload an asset
        await client.post(
            f"/api/posts/{file_path}/assets",
            files=[("files", ("img.jpg", b"data", "image/jpeg"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = await client.get(
            f"/api/posts/{file_path}/assets",
            headers={"Authorization": f"Bearer {token}"},
        )
        assets = resp.json()["assets"]
        names = [a["name"] for a in assets]
        assert "index.md" not in names
        assert "img.jpg" in names

    @pytest.mark.asyncio
    async def test_list_assets_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/api/posts/posts/hello.md/assets")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_assets_nonexistent_post(self, client: AsyncClient) -> None:
        token = await _login(client)
        resp = await client.get(
            "/api/posts/posts/nonexistent.md/assets",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/lukasz/dev/agblogger && python -m pytest tests/test_api/test_post_assets_upload.py::TestListAssets -v`
Expected: FAIL (404, endpoint doesn't exist)

**Step 3: Add schema and implement endpoint**

In `backend/schemas/post.py`, add:

```python
class AssetInfo(BaseModel):
    """Info about a single asset file."""

    name: str
    size: int
    is_image: bool


class AssetListResponse(BaseModel):
    """Response for listing post assets."""

    assets: list[AssetInfo]
```

In `backend/api/posts.py`, add after the `upload_assets` function (around line 439), before the `get_post_endpoint`:

```python
_IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "gif", "webp", "svg", "avif"})


@router.get("/{file_path:path}/assets", response_model=AssetListResponse)
async def list_assets(
    file_path: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    _user: Annotated[User, Depends(require_admin)],
) -> AssetListResponse:
    """List asset files in a post's directory."""
    stmt = select(PostCache).where(PostCache.file_path == file_path)
    result = await session.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Post not found")

    post_dir = (content_manager.content_dir / file_path).parent
    assets: list[AssetInfo] = []
    try:
        for entry in sorted(post_dir.iterdir()):
            if entry.name == "index.md" or entry.name.startswith(".") or not entry.is_file():
                continue
            ext = entry.suffix.lstrip(".").lower()
            assets.append(
                AssetInfo(
                    name=entry.name,
                    size=entry.stat().st_size,
                    is_image=ext in _IMAGE_EXTENSIONS,
                )
            )
    except OSError as exc:
        logger.error("Failed to list assets for %s: %s", file_path, exc)
        raise HTTPException(status_code=500, detail="Failed to list assets") from exc

    return AssetListResponse(assets=assets)
```

Add the import for `AssetListResponse` and `AssetInfo` to the imports section at the top of `backend/api/posts.py`.

**Step 4: Run tests to verify they pass**

Run: `cd /Users/lukasz/dev/agblogger && python -m pytest tests/test_api/test_post_assets_upload.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add backend/api/posts.py backend/schemas/post.py tests/test_api/test_post_assets_upload.py
git commit -m "feat: add list assets endpoint"
```

---

### Task 2: Backend — Delete Asset Endpoint

**Files:**
- Modify: `backend/api/posts.py` (add endpoint after `list_assets`)
- Test: `tests/test_api/test_post_assets_upload.py`

**Step 1: Write failing tests**

Add to `tests/test_api/test_post_assets_upload.py`:

```python
class TestDeleteAsset:
    @pytest.mark.asyncio
    async def test_delete_asset(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        token = await _login(client)
        # Upload first
        await client.post(
            "/api/posts/posts/hello.md/assets",
            files=[("files", ("photo.png", b"data", "image/png"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert (app_settings.content_dir / "posts" / "photo.png").exists()

        resp = await client.delete(
            "/api/posts/posts/hello.md/assets/photo.png",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 204
        assert not (app_settings.content_dir / "posts" / "photo.png").exists()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_asset(self, client: AsyncClient) -> None:
        token = await _login(client)
        resp = await client.delete(
            "/api/posts/posts/hello.md/assets/nope.png",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_asset_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.delete("/api/posts/posts/hello.md/assets/photo.png")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_cannot_delete_index_md(self, client: AsyncClient) -> None:
        """Prevent deletion of the post content file via asset endpoint."""
        token = await _login(client)
        resp = await client.post(
            "/api/posts",
            json={"title": "Test", "body": "Content", "labels": [], "is_draft": False},
            headers={"Authorization": f"Bearer {token}"},
        )
        file_path = resp.json()["file_path"]
        resp = await client.delete(
            f"/api/posts/{file_path}/assets/index.md",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_cannot_delete_hidden_file(self, client: AsyncClient) -> None:
        token = await _login(client)
        resp = await client.delete(
            "/api/posts/posts/hello.md/assets/.gitkeep",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_asset_path_traversal(self, client: AsyncClient) -> None:
        token = await _login(client)
        resp = await client.delete(
            "/api/posts/posts/hello.md/assets/..%2F..%2Findex.toml",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/lukasz/dev/agblogger && python -m pytest tests/test_api/test_post_assets_upload.py::TestDeleteAsset -v`
Expected: FAIL

**Step 3: Implement endpoint**

Add after `list_assets` in `backend/api/posts.py`:

```python
def _validate_asset_filename(filename: str) -> None:
    """Validate an asset filename for safety."""
    if not filename or filename.startswith(".") or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail=f"Invalid filename: {filename}")
    if filename == "index.md":
        raise HTTPException(status_code=400, detail="Cannot modify the post content file")
    # Prevent path traversal via encoded characters
    cleaned = FilePath(filename).name
    if cleaned != filename:
        raise HTTPException(status_code=400, detail=f"Invalid filename: {filename}")


@router.delete("/{file_path:path}/assets/{filename}", status_code=204)
async def delete_asset(
    file_path: str,
    filename: str,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    content_write_lock: Annotated[AsyncWriteLock, Depends(get_content_write_lock)],
    _user: Annotated[User, Depends(require_admin)],
) -> None:
    """Delete a single asset file from a post's directory."""
    _validate_asset_filename(filename)

    async with content_write_lock:
        stmt = select(PostCache).where(PostCache.file_path == file_path)
        result = await session.execute(stmt)
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Post not found")

        asset_path = (content_manager.content_dir / file_path).parent / filename
        if not asset_path.is_file():
            raise HTTPException(status_code=404, detail="Asset not found")

        try:
            asset_path.unlink()
        except OSError as exc:
            logger.error("Failed to delete asset %s: %s", asset_path, exc)
            raise HTTPException(status_code=500, detail="Failed to delete asset") from exc

        set_git_warning(
            response,
            await git_service.try_commit(f"Delete asset {filename} from {file_path}"),
        )
```

**Step 4: Run tests**

Run: `cd /Users/lukasz/dev/agblogger && python -m pytest tests/test_api/test_post_assets_upload.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add backend/api/posts.py tests/test_api/test_post_assets_upload.py
git commit -m "feat: add delete asset endpoint"
```

---

### Task 3: Backend — Rename Asset Endpoint

**Files:**
- Modify: `backend/api/posts.py` (add endpoint after `delete_asset`)
- Modify: `backend/schemas/post.py` (add request schema)
- Test: `tests/test_api/test_post_assets_upload.py`

**Step 1: Write failing tests**

Add to `tests/test_api/test_post_assets_upload.py`:

```python
class TestRenameAsset:
    @pytest.mark.asyncio
    async def test_rename_asset(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        token = await _login(client)
        await client.post(
            "/api/posts/posts/hello.md/assets",
            files=[("files", ("old.png", b"data", "image/png"))],
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = await client.patch(
            "/api/posts/posts/hello.md/assets/old.png",
            json={"new_name": "new.png"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "new.png"
        assert not (app_settings.content_dir / "posts" / "old.png").exists()
        assert (app_settings.content_dir / "posts" / "new.png").exists()

    @pytest.mark.asyncio
    async def test_rename_to_existing_name(
        self, client: AsyncClient
    ) -> None:
        token = await _login(client)
        await client.post(
            "/api/posts/posts/hello.md/assets",
            files=[
                ("files", ("a.png", b"data-a", "image/png")),
                ("files", ("b.png", b"data-b", "image/png")),
            ],
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = await client.patch(
            "/api/posts/posts/hello.md/assets/a.png",
            json={"new_name": "b.png"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_rename_nonexistent_asset(self, client: AsyncClient) -> None:
        token = await _login(client)
        resp = await client.patch(
            "/api/posts/posts/hello.md/assets/nope.png",
            json={"new_name": "new.png"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_rename_to_invalid_name(self, client: AsyncClient) -> None:
        token = await _login(client)
        await client.post(
            "/api/posts/posts/hello.md/assets",
            files=[("files", ("photo.png", b"data", "image/png"))],
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = await client.patch(
            "/api/posts/posts/hello.md/assets/photo.png",
            json={"new_name": ".hidden"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_rename_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.patch(
            "/api/posts/posts/hello.md/assets/photo.png",
            json={"new_name": "new.png"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_cannot_rename_to_index_md(self, client: AsyncClient) -> None:
        token = await _login(client)
        await client.post(
            "/api/posts/posts/hello.md/assets",
            files=[("files", ("photo.png", b"data", "image/png"))],
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = await client.patch(
            "/api/posts/posts/hello.md/assets/photo.png",
            json={"new_name": "index.md"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/lukasz/dev/agblogger && python -m pytest tests/test_api/test_post_assets_upload.py::TestRenameAsset -v`
Expected: FAIL

**Step 3: Add schema and implement**

In `backend/schemas/post.py`, add:

```python
class AssetRenameRequest(BaseModel):
    """Request body for renaming an asset."""

    new_name: str = Field(min_length=1, max_length=255)
```

In `backend/api/posts.py`, add after `delete_asset`:

```python
@router.patch("/{file_path:path}/assets/{filename}", response_model=AssetInfo)
async def rename_asset(
    file_path: str,
    filename: str,
    body: AssetRenameRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    content_write_lock: Annotated[AsyncWriteLock, Depends(get_content_write_lock)],
    _user: Annotated[User, Depends(require_admin)],
) -> AssetInfo:
    """Rename an asset file in a post's directory."""
    _validate_asset_filename(filename)
    _validate_asset_filename(body.new_name)

    async with content_write_lock:
        stmt = select(PostCache).where(PostCache.file_path == file_path)
        result = await session.execute(stmt)
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Post not found")

        post_dir = (content_manager.content_dir / file_path).parent
        old_path = post_dir / filename
        new_path = post_dir / body.new_name

        if not old_path.is_file():
            raise HTTPException(status_code=404, detail="Asset not found")
        if new_path.exists():
            raise HTTPException(status_code=409, detail="A file with that name already exists")

        try:
            old_path.rename(new_path)
        except OSError as exc:
            logger.error("Failed to rename asset %s -> %s: %s", old_path, new_path, exc)
            raise HTTPException(status_code=500, detail="Failed to rename asset") from exc

        set_git_warning(
            response,
            await git_service.try_commit(
                f"Rename asset {filename} -> {body.new_name} in {file_path}"
            ),
        )

        ext = new_path.suffix.lstrip(".").lower()
        return AssetInfo(
            name=body.new_name,
            size=new_path.stat().st_size,
            is_image=ext in _IMAGE_EXTENSIONS,
        )
```

Add the import for `AssetRenameRequest` to the imports at the top.

**Step 4: Run tests**

Run: `cd /Users/lukasz/dev/agblogger && python -m pytest tests/test_api/test_post_assets_upload.py -v`
Expected: ALL PASS

**Step 5: Run backend static checks**

Run: `cd /Users/lukasz/dev/agblogger && just check-backend-static`
Expected: PASS

**Step 6: Commit**

```bash
git add backend/api/posts.py backend/schemas/post.py tests/test_api/test_post_assets_upload.py
git commit -m "feat: add rename asset endpoint"
```

---

### Task 4: Frontend — API Functions for Asset Management

**Files:**
- Modify: `frontend/src/api/posts.ts` (add 3 new functions)
- Modify: `frontend/src/api/client.ts` (add AssetInfo type)

**Step 1: Add types to client.ts**

In `frontend/src/api/client.ts`, add after the `PostEditResponse` interface:

```typescript
export interface AssetInfo {
  name: string
  size: number
  is_image: boolean
}

export interface AssetListResponse {
  assets: AssetInfo[]
}
```

**Step 2: Add API functions to posts.ts**

In `frontend/src/api/posts.ts`, add the import for the new types and add:

```typescript
export async function fetchPostAssets(filePath: string): Promise<AssetListResponse> {
  return api.get(`posts/${filePath}/assets`).json<AssetListResponse>()
}

export async function deletePostAsset(filePath: string, filename: string): Promise<void> {
  await api.delete(`posts/${filePath}/assets/${encodeURIComponent(filename)}`)
}

export async function renamePostAsset(
  filePath: string,
  filename: string,
  newName: string,
): Promise<AssetInfo> {
  return api
    .patch(`posts/${filePath}/assets/${encodeURIComponent(filename)}`, {
      json: { new_name: newName },
    })
    .json<AssetInfo>()
}
```

**Step 3: Run frontend static checks**

Run: `cd /Users/lukasz/dev/agblogger && just check-frontend-static`
Expected: PASS

**Step 4: Commit**

```bash
git add frontend/src/api/posts.ts frontend/src/api/client.ts
git commit -m "feat: add asset management API functions"
```

---

### Task 5: Frontend — FileCard Component

**Files:**
- Create: `frontend/src/components/editor/FileCard.tsx`
- Create: `frontend/src/components/editor/__tests__/FileCard.test.tsx`

**Step 1: Write failing tests**

Create `frontend/src/components/editor/__tests__/FileCard.test.tsx`:

```tsx
import { createElement } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'

import FileCard from '../FileCard'
import type { AssetInfo } from '@/api/client'

const imageAsset: AssetInfo = { name: 'photo.png', size: 1024, is_image: true }
const docAsset: AssetInfo = { name: 'data.csv', size: 2048, is_image: false }

describe('FileCard', () => {
  it('renders filename', () => {
    render(
      createElement(FileCard, {
        asset: imageAsset,
        filePath: 'posts/2026-03-08-test/index.md',
        onInsert: vi.fn(),
        onDelete: vi.fn(),
        onRename: vi.fn(),
      }),
    )
    expect(screen.getByText('photo.png')).toBeInTheDocument()
  })

  it('renders image thumbnail for image assets', () => {
    render(
      createElement(FileCard, {
        asset: imageAsset,
        filePath: 'posts/2026-03-08-test/index.md',
        onInsert: vi.fn(),
        onDelete: vi.fn(),
        onRename: vi.fn(),
      }),
    )
    const img = screen.getByRole('img')
    expect(img).toHaveAttribute('src', '/api/content/posts/2026-03-08-test/photo.png')
  })

  it('renders file icon for non-image assets', () => {
    render(
      createElement(FileCard, {
        asset: docAsset,
        filePath: 'posts/2026-03-08-test/index.md',
        onInsert: vi.fn(),
        onDelete: vi.fn(),
        onRename: vi.fn(),
      }),
    )
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('shows menu on kebab click', async () => {
    const user = userEvent.setup()
    render(
      createElement(FileCard, {
        asset: imageAsset,
        filePath: 'posts/2026-03-08-test/index.md',
        onInsert: vi.fn(),
        onDelete: vi.fn(),
        onRename: vi.fn(),
      }),
    )
    await user.click(screen.getByRole('button', { name: /menu/i }))
    expect(screen.getByText('Insert')).toBeInTheDocument()
    expect(screen.getByText('Copy name')).toBeInTheDocument()
    expect(screen.getByText('Rename')).toBeInTheDocument()
    expect(screen.getByText('Delete')).toBeInTheDocument()
  })

  it('calls onInsert when Insert is clicked', async () => {
    const handleInsert = vi.fn()
    const user = userEvent.setup()
    render(
      createElement(FileCard, {
        asset: imageAsset,
        filePath: 'posts/2026-03-08-test/index.md',
        onInsert: handleInsert,
        onDelete: vi.fn(),
        onRename: vi.fn(),
      }),
    )
    await user.click(screen.getByRole('button', { name: /menu/i }))
    await user.click(screen.getByText('Insert'))
    expect(handleInsert).toHaveBeenCalledWith('photo.png', true)
  })

  it('calls onDelete when Delete is clicked', async () => {
    const handleDelete = vi.fn()
    const user = userEvent.setup()
    render(
      createElement(FileCard, {
        asset: docAsset,
        filePath: 'posts/2026-03-08-test/index.md',
        onInsert: vi.fn(),
        onDelete: handleDelete,
        onRename: vi.fn(),
      }),
    )
    await user.click(screen.getByRole('button', { name: /menu/i }))
    await user.click(screen.getByText('Delete'))
    expect(handleDelete).toHaveBeenCalledWith('data.csv')
  })

  it('enters rename mode and confirms with Enter', async () => {
    const handleRename = vi.fn()
    const user = userEvent.setup()
    render(
      createElement(FileCard, {
        asset: imageAsset,
        filePath: 'posts/2026-03-08-test/index.md',
        onInsert: vi.fn(),
        onDelete: vi.fn(),
        onRename: handleRename,
      }),
    )
    await user.click(screen.getByRole('button', { name: /menu/i }))
    await user.click(screen.getByText('Rename'))

    const input = screen.getByDisplayValue('photo.png')
    await user.clear(input)
    await user.type(input, 'new-photo.png{Enter}')

    expect(handleRename).toHaveBeenCalledWith('photo.png', 'new-photo.png')
  })

  it('cancels rename with Escape', async () => {
    const handleRename = vi.fn()
    const user = userEvent.setup()
    render(
      createElement(FileCard, {
        asset: imageAsset,
        filePath: 'posts/2026-03-08-test/index.md',
        onInsert: vi.fn(),
        onDelete: vi.fn(),
        onRename: handleRename,
      }),
    )
    await user.click(screen.getByRole('button', { name: /menu/i }))
    await user.click(screen.getByText('Rename'))

    const input = screen.getByDisplayValue('photo.png')
    await user.type(input, '{Escape}')

    expect(handleRename).not.toHaveBeenCalled()
    expect(screen.getByText('photo.png')).toBeInTheDocument()
  })
})
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/lukasz/dev/agblogger/frontend && npx vitest run src/components/editor/__tests__/FileCard.test.tsx`
Expected: FAIL (FileCard doesn't exist)

**Step 3: Implement FileCard**

Create `frontend/src/components/editor/FileCard.tsx`:

```tsx
import { useEffect, useRef, useState } from 'react'
import { File as FileIcon, MoreVertical } from 'lucide-react'

import type { AssetInfo } from '@/api/client'

interface FileCardProps {
  asset: AssetInfo
  filePath: string
  onInsert: (name: string, isImage: boolean) => void
  onDelete: (name: string) => void
  onRename: (oldName: string, newName: string) => void
  disabled?: boolean
}

export default function FileCard({ asset, filePath, onInsert, onDelete, onRename, disabled }: FileCardProps) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [renameValue, setRenameValue] = useState(asset.name)
  const menuRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const contentDir = filePath.replace(/\/[^/]+$/, '')
  const thumbnailUrl = `/api/content/${contentDir}/${asset.name}`

  useEffect(() => {
    if (renaming && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [renaming])

  useEffect(() => {
    if (!menuOpen) return
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [menuOpen])

  function handleRenameConfirm() {
    const trimmed = renameValue.trim()
    if (trimmed && trimmed !== asset.name) {
      onRename(asset.name, trimmed)
    }
    setRenaming(false)
  }

  function handleRenameKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleRenameConfirm()
    } else if (e.key === 'Escape') {
      setRenaming(false)
      setRenameValue(asset.name)
    }
  }

  function handleCopyName() {
    void navigator.clipboard.writeText(asset.name)
    setMenuOpen(false)
  }

  return (
    <div className="relative flex flex-col items-center w-20">
      <div className="relative w-20 h-20 rounded-lg border border-border bg-paper-warm flex items-center justify-center overflow-hidden group">
        {asset.is_image ? (
          <img
            src={thumbnailUrl}
            alt={asset.name}
            className="w-full h-full object-cover"
          />
        ) : (
          <FileIcon size={28} className="text-muted" />
        )}

        <div className="absolute top-0.5 right-0.5" ref={menuRef}>
          <button
            type="button"
            aria-label="menu"
            onClick={() => setMenuOpen(!menuOpen)}
            disabled={disabled}
            className="p-0.5 rounded bg-paper/80 hover:bg-paper text-muted hover:text-ink transition-colors"
          >
            <MoreVertical size={14} />
          </button>

          {menuOpen && (
            <div className="absolute right-0 top-6 z-10 w-32 bg-paper border border-border rounded-lg shadow-lg py-1">
              <button
                type="button"
                onClick={() => { onInsert(asset.name, asset.is_image); setMenuOpen(false) }}
                className="w-full text-left px-3 py-1.5 text-sm text-ink hover:bg-paper-warm transition-colors"
              >
                Insert
              </button>
              <button
                type="button"
                onClick={handleCopyName}
                className="w-full text-left px-3 py-1.5 text-sm text-ink hover:bg-paper-warm transition-colors"
              >
                Copy name
              </button>
              <button
                type="button"
                onClick={() => { setRenaming(true); setRenameValue(asset.name); setMenuOpen(false) }}
                className="w-full text-left px-3 py-1.5 text-sm text-ink hover:bg-paper-warm transition-colors"
              >
                Rename
              </button>
              <button
                type="button"
                onClick={() => { onDelete(asset.name); setMenuOpen(false) }}
                className="w-full text-left px-3 py-1.5 text-sm text-red-600 dark:text-red-400 hover:bg-paper-warm transition-colors"
              >
                Delete
              </button>
            </div>
          )}
        </div>
      </div>

      {renaming ? (
        <input
          ref={inputRef}
          type="text"
          value={renameValue}
          onChange={(e) => setRenameValue(e.target.value)}
          onKeyDown={handleRenameKeyDown}
          onBlur={handleRenameConfirm}
          className="mt-1 w-full text-xs text-center text-ink bg-paper border border-accent rounded px-1 py-0.5
                   focus:outline-none focus:ring-1 focus:ring-accent/20"
        />
      ) : (
        <span className="mt-1 text-xs text-muted truncate w-full text-center" title={asset.name}>
          {asset.name}
        </span>
      )}
    </div>
  )
}
```

**Step 4: Run tests**

Run: `cd /Users/lukasz/dev/agblogger/frontend && npx vitest run src/components/editor/__tests__/FileCard.test.tsx`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add frontend/src/components/editor/FileCard.tsx frontend/src/components/editor/__tests__/FileCard.test.tsx
git commit -m "feat: add FileCard component"
```

---

### Task 6: Frontend — FileStrip Component

**Files:**
- Create: `frontend/src/components/editor/FileStrip.tsx`
- Create: `frontend/src/components/editor/__tests__/FileStrip.test.tsx`

**Step 1: Write failing tests**

Create `frontend/src/components/editor/__tests__/FileStrip.test.tsx`:

```tsx
import { createElement } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { fetchPostAssets, deletePostAsset, renamePostAsset, uploadAssets } from '@/api/posts'

vi.mock('@/api/posts', () => ({
  fetchPostAssets: vi.fn(),
  deletePostAsset: vi.fn(),
  renamePostAsset: vi.fn(),
  uploadAssets: vi.fn(),
}))

import FileStrip from '../FileStrip'

const mockFetchAssets = vi.mocked(fetchPostAssets)
const mockDeleteAsset = vi.mocked(deletePostAsset)
const mockRenameAsset = vi.mocked(renamePostAsset)

describe('FileStrip', () => {
  beforeEach(() => {
    mockFetchAssets.mockReset()
    mockDeleteAsset.mockReset()
    mockRenameAsset.mockReset()
  })

  it('shows "save to start" message when post is unsaved', () => {
    render(
      createElement(FileStrip, {
        filePath: null,
        body: '',
        onBodyChange: vi.fn(),
        onInsertAtCursor: vi.fn(),
        disabled: false,
      }),
    )
    expect(screen.getByText(/save.*to start adding files/i)).toBeInTheDocument()
  })

  it('fetches and displays assets for saved post', async () => {
    mockFetchAssets.mockResolvedValue({
      assets: [
        { name: 'photo.png', size: 1024, is_image: true },
        { name: 'data.csv', size: 2048, is_image: false },
      ],
    })

    render(
      createElement(FileStrip, {
        filePath: 'posts/2026-03-08-test/index.md',
        body: '',
        onBodyChange: vi.fn(),
        onInsertAtCursor: vi.fn(),
        disabled: false,
      }),
    )

    // Expand the strip
    await waitFor(() => {
      expect(screen.getByText(/files \(2\)/i)).toBeInTheDocument()
    })
    const user = userEvent.setup()
    await user.click(screen.getByText(/files \(2\)/i))

    await waitFor(() => {
      expect(screen.getByText('photo.png')).toBeInTheDocument()
      expect(screen.getByText('data.csv')).toBeInTheDocument()
    })
  })

  it('shows file count in collapsed header', async () => {
    mockFetchAssets.mockResolvedValue({
      assets: [{ name: 'a.png', size: 100, is_image: true }],
    })

    render(
      createElement(FileStrip, {
        filePath: 'posts/2026-03-08-test/index.md',
        body: '',
        onBodyChange: vi.fn(),
        onInsertAtCursor: vi.fn(),
        disabled: false,
      }),
    )

    await waitFor(() => {
      expect(screen.getByText(/files \(1\)/i)).toBeInTheDocument()
    })
  })

  it('shows "Files" with no count when empty', async () => {
    mockFetchAssets.mockResolvedValue({ assets: [] })

    render(
      createElement(FileStrip, {
        filePath: 'posts/2026-03-08-test/index.md',
        body: '',
        onBodyChange: vi.fn(),
        onInsertAtCursor: vi.fn(),
        disabled: false,
      }),
    )

    await waitFor(() => {
      expect(screen.getByText('Files')).toBeInTheDocument()
    })
  })

  it('shows delete confirmation when file is referenced in body', async () => {
    mockFetchAssets.mockResolvedValue({
      assets: [{ name: 'photo.png', size: 1024, is_image: true }],
    })

    const user = userEvent.setup()
    render(
      createElement(FileStrip, {
        filePath: 'posts/2026-03-08-test/index.md',
        body: '![photo](photo.png)',
        onBodyChange: vi.fn(),
        onInsertAtCursor: vi.fn(),
        disabled: false,
      }),
    )

    // Expand and open menu
    await waitFor(() => {
      expect(screen.getByText(/files \(1\)/i)).toBeInTheDocument()
    })
    await user.click(screen.getByText(/files \(1\)/i))
    await waitFor(() => {
      expect(screen.getByText('photo.png')).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: /menu/i }))
    await user.click(screen.getByText('Delete'))

    expect(screen.getByText(/referenced in your post/i)).toBeInTheDocument()
  })

  it('deletes without confirmation when file is not referenced', async () => {
    mockFetchAssets.mockResolvedValue({
      assets: [{ name: 'unused.png', size: 1024, is_image: true }],
    })
    mockDeleteAsset.mockResolvedValue()
    // After delete, re-fetch returns empty
    mockFetchAssets.mockResolvedValueOnce({
      assets: [{ name: 'unused.png', size: 1024, is_image: true }],
    }).mockResolvedValueOnce({ assets: [] })

    const user = userEvent.setup()
    render(
      createElement(FileStrip, {
        filePath: 'posts/2026-03-08-test/index.md',
        body: 'no references here',
        onBodyChange: vi.fn(),
        onInsertAtCursor: vi.fn(),
        disabled: false,
      }),
    )

    await waitFor(() => {
      expect(screen.getByText(/files \(1\)/i)).toBeInTheDocument()
    })
    await user.click(screen.getByText(/files \(1\)/i))
    await waitFor(() => {
      expect(screen.getByText('unused.png')).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: /menu/i }))
    await user.click(screen.getByText('Delete'))

    // No confirmation dialog — should delete directly
    await waitFor(() => {
      expect(mockDeleteAsset).toHaveBeenCalledWith(
        'posts/2026-03-08-test/index.md',
        'unused.png',
      )
    })
  })
})
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/lukasz/dev/agblogger/frontend && npx vitest run src/components/editor/__tests__/FileStrip.test.tsx`
Expected: FAIL

**Step 3: Implement FileStrip**

Create `frontend/src/components/editor/FileStrip.tsx`:

```tsx
import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronUp, Paperclip, Plus } from 'lucide-react'

import type { AssetInfo } from '@/api/client'
import { fetchPostAssets, deletePostAsset, renamePostAsset, uploadAssets } from '@/api/posts'
import { HTTPError } from '@/api/client'
import FileCard from './FileCard'

interface FileStripProps {
  filePath: string | null
  body: string
  onBodyChange: (body: string) => void
  onInsertAtCursor: (text: string) => void
  disabled: boolean
}

export default function FileStrip({ filePath, body, onBodyChange, onInsertAtCursor, disabled }: FileStripProps) {
  const [assets, setAssets] = useState<AssetInfo[]>([])
  const [expanded, setExpanded] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [operating, setOperating] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const loadAssets = useCallback(async () => {
    if (!filePath) return
    setLoading(true)
    try {
      const resp = await fetchPostAssets(filePath)
      setAssets(resp.assets)
      setError(null)
    } catch {
      setError('Failed to load files')
    } finally {
      setLoading(false)
    }
  }, [filePath])

  useEffect(() => {
    void loadAssets()
  }, [loadAssets])

  if (!filePath) {
    return (
      <div className="mb-4 px-4 py-3 bg-paper border border-border rounded-lg">
        <span className="text-sm text-muted">Save to start adding files</span>
      </div>
    )
  }

  function isReferenced(filename: string): boolean {
    return body.includes(filename)
  }

  async function handleDelete(filename: string) {
    if (isReferenced(filename)) {
      setConfirmDelete(filename)
      return
    }
    await performDelete(filename)
  }

  async function performDelete(filename: string) {
    setOperating(true)
    setConfirmDelete(null)
    try {
      await deletePostAsset(filePath!, filename)
      await loadAssets()
    } catch (err) {
      if (err instanceof HTTPError && err.response.status === 404) {
        setError('File not found')
      } else {
        setError('Failed to delete file')
      }
    } finally {
      setOperating(false)
    }
  }

  async function handleRename(oldName: string, newName: string) {
    setOperating(true)
    try {
      await renamePostAsset(filePath!, oldName, newName)
      // Update markdown references in body
      const updated = body.replaceAll(oldName, newName)
      if (updated !== body) {
        onBodyChange(updated)
      }
      await loadAssets()
    } catch (err) {
      if (err instanceof HTTPError && err.response.status === 409) {
        setError('A file with that name already exists')
      } else {
        setError('Failed to rename file')
      }
    } finally {
      setOperating(false)
    }
  }

  function handleInsert(name: string, isImage: boolean) {
    const markdown = isImage ? `![${name}](${name})` : `[${name}](${name})`
    onInsertAtCursor(markdown)
  }

  async function handleFileUpload(files: FileList | File[]) {
    const fileArray = Array.from(files)
    if (fileArray.length === 0) return

    setOperating(true)
    setError(null)
    try {
      const result = await uploadAssets(filePath!, fileArray)
      const insertions = result.uploaded.map((name) => {
        const ext = name.split('.').pop()?.toLowerCase() ?? ''
        const isImage = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'avif'].includes(ext)
        return isImage ? `![${name}](${name})` : `[${name}](${name})`
      })
      onInsertAtCursor(insertions.join('\n') + '\n\n')
      await loadAssets()
    } catch (err) {
      if (err instanceof HTTPError && err.response.status === 413) {
        setError('File too large. Maximum size is 10 MB.')
      } else {
        setError('Failed to upload file.')
      }
    } finally {
      setOperating(false)
    }
  }

  const isDisabled = disabled || operating

  const headerText = assets.length > 0 ? `Files (${assets.length})` : 'Files'

  return (
    <div className="mb-4 bg-paper border border-border rounded-lg">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-muted hover:text-ink transition-colors"
      >
        <span className="flex items-center gap-2">
          <Paperclip size={14} />
          {headerText}
        </span>
        {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>

      {expanded && (
        <div className="px-4 pb-4">
          {error !== null && (
            <div className="mb-3 text-sm text-red-600 dark:text-red-400">{error}</div>
          )}

          {confirmDelete !== null && (
            <div className="mb-3 flex items-center gap-3 text-sm bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800/40 rounded-lg px-4 py-3">
              <span className="text-red-800 dark:text-red-300">
                This file is referenced in your post. Delete anyway?
              </span>
              <button
                type="button"
                onClick={() => setConfirmDelete(null)}
                className="font-medium text-red-600 dark:text-red-400 hover:underline"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void performDelete(confirmDelete)}
                disabled={isDisabled}
                className="font-medium text-red-700 dark:text-red-300 hover:underline"
              >
                Delete
              </button>
            </div>
          )}

          {loading ? (
            <span className="text-xs text-muted">Loading...</span>
          ) : (
            <div className="flex flex-wrap gap-3">
              {assets.map((asset) => (
                <FileCard
                  key={asset.name}
                  asset={asset}
                  filePath={filePath}
                  onInsert={handleInsert}
                  onDelete={(name) => void handleDelete(name)}
                  onRename={(oldName, newName) => void handleRename(oldName, newName)}
                  disabled={isDisabled}
                />
              ))}

              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                onChange={(e) => {
                  if (e.target.files) {
                    void handleFileUpload(e.target.files)
                  }
                  e.target.value = ''
                }}
              />

              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={isDisabled}
                className="flex flex-col items-center justify-center w-20 h-20 rounded-lg
                         border-2 border-dashed border-border text-muted
                         hover:border-accent hover:text-accent disabled:opacity-50
                         transition-colors"
              >
                <Plus size={20} />
                <span className="text-xs mt-1">Upload</span>
              </button>
            </div>
          )}

          <span className="block mt-2 text-xs text-muted">Max 10 MB per file</span>
        </div>
      )}
    </div>
  )
}
```

**Step 4: Run tests**

Run: `cd /Users/lukasz/dev/agblogger/frontend && npx vitest run src/components/editor/__tests__/FileStrip.test.tsx`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add frontend/src/components/editor/FileStrip.tsx frontend/src/components/editor/__tests__/FileStrip.test.tsx
git commit -m "feat: add FileStrip component"
```

---

### Task 7: Frontend — Save-and-Stay Flow + View Post Button

**Files:**
- Modify: `frontend/src/pages/EditorPage.tsx`
- Modify: `frontend/src/pages/__tests__/EditorPage.test.tsx`

**Step 1: Write failing tests**

Add to `frontend/src/pages/__tests__/EditorPage.test.tsx`:

```tsx
it('stays on editor after saving new post', async () => {
  const mockCreatePost = vi.mocked(createPost)
  const savedPost: PostDetail = {
    id: 1, file_path: 'posts/2026-03-08-my-title/index.md',
    title: 'My Title', author: 'jane', created_at: '2026-03-08 12:00:00+00:00',
    modified_at: '2026-03-08 12:00:00+00:00', is_draft: false,
    rendered_excerpt: '', rendered_html: '<p>Hello</p>', content: 'Hello', labels: [],
  }
  mockCreatePost.mockResolvedValue(savedPost)
  const user = userEvent.setup()
  renderEditor('/editor/new')

  await waitFor(() => {
    expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
  })

  await user.type(screen.getByLabelText(/Title/), 'My Title')
  await user.click(screen.getByRole('button', { name: /save/i }))

  // Should stay on editor, not navigate to post view
  await waitFor(() => {
    expect(screen.getByLabelText(/Title/)).toHaveValue('My Title')
  })
  // The "View post" button should now be visible
  await waitFor(() => {
    expect(screen.getByRole('button', { name: /view post/i })).toBeInTheDocument()
  })
})

it('shows View Post button only after save', async () => {
  renderEditor('/editor/new')

  await waitFor(() => {
    expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
  })

  // No View Post button before save
  expect(screen.queryByRole('button', { name: /view post/i })).not.toBeInTheDocument()
})

it('shows View Post button for existing post', async () => {
  mockFetchPostForEdit.mockResolvedValue(editResponse)
  renderEditor('/editor/posts/existing.md')

  await waitFor(() => {
    expect(screen.getByLabelText(/Title/)).toHaveValue('Existing Post')
  })

  expect(screen.getByRole('button', { name: /view post/i })).toBeInTheDocument()
})
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/lukasz/dev/agblogger/frontend && npx vitest run src/pages/__tests__/EditorPage.test.tsx`
Expected: FAIL (new post navigates away, no View Post button)

**Step 3: Modify EditorPage**

In `EditorPage.tsx`, modify the `handleSave` function to stay on editor:

1. After a successful create, instead of `navigate(`/post/${result.file_path}`)`, do `navigate(`/editor/${result.file_path}`, { replace: true })`.
2. For existing posts (update), don't navigate at all (just stay).
3. Track the effective file path: add state `const [effectiveFilePath, setEffectiveFilePath] = useState<string | null>(isNew ? null : filePath ?? null)`. After create, set it to `result.file_path`. After update, set it to `result.file_path`.
4. Add a "View post" button next to the Save button, visible when `effectiveFilePath` is not null. Clicking it navigates to `/post/${effectiveFilePath}`.
5. If `isDirty` when View Post is clicked, show `window.confirm('You have unsaved changes. Leave without saving?')`. If they confirm, navigate. If not, stay.

The cross-post flow after save should still work: if `selectedPlatforms.length > 0`, show the dialog. After dialog close, stay on editor instead of navigating to post view.

**Step 4: Run tests**

Run: `cd /Users/lukasz/dev/agblogger/frontend && npx vitest run src/pages/__tests__/EditorPage.test.tsx`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add frontend/src/pages/EditorPage.tsx frontend/src/pages/__tests__/EditorPage.test.tsx
git commit -m "feat: save-and-stay flow with View Post button"
```

---

### Task 8: Frontend — Integrate FileStrip into EditorPage

**Files:**
- Modify: `frontend/src/pages/EditorPage.tsx`
- Modify: `frontend/src/pages/__tests__/EditorPage.test.tsx`

**Step 1: Write failing tests**

Add to `frontend/src/pages/__tests__/EditorPage.test.tsx`. Add `fetchPostAssets` to the mock at the top:

```tsx
vi.mock('@/api/posts', () => ({
  fetchPostForEdit: vi.fn(),
  createPost: vi.fn(),
  updatePost: vi.fn(),
  uploadAssets: vi.fn(),
  fetchPostAssets: vi.fn().mockResolvedValue({ assets: [] }),
  deletePostAsset: vi.fn(),
  renamePostAsset: vi.fn(),
}))
```

Then add test:

```tsx
it('shows FileStrip for existing post', async () => {
  mockFetchPostForEdit.mockResolvedValue(editResponse)
  renderEditor('/editor/posts/existing.md')

  await waitFor(() => {
    expect(screen.getByLabelText(/Title/)).toHaveValue('Existing Post')
  })

  // FileStrip header should be visible
  expect(screen.getByText('Files')).toBeInTheDocument()
})

it('shows save-first message for new post FileStrip', async () => {
  renderEditor('/editor/new')

  await waitFor(() => {
    expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
  })

  expect(screen.getByText(/save.*to start adding files/i)).toBeInTheDocument()
})
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/lukasz/dev/agblogger/frontend && npx vitest run src/pages/__tests__/EditorPage.test.tsx`
Expected: FAIL (FileStrip not yet integrated)

**Step 3: Integrate FileStrip into EditorPage**

In `EditorPage.tsx`:

1. Import `FileStrip` from `'@/components/editor/FileStrip'`.
2. Add a `handleInsertAtCursor` callback that inserts text at the textarea cursor position (refactored from the existing upload handler logic).
3. Place `<FileStrip>` between the metadata section and the mobile tabs / split editor. Pass `filePath={effectiveFilePath}`, `body`, `onBodyChange={setBody}`, `onInsertAtCursor`, `disabled={saving || uploading}`.
4. Remove the old standalone upload button section (lines 460-491 that contain the "Upload files" button and hidden file input) since FileStrip now handles uploads.
5. Keep drag-and-drop on the textarea. In `handleDrop`, after upload completes, the FileStrip will auto-refresh via its `loadAssets` effect.

**Step 4: Run tests**

Run: `cd /Users/lukasz/dev/agblogger/frontend && npx vitest run src/pages/__tests__/EditorPage.test.tsx`
Expected: ALL PASS

**Step 5: Run full frontend checks**

Run: `cd /Users/lukasz/dev/agblogger && just check-frontend`
Expected: PASS

**Step 6: Commit**

```bash
git add frontend/src/pages/EditorPage.tsx frontend/src/pages/__tests__/EditorPage.test.tsx
git commit -m "feat: integrate FileStrip into EditorPage"
```

---

### Task 9: End-to-End Verification

**Step 1: Run full check suite**

Run: `cd /Users/lukasz/dev/agblogger && just check`
Expected: ALL PASS

**Step 2: Manual browser test**

Use playwright MCP to verify the flow:
1. Navigate to `/editor/new`, verify FileStrip shows "Save to start adding files"
2. Enter a title and body, save — verify URL updates and FileStrip becomes active
3. Upload a file via FileStrip — verify thumbnail appears and markdown is inserted
4. Rename the file — verify markdown references are updated
5. Delete the file — verify it disappears
6. Click "View post" — verify navigation to post view
7. Edit an existing post — verify FileStrip loads existing assets

**Step 3: Update architecture docs**

Update `docs/arch/frontend.md` to mention the FileStrip component in the editor section.
Update `docs/arch/backend.md` to list the new asset management endpoints.

**Step 4: Commit**

```bash
git add docs/arch/frontend.md docs/arch/backend.md
git commit -m "docs: update arch docs for file management"
```
