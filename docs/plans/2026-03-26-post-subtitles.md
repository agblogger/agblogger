# Post Subtitles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional subtitle support for posts, threaded through front matter, database cache, API, and frontend.

**Architecture:** Subtitle is an optional string field (`str | None`) added to every layer following the same pattern as `author`. It flows through front matter parsing → `PostData` → `PostCache` → API schemas → frontend types → UI components.

**Tech Stack:** Python/FastAPI/SQLAlchemy (backend), React/TypeScript (frontend), SQLite FTS5 (search), Vitest (frontend tests), pytest (backend tests).

---

## File Map

**Backend — modify:**
- `backend/filesystem/frontmatter.py` — `RECOGNIZED_FIELDS`, `PostData`, `FrontmatterMetadata`, `parse_post()`, `serialize_post()`
- `backend/models/post.py` — `PostCache` (add column), `PostsFTS` (add column)
- `backend/schemas/post.py` — `PostSummary`, `PostEditResponse`, `PostSave`, `SearchResult`
- `backend/services/post_service.py` — `list_posts()`, `get_post()`, `search_posts()`
- `backend/services/cache_service.py` — `rebuild_cache()`, `ensure_tables()`
- `backend/api/posts.py` — `_FTS_DELETE_SQL`, `_FTS_INSERT_SQL`, `_upsert_post_fts()`, `_delete_post_fts()`, `_build_post_detail()`, `get_post_for_edit()`, `create_post_endpoint()`, `update_post_endpoint()`, `upload_post()`

**Frontend — modify:**
- `frontend/src/api/client.ts` — `PostSummary`, `PostDetail`, `PostEditResponse`, `SearchResult` types
- `frontend/src/api/posts.ts` — `createPost()`, `updatePost()` param types
- `frontend/src/hooks/useEditorAutoSave.ts` — `DraftData` interface
- `frontend/src/pages/EditorPage.tsx` — subtitle state, input field, save payload
- `frontend/src/pages/PostPage.tsx` — subtitle display, `handlePublish` subtitle passthrough
- `frontend/src/components/posts/PostCard.tsx` — conditional subtitle display
- `frontend/src/pages/SearchPage.tsx` — `SearchResultItem` subtitle display
- `frontend/src/components/search/SearchDropdown.tsx` — subtitle display in dropdown results

**Tests — modify:**
- `tests/test_rendering/test_frontmatter.py` — subtitle parse/serialize round-trip tests
- `frontend/src/components/posts/__tests__/PostCard.test.tsx` — subtitle rendering tests
- `frontend/src/pages/__tests__/PostPage.test.tsx` — subtitle display test
- `frontend/src/pages/__tests__/EditorPage.test.tsx` — subtitle in editor test
- `frontend/src/pages/__tests__/SearchPage.test.tsx` — subtitle in search results test

**Docs — modify:**
- `docs/arch/formats.md` — front matter spec

---

### Task 1: Front Matter Parsing — PostData and parse/serialize

**Files:**
- Modify: `backend/filesystem/frontmatter.py:14-23` (RECOGNIZED_FIELDS), `:26-38` (PostData), `:41-47` (FrontmatterMetadata), `:112-180` (parse_post), `:183-199` (serialize_post)
- Test: `tests/test_rendering/test_frontmatter.py`

- [ ] **Step 1: Write failing tests for subtitle parsing and serialization**

Add a new `TestSubtitle` class to `tests/test_rendering/test_frontmatter.py`:

