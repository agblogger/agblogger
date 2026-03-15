# AgBlogger: Design & Implementation Plan

## 1. Architecture Overview

AgBlogger is a markdown-first blogging platform where markdown files with YAML front matter are the source of truth for all post content and metadata. A lightweight relational database acts as a cache for search/filtering and stores user/auth data. Configuration lives in TOML files. A bidirectional sync mechanism keeps a local directory and the server in lockstep.

```
                    +-----------------------+
                    |   React SPA (Vite)    |
                    |  TypeScript frontend  |
                    +-----------+-----------+
                                |
                           REST API
                                |
                    +-----------+-----------+
                    |  Python / FastAPI     |
                    |  backend server       |
                    +-----------+-----------+
                       |        |        |
              +--------+   +---+---+   +-+----------+
              | Pandoc |   | SQLite|   | Filesystem  |
              | binary |   |  DB   |   | (md, toml,  |
              +--------+   +-------+   |  assets)    |
                                       +-------------+
```

### 1.1 Key Architectural Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Backend language | Python 3.12+ | Best pandoc integration, excellent YAML/TOML libs, mature async (FastAPI) |
| Web framework | FastAPI | Async, fast, OpenAPI docs auto-generated, Pydantic validation |
| Frontend | React + Vite + TypeScript | Fast dev cycle, rich ecosystem for md editing & graph viz |
| Database | SQLite (WAL mode) | Zero-config deployment, FTS5 for search, recursive CTEs for label DAG, single-file backup. PostgreSQL supported as optional upgrade path |
| Markdown rendering | Pandoc (via pypandoc) | Native `$...$` KaTeX math, 140+ syntax-highlighted languages with custom Kate XML definitions, native GFM, Quarto compatibility via Lua filters |
| ORM | SQLAlchemy 2.0 + Alembic | Mature, async support, DB-agnostic, migration management |
| Auth | JWT (access + refresh tokens) | Stateless, works with SPA frontend, python-jose + passlib |
| CSS | TailwindCSS | Utility-first, fast iteration, small production bundles |
| Deployment | Docker (single container) | Pandoc binary + Python + static frontend all in one image |

---

## 2. Technology Stack (Full)

### 2.1 Backend (Python)

| Component | Package | Purpose |
|-----------|---------|---------|
| Framework | `fastapi`, `uvicorn` | Async HTTP server |
| ORM | `sqlalchemy[asyncio]`, `aiosqlite` | Database access |
| Migrations | `alembic` | Schema versioning |
| Markdown | `pypandoc` (calls pandoc binary) | MD -> HTML rendering |
| YAML | `pyyaml`, `python-frontmatter` | Parse YAML front matter |
| TOML | `tomllib` (stdlib 3.11+), `tomli-w` | Read/write TOML config |
| Auth | `python-jose[cryptography]`, `passlib[bcrypt]` | JWT tokens, password hashing |
| Validation | `pydantic` v2 | Request/response models, settings |
| File hashing | `hashlib` (stdlib) | SHA-256 for sync manifests |
| Diff/merge | `merge3` (or `diff-match-patch`) | Three-way text merge for sync conflicts |
| Date/time | `pendulum` | Timezone-aware datetime parsing (lax input, strict output) |
| Task queue | `arq` (Redis-backed) or in-process | Cross-posting job queue |
| Cross-posting | `tweepy`, `atproto`, `Mastodon.py`, `requests` | Platform-specific SDKs |
| Testing | `pytest`, `pytest-asyncio`, `httpx` | Test suite |

### 2.2 Frontend (TypeScript / React)

| Component | Package | Purpose |
|-----------|---------|---------|
| Build tool | Vite | Fast HMR, optimized builds |
| UI framework | React 18+ | Component-based UI |
| Routing | React Router v6 | Client-side navigation |
| Markdown editor | `@uiw/react-md-editor` | WYSIWYG-ish markdown editing |
| Math rendering | KaTeX (client-side for editor preview) | Live math preview in editor |
| Syntax highlighting | Shiki (for editor preview) | Code block highlighting in preview |
| Graph visualization | `@xyflow/react` (React Flow) | Label DAG navigator |
| HTTP client | `ky` or `axios` | API calls |
| State management | Zustand | Lightweight global state |
| Styling | TailwindCSS | Utility CSS |
| Date display | `date-fns` | Date formatting |
| Icons | `lucide-react` | UI icons |

### 2.3 Infrastructure

| Component | Tool | Purpose |
|-----------|------|---------|
| Containerization | Docker, docker-compose | Single-container deployment |
| Reverse proxy | Caddy (optional) | HTTPS termination, static file serving |
| CI/CD | GitHub Actions | Lint, test, build, deploy |

---

## 3. Data Model

### 3.1 Filesystem Layout (Source of Truth)

```
content/                          # Root content directory (configurable)
  index.toml                      # Top-level page config + site preferences
  labels.toml                     # Label definitions
  about.md                        # "About" page (top-level page)
  other-page.md                   # Another top-level page
  posts/                          # Blog posts (any nesting depth)
    2026-02-02-hello-world.md
    cooking/
      best-pasta.md
      images/
        pasta.jpg
    tech/
      swe/
        python-tips.md
      ai/
        llm-overview.md
  assets/                         # Shared assets (images, PDFs, etc.)
    logo.png
    paper.pdf
```

