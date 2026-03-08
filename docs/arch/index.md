# AgBlogger Architecture overview

AgBlogger is a self-hosted, markdown-first blogging platform. Markdown files with YAML front matter are the authoritative source of truth for all post content and metadata. The SQLite database is a regenerable cache for search and filtering. Configuration lives in TOML files. A bidirectional sync mechanism keeps a local directory and the server in lockstep.

## Directory Structure

```
agblogger/
├── backend/            Python FastAPI backend
│   ├── api/            Route handlers + dependency injection
│   ├── crosspost/      Cross-posting platform plugins
│   ├── filesystem/     Markdown/TOML parsing, content management
│   ├── migrations/     Alembic migration templates
│   ├── models/         SQLAlchemy ORM models
│   ├── pandoc/         Pandoc rendering
│   ├── schemas/        Pydantic request/response schemas
│   ├── services/       Business logic layer
│   ├── config.py       Pydantic settings (from .env)
│   ├── database.py     Async SQLAlchemy engine
│   ├── exceptions.py   Application-level exception types
│   └── main.py         Application factory, middleware, lifespan
├── frontend/           React 19 + TypeScript SPA
│   └── src/
│       ├── api/        HTTP client (ky) + API functions
│       ├── hooks/      Custom React hooks (auto-save, KaTeX, code blocks, heading tracking)
│       ├── stores/     Zustand state management
│       ├── pages/      Route-level page components
│       └── components/ Reusable UI components
├── cli/                CLIs: sync, deployment, dev server, mutation testing, DAST
├── tests/              pytest test suite
├── docs/               Project documentation
├── Dockerfile          Multi-stage Docker build
├── docker-compose.yml  Container orchestration
├── Caddyfile           Reverse proxy (HTTPS)
└── pyproject.toml      Python project config
```

## Tech Stack

- **Backend:** FastAPI + async SQLAlchemy (SQLite/`aiosqlite`), Alembic, Pandoc-based Markdown rendering, JWT+bcrypt auth, and git-based content versioning/sync with semantic front matter merges.
- **Frontend:** React 19 + Vite + TypeScript, TailwindCSS, Zustand, KaTeX, and graph visualization via `@xyflow/react` + Dagre; textarea editor with server-side Pandoc preview.
- **Testing:** Pytest + Vitest for functional tests, mutation testing via mutmut (backend) and StrykerJS (frontend), plus Dockerized OWASP ZAP baseline/full DAST scans driven by `just` commands.
- **Infra/runtime:** Requires Pandoc and git, uses `uv` for Python deps, and supports Docker/Compose with optional Caddy reverse proxy.

## Core Concepts

### Markdown as Source of Truth

The filesystem is the canonical store for all content. The database is entirely regenerable from the files on disk — it is rebuilt on every server startup via `rebuild_cache()`. Post CRUD endpoints also perform incremental cache maintenance for `posts_cache`, `posts_fts`, and `post_labels_cache` so search/filter data stays fresh between full rebuilds.

The `content/` directory is **not version-controlled** (it is in `.gitignore`). On startup, `ensure_content_dir()` in `backend/main.py` backfills a minimal scaffold (`index.toml`, `labels.toml`, `posts/`) whenever entries are missing, even if `content/` already exists.

Example `content/` directory:

```
content/
├── index.toml              Site configuration
├── labels.toml             Label DAG definitions
├── about.md                Top-level page
├── posts/
│   ├── 2026-02-02-hello-world.md        Flat post (legacy)
│   └── 2026-02-20-my-post/              Post-per-directory (new posts)
│       ├── index.md                     Post content
│       ├── photo.png                    Co-located asset
│       └── diagram.svg                  Co-located asset
└── assets/                 Shared assets
```

Posts use YAML front matter:

```yaml
---
title: Post Title
created_at: 2026-02-02 22:21:29.975359+00
modified_at: 2026-02-02 22:21:35.000000+00
author: Admin
author_username: admin
labels: ["#swe"]
---

Content here...
```

- **Title** is stored as a `title` field in YAML front matter. For backward compatibility, if `title` is absent, it is extracted from the first `# Heading` in the body, falling back to filename derivation. During sync, missing titles are backfilled from the first heading (or filename), and any matching leading heading is stripped from the body.
- **Ownership** uses `author_username` as the stable draft owner identifier. The human-readable `author` field remains for display.
- **Labels** are referenced as `#label-id` strings.
- **Timestamps** use strict ISO output format; lax input is accepted via pendulum.
- **Post-per-directory**: New posts created via the web UI are stored as `posts/<date>-<slug>/index.md` with co-located assets. The slug is generated from the title via NFKD unicode normalization → ASCII → lowercase → hyphenated (max 80 chars). Existing flat posts (`posts/hello.md`) continue to work.
- **Directory rename on title change**: When a post's title changes, the directory is renamed to match the new slug. A symlink is created at the old path pointing to the new directory, preserving old URLs.
- **Directories** under `posts/` are for disk organization only — they have no effect on labels or metadata.

### Label DAG

Labels form a Directed Acyclic Graph where edges point from child to parent (subcategory to supercategory). Labels can have **multiple parents**. They are defined in `content/labels.toml`:

```toml
[labels.cs]
names = ["computer science"]

[labels.swe]
names = ["software engineering", "programming"]
parent = "#cs"

[labels.quantum]
names = ["quantum mechanics"]
parents = ["#math", "#physics"]
```

Single parent uses `parent = "#id"`, multiple parents use `parents = ["#id1", "#id2"]`. The TOML parser accepts both forms; the writer intelligently chooses singular vs plural.

**Cycle enforcement** operates at two levels:
- **Cache rebuild / sync** (batch): DFS with back-edge detection in O(V+E). Cycles in `labels.toml` are automatically broken by dropping edges, with warnings returned in the sync response and logged at startup.
- **API (single-edge additions)**: Recursive CTE checks if the proposed parent is already a descendant of the label, returning 409 on cycle.

Descendant queries use recursive CTEs in SQLite, enabling a "show me all posts in #cs including subcategories" pattern. The graph is visualized and editable in the frontend using React Flow with Dagre auto-layout.

### TOML Configuration

`content/index.toml` defines site-level settings (title, timezone, page navigation, and a system-managed `default_author`). `content/labels.toml` defines the label hierarchy. Both are read at startup and on cache rebuild.

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Filesystem as source of truth | Backup by copying files; database is fully regenerable at startup |
| Async throughout | Non-blocking I/O for file serving and database queries |
| SQLite FTS5 for search | Zero-config full-text search with good performance |
| Recursive CTEs for label DAG | SQLite supports them natively; efficient hierarchy traversal |
| Pandoc server mode | Amortizes Haskell startup cost across all renders; no per-request subprocess cost |
| JWT with refresh token rotation | Prevents stolen refresh token reuse |
| SHA-256 based sync | Clock-skew immune, deterministic conflict detection |
| Git-backed content directory | Provides merge base for hybrid sync merge (`git merge-file` for body); full change history at no extra cost |
| Single Docker container | Simplest deployment for a self-hosted blog |

## Comprehensive Architectural Description

- **Backend**: docs/arch/backend.md
- **Frontend**: docs/arch/frontend.md
- **Authentication and authorization**: docs/arch/auth.md
- **Bidirectional sync**: docs/arch/sync.md
- **Cross-posting and post sharing**: docs/arch/cross-posting.md
- **Data flow**: docs/arch/data-flow.md
- **Security**: docs/arch/security.md
- **Testing**: docs/arch/testing.md
- **Deployment**: docs/arch/deployment.md