```python
class TestSubtitle:
    def test_subtitle_recognized_field(self) -> None:
        assert "subtitle" in RECOGNIZED_FIELDS

    def test_parse_subtitle_from_frontmatter(self) -> None:
        content = """\
---
title: My Post
subtitle: A deeper look
created_at: 2026-02-02 22:21:29.975359+00
---

Body content.
"""
        post = parse_post(content)
        assert post.subtitle == "A deeper look"

    def test_parse_subtitle_none_when_absent(self) -> None:
        content = """\
---
title: My Post
created_at: 2026-02-02 22:21:29.975359+00
---

Body content.
"""
        post = parse_post(content)
        assert post.subtitle is None

    def test_parse_subtitle_none_when_empty_string(self) -> None:
        content = """\
---
title: My Post
subtitle: ""
created_at: 2026-02-02 22:21:29.975359+00
---

Body content.
"""
        post = parse_post(content)
        assert post.subtitle is None

    def test_parse_subtitle_whitespace_stripped(self) -> None:
        content = """\
---
title: My Post
subtitle: "  Spaces around  "
created_at: 2026-02-02 22:21:29.975359+00
---

Body content.
"""
        post = parse_post(content)
        assert post.subtitle == "Spaces around"

    def test_parse_numeric_subtitle_coerced(self) -> None:
        content = """\
---
title: My Post
subtitle: 42
created_at: 2026-02-02 22:21:29.975359+00
---

Body content.
"""
        post = parse_post(content)
        assert post.subtitle == "42"

    def test_serialize_includes_subtitle_when_present(self) -> None:
        now = now_utc()
        post_data = PostData(
            title="Test",
            subtitle="My subtitle",
            content="Body",
            raw_content="",
            created_at=now,
            modified_at=now,
        )
        result = serialize_post(post_data)
        parsed = frontmatter.loads(result)
        assert parsed["subtitle"] == "My subtitle"

    def test_serialize_omits_subtitle_when_none(self) -> None:
        now = now_utc()
        post_data = PostData(
            title="Test",
            subtitle=None,
            content="Body",
            raw_content="",
            created_at=now,
            modified_at=now,
        )
        result = serialize_post(post_data)
        parsed = frontmatter.loads(result)
        assert "subtitle" not in parsed.metadata

    def test_subtitle_roundtrip(self) -> None:
        now = now_utc()
        original = PostData(
            title="Round Trip",
            subtitle="The subtitle",
            content="Full content here.",
            raw_content="",
            created_at=now,
            modified_at=now,
            author="Admin",
            labels=["swe"],
            is_draft=False,
            file_path="posts/roundtrip/index.md",
        )
        serialized = serialize_post(original)
        reparsed = parse_post(serialized, file_path="posts/roundtrip/index.md")
        assert reparsed.subtitle == "The subtitle"
        assert reparsed.title == "Round Trip"

    def test_subtitle_absent_roundtrip(self) -> None:
        now = now_utc()
        original = PostData(
            title="No Subtitle",
            content="Content.",
            raw_content="",
            created_at=now,
            modified_at=now,
        )
        serialized = serialize_post(original)
        reparsed = parse_post(serialized)
        assert reparsed.subtitle is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend` (or `uv run pytest tests/test_rendering/test_frontmatter.py::TestSubtitle -v`)
Expected: FAIL — `PostData` has no `subtitle` attribute, `subtitle` not in `RECOGNIZED_FIELDS`

- [ ] **Step 3: Implement subtitle in front matter layer**

In `backend/filesystem/frontmatter.py`:

1. Add `"subtitle"` to `RECOGNIZED_FIELDS`:
```python
RECOGNIZED_FIELDS: frozenset[str] = frozenset(
    {
        "title",
        "subtitle",
        "created_at",
        "modified_at",
        "author",
        "labels",
        "draft",
    }
)
```

2. Add `subtitle` field to `PostData` (after `title`):
```python
@dataclass
class PostData:
    """Parsed blog post data."""

    title: str
    content: str
    raw_content: str
    created_at: datetime
    modified_at: datetime
    subtitle: str | None = None
    author: str | None = None
    labels: list[str] = field(default_factory=list)
    is_draft: bool = False
    file_path: str = ""
```

3. Add `subtitle` to `FrontmatterMetadata`:
```python
class FrontmatterMetadata(TypedDict):
    title: str
    created_at: str
    modified_at: str
    subtitle: NotRequired[str]
    author: NotRequired[str]
    labels: NotRequired[list[str]]
    draft: NotRequired[bool]
```

4. Parse `subtitle` in `parse_post()` — add after the author parsing block (before `is_draft`):
```python
    raw_subtitle = post.get("subtitle")
    subtitle: str | None
    if isinstance(raw_subtitle, str):
        subtitle = raw_subtitle.strip() or None
    elif raw_subtitle is not None:
        subtitle = str(raw_subtitle).strip() or None
    else:
        subtitle = None
```

And include it in the return:
```python
    return PostData(
        title=title,
        content=content,
        raw_content=raw_content,
        created_at=created_at,
        modified_at=modified_at,
        subtitle=subtitle,
        author=author,
        labels=labels,
        is_draft=is_draft,
        file_path=file_path,
    )
```

5. Serialize `subtitle` in `serialize_post()` — add immediately after the title line in the metadata dict:
```python
    metadata: FrontmatterMetadata = {
        "title": post_data.title,
        "created_at": format_datetime(post_data.created_at),
        "modified_at": format_datetime(post_data.modified_at),
    }
    if post_data.subtitle:
        metadata["subtitle"] = post_data.subtitle
    if post_data.author:
        metadata["author"] = post_data.author
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_rendering/test_frontmatter.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/filesystem/frontmatter.py tests/test_rendering/test_frontmatter.py
git commit -m "feat: add subtitle to front matter parsing and serialization"
```

