# Backend Architecture

## Runtime Shape

The backend is a single FastAPI application that serves three responsibilities:

- the JSON API under `/api`
- the built React single-page application
- selected server-rendered HTML entry responses for metadata-sensitive routes

Application startup initializes the database, content services, git-backed versioning support, authentication state, and the shared markdown renderer before the app begins serving requests.

## Architectural Layers

The backend follows a layered structure:

- **API layer**: request handling, dependency injection, and HTTP translation
- **Service layer**: business logic and orchestration
- **Filesystem/content layer**: markdown and TOML content management
- **Persistence layer**: SQLAlchemy models and regenerable cache tables
- **Rendering layer**: shared server-side markdown rendering

The filesystem remains the source of truth for content. The database exists primarily to support efficient reads, search, and integration state.

## Core Runtime Services

Several long-lived services define the runtime architecture:

- **content management** for canonical files
- **git-backed versioning** for history and merge support
- **shared rendering** for preview and published HTML
- **cache rebuild and indexing** for searchable derived state

Together, these services let the backend translate between durable content files and fast application read paths.

## Rendering Architecture

Markdown rendering is handled by a long-lived Pandoc server process that is started during backend startup and shared across preview, page rendering, post rendering, excerpts, and other HTML-producing paths.

This is an architectural choice, not just an implementation detail:

- rendering stays behind one backend-controlled boundary for sanitization and output consistency
- preview and published rendering use the same core pipeline
- the application avoids paying full Pandoc process startup cost on every render

The backend treats the Pandoc server as runtime infrastructure owned by the application lifecycle rather than as a per-request helper command.

## Write Coordination

Content mutations are serialized through a shared application-level write boundary. This prevents filesystem updates, cache refreshes, and history updates from interleaving across posts, pages, labels, and sync operations.

Architecturally, this favors correctness and consistency over high write concurrency, which matches the project’s self-hosted editorial model.

## API Surface

The API is organized around a small set of concerns:

- content reads and writes
- authentication and account management
- labels and site configuration
- preview and rendering
- sync and cross-posting
- health and operational endpoints

Public read paths are broad for published content, while mutations are concentrated behind authorization boundaries.

## Failure Handling

The backend is designed around graceful degradation:

- canonical content stays on disk even when derived state needs rebuilds
- integrations are isolated behind service boundaries
- internal failures are translated into generic client-facing errors
- startup validates critical runtime prerequisites up front

That reliability model is central to the backend architecture: preserve content, preserve service availability where possible, and keep internal failures from leaking through the HTTP boundary.

## Code Entry Points

- `backend/main.py` is the main runtime entry point.
- `backend/api/` contains the HTTP-facing modules grouped by feature area.
- `backend/services/` contains the orchestration and business-logic layer.
- `backend/filesystem/` contains the canonical content model.
- `backend/pandoc/server.py` manages the long-lived Pandoc server process used by the application.
- `backend/pandoc/renderer.py` exposes the shared markdown-rendering boundary used across backend features.