All files in `content/` and subdirectories are synced. Markdown files (`.md`) anywhere under `content/posts/` (recursively) are treated as blog posts. Markdown files directly in `content/` matching entries in `index.toml` are top-level pages.

### 3.2 index.toml (Top-Level Page Configuration)

```toml
[site]
title = "My Blog"
description = "A blog about things"
default_author = "Jane Doe"
timezone = "America/New_York"     # Default timezone for lax datetime input

# Top-level pages. Order determines tab order. First = main page.
# The special id "timeline" refers to the built-in post timeline.
[[pages]]
id = "timeline"
title = "Posts"

[[pages]]
id = "about"
title = "About"
file = "about.md"                 # path relative to content root

[[pages]]
id = "projects"
title = "Projects"
file = "projects.md"
```

### 3.3 labels.toml (Label Definitions)

```toml
[labels]
  [labels.cs]
  names = ["computer science"]

  [labels.swe]
  names = ["software engineering", "programming", "software development"]
  parent = "#cs"

  [labels.ai]
  names = ["artificial intelligence", "machine learning"]
  parent = "#cs"

  [labels.cooking]
  names = ["recipes", "food"]

  [labels.politics]
  names = []
```

Labels can also be defined **implicitly** by referencing `#label-id` in a post's front matter without having an entry in `labels.toml`. The system creates a minimal entry (id only, no names, no parents) on first encounter.

Labels form a DAG. The `parent` field (or `parents` as a list) defines supercategory relationships. Cycles are detected and rejected at parse time.

### 3.4 Blog Post Markdown (YAML Front Matter)

```markdown
---
created_at: 2026-02-02 22:21:29.975359+00
modified_at: 2026-02-02 22:21:35.000000+00
author: Jane Doe
labels: [#swe, #ai]
---
# My Blog Post Title

Blog post content in markdown...

Here is some math: $\alpha + \beta = \gamma$

$$
\int_0^\infty e^{-x^2} dx = \frac{\sqrt{\pi}}{2}
$$

```python
def hello():
    print("Hello, world!")
`` `
```

**Front matter fields:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `created_at` | TIMESTAMPTZ string | Auto-generated | Lax input (e.g., `2026-02-02` or `2026-02-02 22:21`) -> strict output (`YYYY-MM-DD HH:MM:SS.ffffff+TZ`) |
| `modified_at` | TIMESTAMPTZ string | Auto-updated | Same format rules |
| `author` | string | No | Falls back to `site.default_author` in `index.toml` |
| `labels` | list of `#label-id` | No | References to label IDs |
| `draft` | boolean | No | Default `false`. Drafts not shown on timeline unless authenticated |

**Title derivation:** The post title is extracted from the first `# Heading` (single `#` only) in the markdown body. If none exists, the title is derived from the filename (e.g., `hello-world.md` -> "Hello World").

**Directory-based implicit labels:** A post at `posts/cooking/best-pasta.md` implicitly receives the `#cooking` label, in addition to any labels declared in its front matter. Nested directories create label hierarchy: `posts/tech/swe/tips.md` implies `#tech` and `#swe`.

### 3.5 Database Schema (SQLite)

The database stores: (a) user/auth data (authoritative), and (b) cached post/label metadata (regenerated from files).

```sql
-- =====================
-- AUTHORITATIVE TABLES
-- =====================

CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    display_name  TEXT,
    is_admin      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TEXT    NOT NULL,  -- ISO 8601
    updated_at    TEXT    NOT NULL
);

CREATE TABLE refresh_tokens (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT    NOT NULL UNIQUE,
    expires_at TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);

-- Cross-posting OAuth tokens
CREATE TABLE social_accounts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    platform     TEXT    NOT NULL,  -- 'x', 'bluesky', 'mastodon', 'facebook', 'linkedin'
    account_name TEXT,
    credentials  TEXT    NOT NULL,  -- encrypted JSON blob (tokens, secrets)
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL,
    UNIQUE(user_id, platform, account_name)
);

-- Cross-posting history
CREATE TABLE cross_posts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    post_path    TEXT    NOT NULL,  -- relative path to markdown file
    platform     TEXT    NOT NULL,
    platform_id  TEXT,              -- ID on the remote platform
    status       TEXT    NOT NULL DEFAULT 'pending',  -- pending, posted, failed
    posted_at    TEXT,
    error        TEXT,
    created_at   TEXT    NOT NULL
);

-- =====================
-- CACHE TABLES (regenerated from filesystem)
-- =====================

CREATE TABLE posts_cache (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path    TEXT    NOT NULL UNIQUE,  -- relative to content root
    title        TEXT    NOT NULL,
    author       TEXT,
    created_at   TEXT    NOT NULL,         -- from front matter
    modified_at  TEXT    NOT NULL,
    is_draft     BOOLEAN NOT NULL DEFAULT FALSE,
    content_hash TEXT    NOT NULL,         -- SHA-256 for change detection
    excerpt      TEXT,                      -- first ~200 chars of body text
    UNIQUE(file_path)
);

CREATE TABLE labels_cache (
    id     TEXT PRIMARY KEY,               -- e.g., "swe"
    names  TEXT NOT NULL DEFAULT '[]',     -- JSON array of name strings
    is_implicit BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE label_parents_cache (
    label_id  TEXT NOT NULL REFERENCES labels_cache(id),
    parent_id TEXT NOT NULL REFERENCES labels_cache(id),
    PRIMARY KEY (label_id, parent_id),
    CHECK (label_id != parent_id)
);

CREATE TABLE post_labels_cache (
    post_id  INTEGER NOT NULL REFERENCES posts_cache(id) ON DELETE CASCADE,
    label_id TEXT    NOT NULL REFERENCES labels_cache(id),
    source   TEXT    NOT NULL DEFAULT 'frontmatter',  -- 'frontmatter' or 'directory'
    PRIMARY KEY (post_id, label_id)
);

-- Full-text search
CREATE VIRTUAL TABLE posts_fts USING fts5(
    title,
    excerpt,
    content,           -- full markdown body (stripped of front matter)
    content_rowid=id,
    content=posts_cache
);

-- Sync manifest
CREATE TABLE sync_manifest (
    file_path     TEXT    PRIMARY KEY,
    content_hash  TEXT    NOT NULL,
    file_size     INTEGER NOT NULL,
    file_mtime    TEXT    NOT NULL,      -- ISO 8601
    synced_at     TEXT    NOT NULL       -- when last synced
);
```