---

### Task 2: Database Model — PostCache and FTS

**Files:**
- Modify: `backend/models/post.py:17-55`

- [ ] **Step 1: Add subtitle column to PostCache**

In `backend/models/post.py`, add after the `title` column (line 24):

```python
    title: Mapped[str] = mapped_column(Text, nullable=False)
    subtitle: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 2: Add subtitle column to PostsFTS**

Update the `PostsFTS` class to include `subtitle` between `title` and `content`:

```python
class PostsFTS(CacheBase):
    """Full-text search virtual table for posts.

    Created manually via raw SQL because SQLAlchemy's create_all cannot
    produce the CREATE VIRTUAL TABLE statement required by FTS5.
    """

    __tablename__ = "posts_fts"
    __table_args__ = {"info": {"is_virtual": True}}

    rowid: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    subtitle: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
```

- [ ] **Step 3: Commit**

```bash
git add backend/models/post.py
git commit -m "feat: add subtitle column to PostCache and PostsFTS models"
```

---

### Task 3: Cache Service — rebuild_cache and ensure_tables

**Files:**
- Modify: `backend/services/cache_service.py:43-49` (FTS CREATE), `:110-121` (PostCache insert), `:124-134` (FTS insert), `:162-168` (ensure_tables FTS CREATE)

- [ ] **Step 1: Update FTS table creation in rebuild_cache**

Change the FTS CREATE statement at line 46 to include `subtitle`:

```python
        await session.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5("
                "title, subtitle, content, content='posts_cache', content_rowid='id')"
            )
        )
```

- [ ] **Step 2: Update PostCache creation in rebuild_cache**

Add `subtitle` to the `PostCache(...)` constructor at line 110:

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
                rendered_excerpt=rendered_excerpt,
                rendered_html=rendered_html,
            )
```

- [ ] **Step 3: Update FTS insert in rebuild_cache**

Change the FTS insert at line 125 to include `subtitle`:

```python
            await session.execute(
                text(
                    "INSERT INTO posts_fts(rowid, title, subtitle, content) "
                    "VALUES (:rowid, :title, :subtitle, :content)"
                ),
                {
                    "rowid": post.id,
                    "title": post_data.title,
                    "subtitle": post_data.subtitle or "",
                    "content": post_data.content,
                },
            )
```

- [ ] **Step 4: Update ensure_tables FTS creation**

Change the FTS CREATE statement in `ensure_tables()` at line 163:

```python
    await session.execute(
        text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5("
            "title, subtitle, content, content='posts_cache', content_rowid='id')"
        )
    )
```

- [ ] **Step 5: Commit**

```bash
git add backend/services/cache_service.py
git commit -m "feat: include subtitle in cache rebuild and FTS indexing"
```

---

### Task 4: API Schemas

**Files:**
- Modify: `backend/schemas/post.py:10-98`

- [ ] **Step 1: Add subtitle to PostSummary**

Add after `title` (line 15):

```python
class PostSummary(BaseModel):
    """Post summary for timeline listing."""

    id: int
    file_path: str
    title: str
    subtitle: str | None = None
    author: str | None = None
    created_at: str
    modified_at: str
    is_draft: bool = False
    rendered_excerpt: str | None = None
    labels: list[str] = Field(default_factory=list)
```

`PostDetail` inherits from `PostSummary`, so it gets `subtitle` automatically.

- [ ] **Step 2: Add subtitle to PostEditResponse**

Add after `title` (line 36):

```python
class PostEditResponse(BaseModel):
    """Structured post data for the editor."""

    file_path: str
    title: str
    subtitle: str | None = None
    body: str
    labels: list[str] = Field(default_factory=list)
    is_draft: bool = False
    created_at: str
    modified_at: str
    author: str | None = None
```

- [ ] **Step 3: Add subtitle to PostSave**

Add after the `title` field with validation:

```python
class PostSave(BaseModel):
    """Request body for creating or updating a post."""

    title: str = Field(
        min_length=1,
        max_length=500,
        description="Post title",
    )
    subtitle: str | None = Field(
        default=None,
        max_length=500,
        description="Optional post subtitle",
    )
    body: str = Field(
        min_length=1,
        max_length=500_000,
        description="Markdown body without front matter",
    )
    labels: list[str] = Field(default_factory=list)
    is_draft: bool = False

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, v: str) -> str:
        _ = cls
        return v.strip()

    @field_validator("subtitle", mode="before")
    @classmethod
    def strip_subtitle(cls, v: str | None) -> str | None:
        _ = cls
        if v is None:
            return None
        stripped = v.strip()
        return stripped or None
```

