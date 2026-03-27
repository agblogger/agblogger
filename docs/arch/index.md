# AgBlogger Architecture Overview

AgBlogger is a self-hosted, markdown-first blogging platform. Markdown files with YAML front matter, plus TOML configuration files under the content directory, are the authoritative source of truth. The backend builds and maintains a regenerable SQLite cache so the application can provide fast reads, search, filtering, and integration features without making the database authoritative for content.

Start here for the system shape, then read only the subsystem documents that are relevant to the task.

## System Shape

The system has four primary architectural parts:

- **Content layer**: canonical content under `content/` — markdown posts with YAML front matter and TOML site metadata
- **Application layer**: a FastAPI backend that owns API boundaries, rendering, authorization, and content orchestration
- **Presentation layer**: a React single-page app for browsing, editing, and administration
- **Integration layer**: CLI tooling, bidirectional sync, and cross-posting adapters that extend the core content system

The backend serves both the JSON API and the built frontend, so browser clients and automation clients share the same application boundary.

## Architecture and Design Decisions

- **Filesystem is the source of truth**: posts, pages, labels, and site settings are stored as regular files so content stays inspectable, portable, and easy to back up. Posts use directory-backed content units so a post's body and related assets live together.
- **SQLite as a derived cache**: the database accelerates queries and search but is rebuilt from canonical files on startup and refreshed incrementally on writes. The database also holds durable state that has no filesystem backing: admin account and credentials, auth tokens (refresh tokens), connected social accounts (encrypted OAuth credentials), and cross-post history.
- **Backend-owned mutation boundary**: rendering, sanitization, authorization, and write coordination are enforced on the server. Content-changing operations share coordinated write handling so filesystem updates, cache refreshes, and versioning stay consistent.
- **Long-lived Pandoc renderer**: markdown rendering runs through a shared Pandoc server process rather than spawning per-request subprocesses.
- **Adapters at the edges**: sync, cross-posting, and CLI tooling extend the core content model instead of redefining it.
- **Deployment and security**: self-hosted container-oriented runtime with layered security controls

## What To Read Next

- Read [backend.md](backend.md) for backend, API, rendering, filesystem, or service-layer tasks.
- Read [frontend.md](frontend.md) for SPA, route, state, or browser-session tasks.
- Read [data-flow.md](data-flow.md) when the task touches canonical content flow, cache updates, or read/write behavior across layers.
- Read [formats.md](formats.md) when the task touches markdown front matter, site TOML, label TOML, or the structure of the `content/` tree.
- Read [auth.md](auth.md) and [security.md](security.md) for authentication, authorization, session, validation, or security-sensitive work.
- Read [sync.md](sync.md) for sync protocol, manifest, merge, or CLI sync tasks.
- Read [cross-posting.md](cross-posting.md) for provider integrations, connected accounts, or publication-to-social-platform tasks.
- Read [analytics.md](analytics.md) for page-view tracking, GoatCounter sidecar, stats proxy, or view-count tasks.
- Read [testing.md](testing.md) when changing tests, validation strategy, or repository quality gates.
- Read [deployment.md](deployment.md) only for packaging, container, runtime topology, or deployment-helper work.

## Code Entry Points

- `backend/main.py` wires up the application, lifespan, middleware, and shared runtime services.
- `backend/filesystem/` contains the filesystem-backed content model, including markdown front matter and TOML configuration handling.
- `backend/services/` contains the main orchestration logic for content, auth, sync, rendering, and integrations.
- `frontend/src/App.tsx` is the SPA entry point, with route-level UI in `frontend/src/pages/`.
- `cli/` contains the sync and deployment companions that sit on top of the core application architecture.