**Key indexes:**
```sql
CREATE INDEX idx_posts_created_at ON posts_cache(created_at DESC);
CREATE INDEX idx_posts_author ON posts_cache(author);
CREATE INDEX idx_post_labels_label ON post_labels_cache(label_id);
```

---

## 4. Markdown Rendering Pipeline

**Engine: Pandoc** (called via `pypandoc` or `subprocess`)

### 4.1 Rendering Command

```bash
pandoc \
  -f gfm+footnotes+tex_math_dollars+raw_html+fenced_divs+bracketed_spans \
  -t html5 \
  --katex \
  --highlight-style=pygments \
  --syntax-definition=custom-lang.xml \   # for any custom languages
  --lua-filter=callouts.lua \             # custom callout rendering
  --lua-filter=tabsets.lua \              # custom tabset rendering
  --lua-filter=local-links.lua \          # resolve local file links
  --wrap=none \
  input.md
```

### 4.2 Rendering Features

| Feature | Implementation |
|---------|---------------|
| KaTeX math (`$...$`, `$$...$$`) | Pandoc `+tex_math_dollars` + `--katex` flag. Client-side KaTeX CSS/JS loaded on pages with math |
| Syntax highlighting | Pandoc's skylighting (140+ languages). Custom languages via `--syntax-definition` with Kate XML files |
| GFM extensions | `-f gfm+footnotes` enables tables, task lists, strikethrough, autolinks, footnotes |
| Callouts/admonitions | Lua filter processing `::: {.callout-note}` fenced divs |
| Tabsets | Lua filter processing `::: {.tabset}` fenced divs |
| Cross-references | pandoc-crossref filter or custom Lua filter |
| Local links | Lua filter that resolves `[text](./other-post.md)` to platform URLs |
| Inline images | Standard markdown `![alt](path)` with path resolution to served asset URLs |
| Embedded videos | Custom Lua filter or raw HTML passthrough for `<video>` tags. Also support YouTube/Vimeo embeds via URL pattern detection |
| Quarto-like extensions | Fenced divs + Lua filters. Reuse/adapt Quarto's open-source Lua filters where appropriate |

### 4.3 Rendering Pipeline (Python)

```
Input: markdown string (with front matter stripped)
  |
  v
[1] Pre-process: resolve asset paths, expand custom shortcodes
  |
  v
[2] Pandoc: markdown -> HTML (via pypandoc)
  |
  v
[3] Post-process: sanitize HTML, add heading anchors, wrap images in figures
  |
  v
Output: HTML string (stored or served)
```

Rendering happens at **publish time** (when a post is created/edited via web or synced from local), not on every page view. Rendered HTML is cached in the database or filesystem.

### 4.4 Editor Preview