- [ ] **Step 4: Add subtitle to SearchResult**

Add after `title` (line 94):

```python
class SearchResult(BaseModel):
    """Search result item."""

    id: int
    file_path: str
    title: str
    subtitle: str | None = None
    rendered_excerpt: str | None = None
    created_at: str
    rank: float = 0.0
```

- [ ] **Step 5: Commit**

```bash
git add backend/schemas/post.py
git commit -m "feat: add subtitle field to post API schemas"
```

---

### Task 5: Post Service — list_posts, get_post, search_posts

**Files:**
- Modify: `backend/services/post_service.py:213-229` (list_posts summary), `:268-280` (get_post), `:283-320` (search_posts)

- [ ] **Step 1: Add subtitle to PostSummary construction in list_posts**

At line 218, add `subtitle` to the `PostSummary(...)` call:

```python
        summaries.append(
            PostSummary(
                id=post.id,
                file_path=post.file_path,
                title=post.title,
                subtitle=post.subtitle,
                author=display_author,
                created_at=format_iso(post.created_at),
                modified_at=format_iso(post.modified_at),
                is_draft=post.is_draft,
                rendered_excerpt=post.rendered_excerpt,
                labels=labels_map.get(post.id, []),
            )
        )
```

- [ ] **Step 2: Add subtitle to PostDetail construction in get_post**

At line 268, add `subtitle`:

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
        content=None,
    )
```

- [ ] **Step 3: Add subtitle to search_posts**

Update the SQL query at line 291 to also select `subtitle`:

```python
    stmt = text("""
        SELECT p.id, p.file_path, p.title, p.subtitle, p.rendered_excerpt, p.created_at,
               rank
        FROM posts_fts fts
        JOIN posts_cache p ON fts.rowid = p.id
        WHERE posts_fts MATCH :query
        AND p.is_draft = 0
        ORDER BY rank
        LIMIT :limit
    """)
```

Update the result mapping (column indices shift by 1 after title):

```python
    for r in rows:
        created_at_val = r[5]
        if isinstance(created_at_val, datetime):
            created_at_str = format_iso(created_at_val)
        else:
            created_at_str = str(created_at_val)
        results.append(
            SearchResult(
                id=r[0],
                file_path=r[1],
                title=r[2],
                subtitle=r[3],
                rendered_excerpt=r[4],
                created_at=created_at_str,
                rank=float(r[6]) if r[6] else 0.0,
            )
        )
```

- [ ] **Step 4: Commit**

```bash
git add backend/services/post_service.py
git commit -m "feat: pass subtitle through post service queries"
```

---

### Task 6: API Endpoints — posts.py

**Files:**
- Modify: `backend/api/posts.py:75-82` (FTS SQL), `:107-125` (_upsert_post_fts), `:128-146` (_delete_post_fts), `:164-191` (_build_post_detail), `:357-376` (upload PostCache+FTS), `:409-428` (get_post_for_edit), `:789-825` (create_post_endpoint), `:899-978` (update_post_endpoint)

- [ ] **Step 1: Update FTS SQL templates**

Change the SQL constants at line 75:

```python
_FTS_DELETE_SQL = text(
    "INSERT INTO posts_fts(posts_fts, rowid, title, subtitle, content) "
    "VALUES ('delete', :rowid, :title, :subtitle, :content)"
)

_FTS_INSERT_SQL = text(
    "INSERT INTO posts_fts(rowid, title, subtitle, content) "
    "VALUES (:rowid, :title, :subtitle, :content)"
)
```

- [ ] **Step 2: Update _upsert_post_fts signature and body**

Add `subtitle` parameter:

```python
async def _upsert_post_fts(
    session: AsyncSession,
    *,
    post_id: int,
    title: str,
    subtitle: str,
    content: str,
    old_title: str | None = None,
    old_subtitle: str | None = None,
    old_content: str | None = None,
) -> None:
    """Keep the full-text index row in sync with post cache mutations."""
    if old_title is not None and old_content is not None:
        await session.execute(
            _FTS_DELETE_SQL,
            {"rowid": post_id, "title": old_title, "subtitle": old_subtitle or "", "content": old_content},
        )
    await session.execute(
        _FTS_INSERT_SQL,
        {"rowid": post_id, "title": title, "subtitle": subtitle, "content": content},
    )
