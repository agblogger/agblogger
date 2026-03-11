# AgBlogger Architecture Overview

AgBlogger is a self-hosted, markdown-first blogging platform. Markdown files with YAML front matter, plus TOML configuration files under the content directory, are the authoritative source of truth. The backend builds and maintains a regenerable SQLite cache so the application can provide fast reads, search, filtering, and integration features without making the database authoritative for content.

Start here for the system shape, then read only the subsystem documents that are relevant to the task.

## System Shape

The system has four primary architectural parts:

- **Content layer**: markdown posts, pages, labels, and site configuration stored on disk
- **Application layer**: a FastAPI backend that owns API boundaries, rendering, authorization, and content orchestration
- **Presentation layer**: a React single-page app for browsing, editing, and administration
- **Integration layer**: CLI tooling, bidirectional sync, and cross-posting adapters that extend the core content system

The backend serves both the JSON API and the built frontend, so browser clients and automation clients share the same application boundary.

## Repository Structure

The repository is organized around those layers:

```text
agblogger/
├── backend/   FastAPI application, services, content logic, rendering, sync, and integrations
├── frontend/  React SPA for reading, editing, and administration
├── cli/       Operational tooling such as sync and deployment helpers
├── tests/     Backend, frontend, and CLI test suites
└── docs/      Architecture, guidelines, and supporting documentation
```

## What To Read Next

- Read [backend.md](backend.md) for backend, API, rendering, filesystem, or service-layer tasks.
- Read [frontend.md](frontend.md) for SPA, route, state, or browser-session tasks.
- Read [data-flow.md](data-flow.md) when the task touches canonical content flow, cache updates, or read/write behavior across layers.
- Read [formats.md](formats.md) when the task touches markdown front matter, site TOML, label TOML, or the structure of the `content/` tree.
- Read [auth.md](auth.md) and [security.md](security.md) for authentication, authorization, session, validation, or security-sensitive work.
- Read [sync.md](sync.md) for sync protocol, manifest, merge, or CLI sync tasks.
- Read [cross-posting.md](cross-posting.md) for provider integrations, connected accounts, or publication-to-social-platform tasks.
- Read [testing.md](testing.md) when changing tests, validation strategy, or repository quality gates.
- Read [deployment.md](deployment.md) only for packaging, container, runtime topology, or deployment-helper work.

## Canonical Content Formats

The canonical content model lives under `content/`: markdown posts use YAML front matter, `content/index.toml` defines site-wide metadata and top-level pages, and `content/labels.toml` defines the label graph. Read [formats.md](formats.md) when a task depends on those file formats or the shape of the content tree.

## Core Architectural Principles

- **Filesystem-first content**: posts, pages, labels, and site settings are stored as regular files so backups, inspection, and migration remain simple.
- **Derived database state**: the SQLite database accelerates queries and search, is rebuilt from disk on startup, and is refreshed incrementally when writes succeed.
- **Centralized backend policy**: rendering, sanitization, authorization, and write coordination are enforced on the server rather than split across clients.
- **Single mutation boundary**: content-changing operations share coordinated write handling so filesystem updates, cache refreshes, and versioning stay consistent.
- **Extensible integrations**: sync and cross-posting are layered on top of the content model instead of redefining it.

## Key Design Decisions

- **Canonical files over canonical database rows**: the filesystem is the source of truth so content stays inspectable, portable, and easy to back up.
- **SQLite as a derived acceleration layer**: read-heavy features use a cache database, but the system can rebuild that state from canonical files.
- **Directory-backed posts instead of standalone markdown files**: a post can keep its body and related assets together under one content unit.
- **Long-lived Pandoc renderer instead of per-request subprocesses**: markdown rendering runs through a shared Pandoc server process so preview and publish paths use one rendering boundary without paying full process-start cost on every render.
- **Backend-owned mutation flow**: writes, validation, rendering, and authorization stay behind one application boundary instead of being split across clients.
- **Adapters at the edges**: sync, cross-posting, and CLI tooling extend the core content system instead of redefining it.

## Major Subsystems

- **Backend**: request handling, service orchestration, rendering, cache rebuilds, and integration boundaries
- **Frontend**: route-driven SPA that consumes backend APIs and enhances server-rendered content
- **Authentication**: cookie-based browser sessions plus token-based access for automation and CLI workflows
- **Sync**: bidirectional reconciliation between a local content directory and the server-managed content tree
- **Cross-posting**: adapter-based publishing from canonical blog posts to external social platforms
- **Deployment and security**: self-hosted container-oriented runtime with layered security controls

## Common Starting Points

- For backend behavior and request lifecycle, start in `backend/main.py`, then move into `backend/api/` and `backend/services/`.
- For canonical content handling, start in `backend/filesystem/`, then `backend/services/cache_service.py` and `backend/services/post_service.py`.
- For frontend behavior, start in `frontend/src/App.tsx`, then open the relevant page in `frontend/src/pages/`.
- For sync and deployment tooling, start in `cli/` alongside the matching subsystem document.

## Code Entry Points

- `backend/main.py` wires up the application, lifespan, middleware, and shared runtime services.
- `backend/filesystem/` contains the filesystem-backed content model, including markdown front matter and TOML configuration handling.
- `backend/services/` contains the main orchestration logic for content, auth, sync, rendering, and integrations.
- `frontend/src/App.tsx` is the SPA entry point, with route-level UI in `frontend/src/pages/`.
- `cli/` contains the sync and deployment companions that sit on top of the core application architecture.