The web editor uses `@uiw/react-md-editor` with client-side rendering for live preview:
- KaTeX for math (client-side, matching pandoc's output)
- Shiki for syntax highlighting (client-side, matching pandoc's theme)
- remark-gfm for GFM tables, task lists, etc.

The preview will be *close* to the final pandoc output but may differ slightly for advanced features (callouts, cross-refs). A "full preview" button triggers server-side pandoc rendering.

---

## 5. Label System (DAG)

### 5.1 Data Structures

Labels form a Directed Acyclic Graph (DAG) where edges point from child to parent (subcategory to supercategory).

**In-memory representation** (loaded from `labels.toml` + implicit labels):
```python
@dataclass
class Label:
    id: str                    # e.g., "swe"
    names: list[str]           # alternative names
    parents: set[str]          # parent label IDs
    children: set[str]         # child label IDs (computed)
    is_implicit: bool          # True if not defined in labels.toml
```

### 5.2 Operations

| Operation | Algorithm |
|-----------|-----------|
| Get all ancestors of a label | BFS/DFS upward through parents. DB: recursive CTE |
| Get all descendants of a label | BFS/DFS downward through children. DB: recursive CTE |
| Get all posts with label (including descendants) | Collect label + all descendants, then query `post_labels_cache` |
| Cycle detection | On label add/edit: attempt topological sort of the full graph. If it fails, the change introduces a cycle and is rejected |
| Label resolution by name | Build a lookup dict `{name -> label_id}` from all labels and their names. Used when the user types a name in the UI |

### 5.3 Recursive CTE Example (SQLite)

```sql
-- Get all descendant label IDs of 'cs' (including 'cs' itself)
WITH RECURSIVE descendants(id) AS (
    SELECT 'cs'
    UNION ALL
    SELECT lp.label_id
    FROM label_parents_cache lp
    JOIN descendants d ON lp.parent_id = d.id
)
SELECT DISTINCT p.*
FROM posts_cache p
JOIN post_labels_cache pl ON p.id = pl.post_id
JOIN descendants d ON pl.label_id = d.id
ORDER BY p.created_at DESC;
```

### 5.4 Graph Visualization (Frontend)

The label graph navigator uses React Flow (`@xyflow/react`):
- Nodes = labels (showing id and primary name)
- Edges = parent-child relationships (directed)
- Auto-layout using dagre or ELK algorithm
- Clicking a node shows all posts with that label (including descendants)
- Supports zoom, pan, and search
- Color-coding by depth or category

---

## 6. Bidirectional Sync

### 6.1 Architecture

Sync uses **hash-based change detection** with **three-way merge** for conflict resolution, inspired by Unison's algorithm.

Both client and server maintain a **sync manifest**: a mapping from file paths to `(SHA-256 hash, mtime, size)` representing the agreed-upon state at the last successful sync.

### 6.2 Sync Protocol

```
Client                                    Server
  |                                          |
  |  1. POST /api/sync/init                  |
  |     {client_manifest}     ---------->    |
  |                                          |  2. Compare client_manifest
  |                                          |     vs server_manifest
  |                                          |     vs server_current_state
  |                           <----------    |
  |  3. Receive sync plan:                   |  3. Return sync plan
  |     - files to upload                    |
  |     - files to download                  |
  |     - conflicts to resolve               |
  |                                          |
  |  4. Upload changed files                 |
  |     POST /api/sync/upload  ---------->   |
  |                                          |
  |  5. Download changed files               |
  |     GET /api/sync/download <----------   |
  |                                          |
  |  6. POST /api/sync/commit                |
  |     {resolution_decisions} ---------->   |
  |                                          |  7. Apply changes atomically
  |                           <----------    |     Update manifest
  |  8. Update local manifest                |     Regenerate DB caches
  |                                          |
```

### 6.3 Change Classification

For each file path across `(client_files UNION server_files UNION manifest_files)`:

| Client vs Manifest | Server vs Manifest | Classification | Action |
|---|---|---|---|
| Same | Same | No change | Skip |
| Changed | Same | Local modification | Push to server |
| Same | Changed | Remote modification | Pull to client |
| Changed | Changed | **Conflict** | Merge (see 6.4) |
| New (not in manifest) | N/A | Local addition | Push to server |
| N/A | New (not in manifest) | Remote addition | Pull to client |
| Deleted | Same | Local deletion | Delete on server |
| Same | Deleted | Remote deletion | Delete on client |
| Deleted | Changed | **Delete/modify conflict** | Keep modified version (data preservation) |
| Changed | Deleted | **Delete/modify conflict** | Keep modified version (data preservation) |

### 6.4 Conflict Resolution

**For markdown files (text):**
1. Split into YAML front matter and markdown body
2. **Front matter**: parse as structured YAML, merge field-by-field:
   - Scalar fields (author, draft): last-writer-wins by `modified_at`
   - Array fields (labels): set union of both sides' additions, set intersection of removals relative to ancestor
   - Timestamps: take the latest `modified_at`; keep earliest `created_at`
3. **Body**: three-way line-based merge using `merge3` library (ancestor, local, remote)
   - If clean merge: accept automatically
   - If overlapping edits: keep server version as primary, report conflict to the client for user review
4. Reassemble merged front matter + merged body

**For TOML config files:**
- Parse both versions and the ancestor
- Merge structurally (key-by-key), similar to YAML front matter merge
- For `labels.toml`: union of label definitions, last-writer-wins on conflicting field values

**For binary files (images, PDFs, etc.):**
- Last-writer-wins by `mtime`
- Loser reported as a conflict to the client for user review

### 6.5 Performance Optimizations

- **mtime+size pre-filter**: Only compute SHA-256 when `mtime` or `size` differ from the manifest entry. This avoids hashing unchanged files.
- **Delta transfer**: For large files, transfer only changed content using chunked upload. For typical blog content (<5MB per file), full file transfer is fine.
- **Parallel upload/download**: Transfer multiple files concurrently.

### 6.6 CLI Sync Client

The sync client is a Python CLI tool (`agblogger-sync`) that can be installed via pip:

```bash
pip install agblogger-sync

# Configure
agblogger-sync init --server https://myblog.example.com --dir ./my-blog

# Sync
agblogger-sync push        # local -> server only
agblogger-sync pull        # server -> local only
agblogger-sync sync        # bidirectional (default)
agblogger-sync status      # show what would change
```

---

## 7. API Design

### 7.1 Endpoints

**Auth:**
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/register` | Create user account |
| POST | `/api/auth/login` | Login, returns JWT access + refresh tokens |
| POST | `/api/auth/refresh` | Refresh access token |
| POST | `/api/auth/logout` | Revoke refresh token |

**Posts:**
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/posts` | List posts (paginated, filterable by label/author/date) |
| GET | `/api/posts/{path}` | Get single post (metadata + rendered HTML) |
| GET | `/api/posts/{path}/raw` | Get raw markdown source |
| POST | `/api/posts` | Create new post (auth required) |
| PUT | `/api/posts/{path}` | Update post (auth required) |
| DELETE | `/api/posts/{path}` | Delete post (auth required) |
| GET | `/api/posts/search?q=...` | Full-text search |

**Labels:**
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/labels` | List all labels |
| GET | `/api/labels/{id}` | Get label details + post count |
| GET | `/api/labels/{id}/posts` | Get posts with this label (including descendants) |
| GET | `/api/labels/graph` | Get full label DAG (nodes + edges) for visualization |
| POST | `/api/labels` | Create/update label (auth required) |
| DELETE | `/api/labels/{id}` | Delete label (auth required) |

**Pages:**
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/pages` | List top-level pages (ordered) |
| GET | `/api/pages/{id}` | Get page content (rendered HTML) |
| PUT | `/api/pages/{id}` | Update page (auth required) |

**Sync:**
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/sync/init` | Start sync session, exchange manifests, get sync plan |
| POST | `/api/sync/upload` | Upload files to server |
| GET | `/api/sync/download/{path}` | Download file from server |
| POST | `/api/sync/commit` | Finalize sync, update manifests, regenerate caches |

**Cross-posting:**
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/crosspost/accounts` | List connected social accounts |
| POST | `/api/crosspost/accounts` | Connect a social account (OAuth flow) |
| DELETE | `/api/crosspost/accounts/{id}` | Disconnect account |
| POST | `/api/crosspost/post` | Cross-post to selected platforms |
| GET | `/api/crosspost/history` | Get cross-posting history for a post |

**Rendering:**
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/render/preview` | Render markdown to HTML (for "full preview" in editor) |

### 7.2 Filtering & Pagination

`GET /api/posts` supports:
```
?page=1&per_page=20
?label=swe                    # filter by label (includes descendants)
?labels=swe,ai                # filter by multiple labels (OR)
?author=Jane+Doe
?from=2026-01-01&to=2026-02-01
?q=search+term                # full-text search
?sort=created_at&order=desc
?draft=true                   # include drafts (auth required)
```

---

## 8. Authentication & Authorization

### 8.1 JWT Token Flow

```
Login (username + password)
  -> Verify password hash (bcrypt via passlib)
  -> Issue access token (short-lived: 15 min) + refresh token (long-lived: 7 days)
  -> Store refresh token hash in DB

API Request
  -> Bearer token in Authorization header
  -> Verify JWT signature + expiration
  -> Extract user_id from claims

Token Refresh
  -> POST refresh token
  -> Verify against DB
  -> Issue new access + refresh tokens
  -> Revoke old refresh token (rotation)
```

### 8.2 Roles

| Role | Capabilities |
|------|-------------|
| Admin | Full access: manage users, posts, labels, config, sync |
| Author | Create/edit/delete own posts, manage own labels |
| Reader | View published posts only (no auth required for public reading) |

Public reading requires no authentication. All write operations require authentication.

---

## 9. Cross-Posting

### 9.1 Plugin Architecture

Each social platform is an independent module implementing a common interface:

```python
class CrossPoster(Protocol):
    platform: str

    async def authenticate(self, credentials: dict) -> bool: ...
    async def post(self, content: CrossPostContent) -> CrossPostResult: ...
    async def validate_credentials(self) -> bool: ...

@dataclass
class CrossPostContent:
    title: str
    excerpt: str           # Platform-appropriate excerpt
    url: str               # Link back to the blog post
    image_url: str | None  # OG image / featured image
    labels: list[str]      # For hashtags
```

### 9.2 Platform Support (Priority Order)

| Platform | Library | Auth | Notes |
|----------|---------|------|-------|
| Bluesky | `atproto` | App password + JWT | Free, open API. 300 char limit. Must manually construct link facets and external embeds |
| Mastodon | `Mastodon.py` | OAuth 2.0 | Free, open API. 500+ chars. Easiest integration |
| X (Twitter) | `tweepy` | OAuth 2.0 | Free tier: 1500 tweets/month. 280 chars. Media upload via v1.1 endpoint |
| LinkedIn | `requests` | OAuth 2.0 | Free but gated (app review required). 3000 chars |
| Facebook | `requests` | OAuth 2.0 | Pages only (no personal profile). Requires app review for production |

### 9.3 Formatting Strategy

Each platform module includes a formatter that tailors content:
- Truncate/rewrite excerpt to fit character limits
- Add relevant hashtags from post labels
- Include link to full post
- Attach featured image where supported
- For Bluesky: manually construct link facets and external embed with OG data

### 9.4 Open Graph Tags

The blog's HTML pages include OG meta tags for link previews:
```html
<meta property="og:title" content="Post Title" />
<meta property="og:description" content="First 200 chars of post..." />
<meta property="og:image" content="https://blog.example.com/assets/post-image.jpg" />
<meta property="og:url" content="https://blog.example.com/posts/my-post" />
<meta property="og:type" content="article" />
<meta property="article:published_time" content="2026-02-02T22:21:29Z" />
<meta name="twitter:card" content="summary_large_image" />
```

---

## 10. Frontend Architecture

### 10.1 Page Structure

```
+--------------------------------------------------+
|  Site Title                          [Login]      |
+--------------------------------------------------+
|  [Posts] [About] [Projects] [...]   <- top tabs   |
+--------------------------------------------------+
|                                                    |
|  Main content area                                 |
|  (timeline / page / post / editor / label graph)   |
|                                                    |
+--------------------------------------------------+
```

### 10.2 Routes

| Route | Component | Description |
|-------|-----------|-------------|
| `/` | Timeline | Default main page (or configured first page) |
| `/page/:id` | PageView | Top-level page rendering |
| `/post/:path` | PostView | Single post view (rendered HTML) |
| `/labels` | LabelGraph | Interactive DAG visualization |
| `/labels/:id` | LabelPosts | Posts for a specific label |
| `/search` | SearchResults | Full-text search results |
| `/editor/new` | PostEditor | Create new post (auth) |
| `/editor/:path` | PostEditor | Edit existing post (auth) |
| `/admin/labels` | LabelManager | CRUD labels (auth) |
| `/admin/crosspost` | CrossPostManager | Manage social accounts, cross-post (auth) |
| `/admin/settings` | Settings | Site settings (auth) |
| `/login` | Login | Authentication form |

### 10.3 Key Components

**Timeline** (`/`):
- Paginated list of posts, sorted by `created_at` descending
- Each card shows: title, author, date, labels (as chips), excerpt
- Filter sidebar: label selector (with autocomplete by name), date range picker, author filter
- Infinite scroll or pagination

**PostView** (`/post/:path`):
- Rendered HTML from server (pandoc output)
- KaTeX CSS loaded for math rendering
- Syntax highlighting CSS loaded for code blocks
- Table of contents sidebar (auto-generated from headings)
- Labels shown as clickable chips
- Edit button (if authenticated)
- Cross-post button (if authenticated)

**PostEditor** (`/editor/*`):
- Split pane: markdown source (left) / live preview (right)
- `@uiw/react-md-editor` for the editing area
- Front matter editor panel (structured fields for date, author, labels)
- Label autocomplete (search by id or any name)
- Image/file upload with drag-and-drop
- "Save draft" and "Publish" buttons
- "Full preview" button (server-side pandoc render)

**LabelGraph** (`/labels`):
- React Flow canvas with dagre auto-layout
- Nodes show label id and primary name
- Edges show parent-child relationships
- Click node -> navigate to `/labels/:id` showing posts
- Search/filter overlay
- Zoom controls

---

## 11. Datetime Handling

### 11.1 Format Specification

**Canonical format (strict output):**
```
YYYY-MM-DD HH:MM:SS.ffffff±TZ
```
Example: `2026-02-02 22:21:29.975359+00`

**Lax input formats accepted** (parsed with `pendulum`):
```
2026-02-02 22:21:29.975359+00     # full
2026-02-02 22:21:29+00             # no microseconds -> .000000
2026-02-02 22:21+00                # no seconds -> :00.000000
2026-02-02 22:21                   # no timezone -> site default TZ
2026-02-02                         # no time -> 00:00:00.000000, site default TZ
```

### 11.2 Rules

- All timestamps stored in front matter use the strict output format after first processing
- Missing timezone defaults to `site.timezone` from `index.toml`
- Missing time components (SS, ffffff) default to zeros
- The parser accepts ISO 8601 variants including `T` separator
- All internal processing uses UTC; display conversion happens in the frontend

---

## 12. Project Structure

```
agblogger/
  PLAN.md
  README.md
  pyproject.toml                    # Python project config (uv/pip)
  alembic.ini                       # Alembic config
  Dockerfile
  docker-compose.yml

  backend/
    __init__.py
    main.py                         # FastAPI app entry point
    config.py                       # Pydantic settings
    database.py                     # SQLAlchemy engine + session

    models/                         # SQLAlchemy ORM models
      __init__.py
      user.py
      post.py
      label.py
      sync.py
      crosspost.py

    schemas/                        # Pydantic request/response schemas
      __init__.py
      auth.py
      post.py
      label.py
      sync.py
      crosspost.py

    api/                            # FastAPI routers
      __init__.py
      auth.py
      posts.py
      labels.py
      pages.py
      sync.py
      crosspost.py
      render.py

    services/                       # Business logic
      __init__.py
      auth_service.py
      post_service.py
      label_service.py
      page_service.py
      sync_service.py
      render_service.py             # Pandoc rendering pipeline
      cache_service.py              # DB cache regeneration
      datetime_service.py           # Lax input / strict output parsing

    crosspost/                      # Cross-posting plugins
      __init__.py
      base.py                       # Protocol/interface
      bluesky.py
      mastodon.py
      twitter.py
      linkedin.py
      facebook.py

    sync/                           # Sync engine
      __init__.py
      manifest.py                   # Manifest generation + comparison
      merger.py                     # Three-way merge logic
      protocol.py                   # Sync protocol handler

    filesystem/                     # Filesystem operations
      __init__.py
      content_manager.py            # Read/write markdown + TOML files
      frontmatter.py                # YAML front matter parser/serializer
      toml_manager.py               # TOML config reader/writer
      watcher.py                    # File change detection

    pandoc/                         # Pandoc integration
      __init__.py
      renderer.py                   # pypandoc wrapper
      filters/                      # Custom Lua filters
        callouts.lua
        tabsets.lua
        local_links.lua
        video_embeds.lua

    migrations/                     # Alembic migrations
      env.py
      versions/

  frontend/
    package.json
    vite.config.ts
    tsconfig.json
    tailwind.config.js
    index.html

    src/
      main.tsx
      App.tsx

      api/                          # API client
        client.ts
        auth.ts
        posts.ts
        labels.ts
        sync.ts

      components/
        layout/
          Header.tsx
          TabNavigation.tsx
          Sidebar.tsx
        posts/
          Timeline.tsx
          PostCard.tsx
          PostView.tsx
          PostEditor.tsx
        labels/
          LabelGraph.tsx
          LabelChip.tsx
          LabelSelector.tsx
        auth/
          LoginForm.tsx
          ProtectedRoute.tsx
        crosspost/
          CrossPostDialog.tsx
          SocialAccountManager.tsx

      pages/
        TimelinePage.tsx
        PostPage.tsx
        EditorPage.tsx
        LabelGraphPage.tsx
        LabelPostsPage.tsx
        SearchPage.tsx
        LoginPage.tsx
        AdminPage.tsx

      stores/
        authStore.ts
        postStore.ts
        labelStore.ts

      hooks/
        useAuth.ts
        usePosts.ts
        useLabels.ts

      styles/
        globals.css
        katex.css                   # KaTeX styles
        code-theme.css              # Syntax highlighting theme

  cli/                              # Sync CLI client
    __init__.py
    main.py                         # CLI entry point (click or typer)
    sync_client.py                  # HTTP client for sync API
    manifest.py                     # Local manifest management
    config.py                       # CLI config (.agblogger.json)

  tests/
    conftest.py
    test_api/
    test_services/
    test_sync/
    test_rendering/
    test_labels/
```

---

## 13. Implementation Phases

> **STATUS (2026-02-17): ALL PHASES COMPLETE.** 92 backend tests + 1 frontend test passing.

### Phase 1: Foundation (MVP) ✅
**Goal: Basic blog with markdown rendering, no sync, no cross-posting**

1. **Project scaffolding**
   - Python project with `pyproject.toml` (uv for dependency management)
   - FastAPI app skeleton with CORS, static file serving
   - SQLite database setup with SQLAlchemy + Alembic
   - Vite + React + TypeScript frontend scaffold
   - Docker setup

2. **Filesystem layer**
   - TOML config parser (`index.toml`, `labels.toml`)
   - YAML front matter parser/serializer
   - Content directory scanner (recursive markdown discovery)
   - Datetime parsing (lax input -> strict output)

3. **Pandoc rendering pipeline**
   - pypandoc integration with GFM + KaTeX + syntax highlighting
   - Basic Lua filters (callouts, local link resolution)
   - Rendered HTML caching

4. **Database cache layer**
   - Schema creation + migrations
   - Cache regeneration from filesystem (posts, labels, post-labels)
   - FTS5 index population

5. **Core API**
   - Post listing with pagination and filtering
   - Single post retrieval (rendered HTML)
   - Label listing and label->posts queries
   - Full-text search
   - Top-level page retrieval

6. **Frontend (read-only)**
   - Tab navigation (configurable top-level pages)
   - Timeline view with post cards
   - Post view with rendered HTML, KaTeX, code highlighting
   - Label chips linking to filtered views
   - Search interface
   - Responsive design

### Phase 2: Authentication & Editing
**Goal: Authenticated users can create/edit/delete posts and labels via the web UI**

7. **Auth system**
   - User registration and login
   - JWT access + refresh token flow
   - Password hashing with bcrypt
   - Protected API endpoints

8. **Post editor**
   - Markdown editor component (`@uiw/react-md-editor`)
   - Front matter editor panel (structured fields)
   - Image/file upload
   - Live preview (client-side) + full preview (server-side pandoc)
   - Save -> writes markdown file + updates DB cache

9. **Label management**
   - CRUD UI for labels
   - DAG cycle detection on parent changes
   - Updates both TOML file and DB cache

### Phase 3: Label Graph & Advanced Navigation
**Goal: Interactive label graph, advanced filtering**

10. **Label graph visualization**
    - React Flow canvas with dagre layout
    - Click-to-navigate
    - Search overlay

11. **Advanced filtering**
    - Multi-label filter (OR / AND modes)
    - Date range picker
    - Author selector
    - Combined filters

### Phase 4: Bidirectional Sync
**Goal: Local directory <-> server sync with conflict resolution**

12. **Sync engine (server)**
    - Manifest generation and comparison
    - Sync plan computation
    - File upload/download endpoints
    - Three-way merge for markdown/TOML
    - Cache regeneration after sync

13. **Sync CLI client**
    - CLI tool (`agblogger-sync`) with init, push, pull, sync, status
    - Local manifest management
    - Conflict reporting and resolution

### Phase 5: Cross-Posting
**Goal: Cross-post blog content to social media platforms**

14. **Cross-posting infrastructure**
    - Social account connection (OAuth flows)
    - Cross-posting interface and formatters
    - Platform modules: Bluesky, Mastodon, X, LinkedIn, Facebook
    - Cross-post history tracking
    - OG meta tags on blog pages

### Phase 6: Polish & Production Readiness

15. **Performance & SEO**
    - Server-side rendered HTML meta tags for SEO
    - Static file caching headers
    - Gzip/Brotli compression
    - Image optimization pipeline

16. **Production deployment**
    - Production Docker image (multi-stage build)
    - Caddy reverse proxy config
    - Backup strategy (SQLite + content directory)
    - Health check endpoint
    - Logging and monitoring

---

## 14. Deployment

### 14.1 Docker (Recommended)

```dockerfile
# Multi-stage build
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
# Install pandoc
RUN apt-get update && apt-get install -y pandoc && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
COPY backend/ ./backend/
COPY --from=frontend-build /app/frontend/dist ./frontend/dist
# Content directory mounted as volume
VOLUME /data/content
VOLUME /data/db
ENV CONTENT_DIR=/data/content
ENV DATABASE_URL=sqlite+aiosqlite:///data/db/agblogger.db
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 14.2 docker-compose.yml

```yaml
version: "3.8"
services:
  agblogger:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./content:/data/content      # Blog content (source of truth)
      - agblogger-db:/data/db        # SQLite database
    environment:
      - SECRET_KEY=${SECRET_KEY}
      - ADMIN_PASSWORD=${ADMIN_PASSWORD}
    restart: unless-stopped

volumes:
  agblogger-db:
```

### 14.3 With Caddy (HTTPS)

```yaml
services:
  agblogger:
    # ... same as above, no port exposure
  caddy:
    image: caddy:2
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy-data:/data
    depends_on:
      - agblogger

# Caddyfile:
# myblog.example.com {
#     reverse_proxy agblogger:8000
# }
```

---

## 15. Testing Strategy

| Layer | Tool | What to test |
|-------|------|-------------|
| Unit (Python) | pytest | Datetime parsing, front matter serializer, label DAG operations, merge algorithm |
| Integration (API) | pytest + httpx | Full API endpoint testing with test database |
| Rendering | pytest | Pandoc output for various markdown inputs (math, code, GFM, callouts) |
| Sync | pytest | Manifest comparison, conflict detection, merge results |
| Frontend | Vitest + React Testing Library | Component rendering, user interactions |
| E2E | Playwright | Full user flows (view timeline, create post, edit, filter, search) |

---

## 16. Key Design Considerations

### 16.1 Why SQLite Over PostgreSQL?

- **Ease of deployment**: Single file, no separate database server, zero configuration
- **Sufficient for use case**: A blogging platform serves relatively low traffic; SQLite handles ~100k reads/sec in WAL mode
- **Full-text search**: FTS5 is excellent, competitive with PostgreSQL's tsvector
- **Recursive CTEs**: Fully supported for label DAG queries
- **Backup**: Copy one file
- **Upgrade path**: SQLAlchemy abstracts the database; switching to PostgreSQL requires only a connection string change and migration replay

### 16.2 Why Pandoc Over Alternatives?

- **KaTeX**: Native `$...$` math delimiters, best handling of `$` ambiguity
- **Quarto compatibility**: Quarto is literally built on pandoc; Lua filters are the extension mechanism
- **Extensibility**: Custom Lua filters (20-50 LOC each) for callouts, tabsets, cross-refs, video embeds
- **Custom syntax highlighting**: Add languages via Kate XML syntax definition files
- **GFM**: Built-in `-f gfm` reader
- **Maturity**: 18+ years of development, handles edge cases other parsers miss
- **Process overhead**: ~100ms per render is irrelevant for publish-time rendering

### 16.3 Why Hash-Based Sync Over Timestamps?

- **Clock-skew immunity**: SHA-256 hashes are deterministic; timestamps depend on synchronized clocks
- **Reliable conflict detection**: If both sides changed a file from the ancestor state, it's always detected
- **mtime as optimization, not truth**: Use mtime+size as a fast pre-filter to skip unchanged files, but rely on hashes for correctness