```

- [ ] **Step 3: Update _delete_post_fts signature and body**

Add `subtitle` parameter:

```python
async def _delete_post_fts(
    session: AsyncSession, *, post_id: int, title: str, subtitle: str, content: str
) -> None:
    try:
        await session.execute(
            _FTS_DELETE_SQL,
            {"rowid": post_id, "title": title, "subtitle": subtitle, "content": content},
        )
    except OperationalError as exc:
        logger.warning(
            "FTS delete failed for post %d (will be cleaned up on next cache rebuild): %s",
            post_id,
            exc,
        )
```

- [ ] **Step 4: Update _build_post_detail to include subtitle**

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
        labels=labels,
        rendered_html=rendered_html,
        warnings=warnings or [],
    )
```

- [ ] **Step 5: Update get_post_for_edit to include subtitle**

```python
    return PostEditResponse(
        file_path=file_path,
        title=post_data.title,
        subtitle=post_data.subtitle,
        body=post_data.content,
        labels=post_data.labels,
        is_draft=post_data.is_draft,
        created_at=format_iso(post_data.created_at),
        modified_at=format_iso(post_data.modified_at),
        author=post_data.author,
    )
```

- [ ] **Step 6: Update create_post_endpoint**

Add `subtitle` to `PostData` construction:

```python
        post_data = PostData(
            title=body.title,
            subtitle=body.subtitle,
            content=body.body,
            raw_content="",
            created_at=now,
            modified_at=now,
            author=author,
            labels=body.labels,
            is_draft=body.is_draft,
            file_path=file_path,
        )
```

Add `subtitle` to `PostCache` construction:

```python
        post = PostCache(
            file_path=file_path,
            title=post_data.title,
            subtitle=post_data.subtitle,
            author=post_data.author,
            created_at=post_data.created_at,
            modified_at=post_data.modified_at,
            is_draft=post_data.is_draft,
            content_hash=hash_content(serialized),
            rendered_excerpt=rendered_excerpt,
            rendered_html=rendered_html,
        )
```

Add `subtitle` to `_upsert_post_fts` call:

```python
            await _upsert_post_fts(
                session,
                post_id=post.id,
                title=post_data.title,
                subtitle=post_data.subtitle or "",
                content=post_data.content,
            )
```

- [ ] **Step 7: Update update_post_endpoint**

Add `subtitle` to `PostData` construction:

```python
        post_data = PostData(
            title=title,
            subtitle=body.subtitle,
            content=body.body,
            raw_content="",
            created_at=created_at,
            modified_at=now,
            author=author,
            labels=body.labels,
            is_draft=body.is_draft,
            file_path=file_path,
        )
```

Save the previous subtitle for FTS delete (after `previous_content` around line 960):

```python
        previous_title = existing.title
        previous_subtitle = existing.subtitle or ""
        previous_content = existing_post_data.content if existing_post_data else ""
```

Update the `existing` cache row:

```python
        existing.title = title
        existing.subtitle = body.subtitle
        existing.author = author
```

Update the `_upsert_post_fts` call:

```python
        await _upsert_post_fts(
            session,
            post_id=existing.id,
            title=title,
            subtitle=body.subtitle or "",
            content=post_data.content,
            old_title=previous_title,
            old_subtitle=previous_subtitle,
            old_content=previous_content,
        )
```

- [ ] **Step 8: Update upload_post endpoint**

Add `subtitle` to the `PostCache(...)` constructor in the upload handler (around line 357):

```python
            post = PostCache(
                file_path=file_path,
                title=post_data.title,
                subtitle=post_data.subtitle,
                author=post_data.author,
                ...
            )
```

Add `subtitle` to the `_upsert_post_fts` call:

```python
            await _upsert_post_fts(
                session,
                post_id=post.id,
                title=post_data.title,
                subtitle=post_data.subtitle or "",
                content=post_data.content,
            )
```

- [ ] **Step 9: Update all _delete_post_fts calls**

Search for `_delete_post_fts` calls and add the `subtitle` parameter. There is a call in the delete endpoint — add `subtitle=post.subtitle or ""`.

- [ ] **Step 10: Commit**

```bash
git add backend/api/posts.py
git commit -m "feat: thread subtitle through all post API endpoints and FTS operations"
```

---

### Task 7: Backend Integration Tests

**Files:**
- Test: `tests/test_rendering/test_frontmatter.py` (already done in Task 1)

Since backend integration tests require a running server + database, verify the subtitle field works end-to-end by running the existing test suite to confirm no regressions:

- [ ] **Step 1: Run full backend tests**

Run: `just test-backend`
Expected: All PASS — existing tests pass, new subtitle tests from Task 1 pass.

- [ ] **Step 2: Run full static checks**

Run: `just check-backend`
Expected: All PASS — no type errors from the new `subtitle` field.

---

### Task 8: Frontend Types

**Files:**
- Modify: `frontend/src/api/client.ts:135-249`
- Modify: `frontend/src/api/posts.ts:54-68`
- Modify: `frontend/src/hooks/useEditorAutoSave.ts:13-20`

- [ ] **Step 1: Add subtitle to TypeScript types in client.ts**

Add `subtitle` to `PostSummary` (after `title`):
```typescript
export interface PostSummary {
  id: number
  file_path: string
  title: string
  subtitle: string | null
  author: string | null
  created_at: string
  modified_at: string
  is_draft: boolean
  rendered_excerpt: string | null
  labels: string[]
}
```

`PostDetail` extends `PostSummary`, so it gets `subtitle` automatically.

Add `subtitle` to `PostEditResponse` (after `title`):
```typescript
export interface PostEditResponse {
  file_path: string
  title: string
  subtitle: string | null
  body: string
  labels: string[]
  is_draft: boolean
  created_at: string
  modified_at: string
  author: string | null
}
```

Add `subtitle` to `SearchResult` (after `title`):
```typescript
export interface SearchResult {
  id: number
  file_path: string
  title: string
  subtitle: string | null
  rendered_excerpt: string | null
  created_at: string
  rank: number
}
```

- [ ] **Step 2: Add subtitle to createPost and updatePost params**

In `frontend/src/api/posts.ts`, update the param types:

```typescript
export async function createPost(params: {
  title: string
  subtitle: string | null
  body: string
  labels: string[]
  is_draft: boolean
}): Promise<PostDetail> {
  return api.post('posts', { json: params }).json<PostDetail>()
}

export async function updatePost(
  filePath: string,
  params: { title: string; subtitle: string | null; body: string; labels: string[]; is_draft: boolean },
): Promise<PostDetail> {
  return api.put(`posts/${filePath}`, { json: params }).json<PostDetail>()
}
```

- [ ] **Step 3: Add subtitle to DraftData**

In `frontend/src/hooks/useEditorAutoSave.ts`, add to the `DraftData` interface:

```typescript
export interface DraftData {
  title: string
  subtitle: string
  body: string
  labels: string[]
  isDraft: boolean
  savedAt?: string
  _v?: number
}
```

Also bump `DRAFT_SCHEMA_VERSION` to `2` so stale drafts without `subtitle` are ignored:

```typescript
export const DRAFT_SCHEMA_VERSION = 2
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/api/posts.ts frontend/src/hooks/useEditorAutoSave.ts
git commit -m "feat: add subtitle to frontend TypeScript types"
```

---

### Task 9: Editor Page — subtitle state and input

**Files:**
- Modify: `frontend/src/pages/EditorPage.tsx`
- Test: `frontend/src/pages/__tests__/EditorPage.test.tsx`

- [ ] **Step 1: Write failing test for subtitle in editor**

Add to `EditorPage.test.tsx`, in the existing describe block. Find or add a test that checks subtitle input appears and is included in save:

```typescript
  it('renders subtitle input and includes it in save', async () => {
    const user = userEvent.setup()
    const mockPostDetail: PostDetail = {
      id: 1,
      file_path: 'posts/test/index.md',
      title: 'Test',
      subtitle: null,
      author: 'admin',
      created_at: '2026-02-01T12:00:00Z',
      modified_at: '2026-02-01T12:00:00Z',
      is_draft: false,
      rendered_excerpt: null,
      rendered_html: '<p>Body</p>',
      labels: [],
      content: null,
    }
    vi.mocked(createPost).mockResolvedValue(mockPostDetail)
    vi.mocked(fetchSocialAccounts).mockResolvedValue([])
    renderEditor()

    const subtitleInput = screen.getByPlaceholderText('Subtitle')
    expect(subtitleInput).toBeInTheDocument()
    await user.type(subtitleInput, 'My subtitle')

    // Fill required fields
    const titleInput = screen.getByPlaceholderText('Post title')
    await user.type(titleInput, 'Test Title')
    const bodyTextarea = screen.getByPlaceholderText('Write your post in markdown...')
    await user.type(bodyTextarea, 'Body text')

    // Save
    await user.click(screen.getByText('Save'))

    await waitFor(() => {
      expect(createPost).toHaveBeenCalledWith(
        expect.objectContaining({ subtitle: 'My subtitle' }),
      )
    })
  })
```

- [ ] **Step 2: Run test to verify it fails**

Run: `just test-frontend` (or the specific test file)
Expected: FAIL — no subtitle input in editor

- [ ] **Step 3: Add subtitle state and input to EditorPage**

In `EditorPage.tsx`:

Add state (after `const [title, setTitle]`):
```typescript
  const [subtitle, setSubtitle] = useState('')
```

Update `currentState` memo to include subtitle:
```typescript
  const currentState = useMemo<DraftData>(
    () => ({ title, subtitle, body, labels, isDraft }),
    [title, subtitle, body, labels, isDraft],
  )
```

Update `handleRestore` to include subtitle:
```typescript
  const handleRestore = useCallback((draft: DraftData) => {
    setTitle(draft.title)
    setSubtitle(draft.subtitle)
    setBody(draft.body)
    setLabels(draft.labels)
    setIsDraft(draft.isDraft)
  }, [])
```

Update the `fetchPostForEdit` load (around line 103):
```typescript
          setTitle(data.title)
          setSubtitle(data.subtitle ?? '')
          setBody(data.body)
```

Update `handleSave` to include subtitle in the payload:
```typescript
      if (isNew) {
        result = await createPost({ title, subtitle: subtitle.trim() || null, body, labels, is_draft: isDraft })
      } else {
        result = await updatePost(filePath, { title, subtitle: subtitle.trim() || null, body, labels, is_draft: isDraft })
      }
```

Update `handlePublish` in `PostPage.tsx` to pass subtitle:
```typescript
      const updated = await updatePost(post.file_path, {
        title: editData.title,
        subtitle: editData.subtitle,
        body: editData.body,
        labels: editData.labels,
        is_draft: false,
      })
```

Add the subtitle input field in the JSX — between the title input `</div>` (line 408) and the labels `<div>` (line 410):

```tsx
        <div>
          <input
            id="subtitle"
            type="text"
            value={subtitle}
            onChange={(e) => setSubtitle(e.target.value)}
            disabled={saving}
            maxLength={500}
            placeholder="Subtitle"
            className="w-full px-3 py-2 bg-paper-warm border border-border rounded-lg
                     text-ink text-sm
                     focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                     disabled:opacity-50"
          />
        </div>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-frontend`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/EditorPage.tsx frontend/src/pages/PostPage.tsx frontend/src/pages/__tests__/EditorPage.test.tsx
git commit -m "feat: add subtitle input to editor and include in save payload"
```

---

### Task 10: Post Detail Page — subtitle display

**Files:**
- Modify: `frontend/src/pages/PostPage.tsx:148-151`
- Test: `frontend/src/pages/__tests__/PostPage.test.tsx`

- [ ] **Step 1: Write failing test for subtitle on post page**

Add to `PostPage.test.tsx`. First, update the mock post factory to include `subtitle: null` by default, then add a test:

```typescript
  it('displays subtitle when present', async () => {
    vi.mocked(fetchPost).mockResolvedValue({
      ...mockPost,
      subtitle: 'A deeper look at the topic',
    })
    renderPost()
    await waitFor(() => {
      expect(screen.getByText('A deeper look at the topic')).toBeInTheDocument()
    })
  })

  it('does not render subtitle element when null', async () => {
    vi.mocked(fetchPost).mockResolvedValue({ ...mockPost, subtitle: null })
    renderPost()
    await waitFor(() => {
      expect(screen.getByText(mockPost.title)).toBeInTheDocument()
    })
    expect(screen.queryByTestId('post-subtitle')).not.toBeInTheDocument()
  })
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — subtitle not rendered

- [ ] **Step 3: Add subtitle display to PostPage**

In `PostPage.tsx`, add after the `<h1>` title (line 151):

```tsx
        <h1 className="font-display text-4xl md:text-5xl text-ink leading-tight tracking-tight">
          {post.title}
        </h1>

        {post.subtitle != null && (
          <p data-testid="post-subtitle" className="font-display text-xl md:text-2xl text-ink/70 mt-2 leading-snug">
            {post.subtitle}
          </p>
        )}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-frontend`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/PostPage.tsx frontend/src/pages/__tests__/PostPage.test.tsx
git commit -m "feat: display subtitle on post detail page"
```

---

### Task 11: Post Card — subtitle display

**Files:**
- Modify: `frontend/src/components/posts/PostCard.tsx:28-30`
- Test: `frontend/src/components/posts/__tests__/PostCard.test.tsx`

- [ ] **Step 1: Write failing tests for subtitle in PostCard**

Update `makePost` to include `subtitle: null` by default, then add tests:

```typescript
  it('renders subtitle when present', () => {
    renderCard(makePost({ subtitle: 'Card subtitle' }))
    expect(screen.getByText('Card subtitle')).toBeInTheDocument()
  })

  it('does not render subtitle when null', () => {
    renderCard(makePost({ subtitle: null }))
    expect(screen.queryByTestId('card-subtitle')).not.toBeInTheDocument()
  })
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — subtitle not rendered

- [ ] **Step 3: Add subtitle to PostCard**

In `PostCard.tsx`, add after the `<h2>` title (line 29):

```tsx
          <h2 className="font-display text-xl text-ink group-hover:text-accent transition-colors leading-snug">
            {post.title}
          </h2>

          {post.subtitle != null && (
            <p data-testid="card-subtitle" className="text-base text-ink/60 mt-1 leading-snug">
              {post.subtitle}
            </p>
          )}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-frontend`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/posts/PostCard.tsx frontend/src/components/posts/__tests__/PostCard.test.tsx
git commit -m "feat: display subtitle in post cards"
```

---

### Task 12: Search Results — subtitle display

**Files:**
- Modify: `frontend/src/pages/SearchPage.tsx:124-147` (SearchResultItem)
- Modify: `frontend/src/components/search/SearchDropdown.tsx:79-86`
- Test: `frontend/src/pages/__tests__/SearchPage.test.tsx`

- [ ] **Step 1: Write failing test for subtitle in search results**

Update `mockResults` in `SearchPage.test.tsx` to include `subtitle`:

```typescript
const mockResults: SearchResult[] = [
  { id: 1, file_path: 'posts/hello/index.md', title: 'Hello World', subtitle: 'A first subtitle', rendered_excerpt: '<p>A first post</p>', created_at: '2026-02-01 12:00:00+00:00', rank: 1.0 },
  { id: 2, file_path: 'posts/react/index.md', title: 'React Guide', subtitle: null, rendered_excerpt: '<p>Learn React</p>', created_at: '2026-02-02 12:00:00+00:00', rank: 0.9 },
]
```

Add a test:

```typescript
  it('displays subtitle in search results when present', async () => {
    mockSearchPosts.mockResolvedValue(mockResults)
    renderSearch('hello')

    await waitFor(() => {
      expect(screen.getByText('A first subtitle')).toBeInTheDocument()
    })
  })
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — subtitle not rendered in search results

- [ ] **Step 3: Add subtitle to SearchResultItem**

In `SearchPage.tsx`, update `SearchResultItem` (after the `<h3>` title):

```tsx
      <h3 className="font-display text-lg text-ink">{result.title}</h3>
      {result.subtitle != null && (
        <p className="text-sm text-ink/60 mt-0.5">{result.subtitle}</p>
      )}
```

- [ ] **Step 4: Add subtitle to SearchDropdown**

In `SearchDropdown.tsx`, update the result rendering (after the title div at line 79):

```tsx
              <div className="text-sm font-medium text-ink truncate">
                {segments.map((seg, j) =>
                  seg.match ? <mark key={j}>{seg.text}</mark> : seg.text,
                )}
              </div>
              {result.subtitle != null && (
                <div className="text-xs text-ink/60 truncate">{result.subtitle}</div>
              )}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `just test-frontend`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/SearchPage.tsx frontend/src/components/search/SearchDropdown.tsx frontend/src/pages/__tests__/SearchPage.test.tsx
git commit -m "feat: display subtitle in search results and dropdown"
```

---

### Task 13: Documentation

**Files:**
- Modify: `docs/arch/formats.md:33-54`

- [ ] **Step 1: Update front matter spec in formats.md**

Add `subtitle` to the example and field list. Update the example block:

```md
---
title: Example Post
subtitle: A deeper look at the topic
created_at: 2026-03-01 12:00:00.000000+0000
modified_at: 2026-03-01 12:00:00.000000+0000
author: admin
labels:
  - "#architecture"
draft: false
---
```

Add to the field meanings list (after `title`):

```
- `subtitle`: optional short description displayed below the title; omitted from front matter when absent
```

- [ ] **Step 2: Commit**

```bash
git add docs/arch/formats.md
git commit -m "docs: add subtitle to front matter spec in formats.md"
```

---

### Task 14: Final Verification

- [ ] **Step 1: Run full check**

Run: `just check`
Expected: All static checks and tests PASS.

- [ ] **Step 2: Commit any remaining fixes**

If any checks fail, fix and commit.
