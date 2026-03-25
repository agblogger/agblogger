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
- **Persistence layer**: SQLAlchemy models split into durable tables (Alembic-managed) and regenerable cache tables
- **Rendering layer**: shared server-side markdown rendering

The filesystem remains the source of truth for content. The database exists primarily to support efficient reads, search, and integration state.

Within that filesystem model, posts are canonical only when they live at `posts/<slug>/index.md`. Backend content reads, sync normalization, slug resolution, and asset management reject legacy `posts/<slug>.md` flat-file posts.

## Core Runtime Services

Several long-lived services define the runtime architecture:

- **content management** for canonical files
- **git-backed versioning** for history and merge support
- **shared rendering** for preview and published HTML
- **cache rebuild and indexing** for searchable derived state

These services connect durable content files to the application's read paths.

## Rendering Architecture

Markdown rendering is handled by a long-lived Pandoc server process that is started during backend startup and shared across preview, page rendering, post rendering, excerpts, and other HTML-producing paths.

- rendering stays behind one backend-controlled boundary for sanitization and output consistency
- preview and published rendering use the same core pipeline
- clean public post routes and clean post-asset URLs are derived from directory-backed posts only
- the application avoids paying full Pandoc process startup cost on every render

The backend treats the Pandoc server as runtime infrastructure, not a per-request helper command.

## Write Coordination

Content mutations are serialized through a shared application-level write boundary. This prevents filesystem updates, cache refreshes, and history updates from interleaving across posts, pages, labels, and sync operations.

This favors correctness and consistency over high write concurrency.

## Database Schema Management

The database uses two separate declarative bases to distinguish durable state from derived cache state:

- **DurableBase** tables (users, tokens, invites, social accounts, cross-posts) are managed by Alembic migrations. Schema changes are applied programmatically during application startup via `alembic upgrade head`. These tables persist across restarts and upgrades.
- **CacheBase** tables (posts cache, labels cache, label associations, sync manifest) are dropped and recreated on every startup. Their content is rebuilt from the filesystem.

This separation means adding a column to a durable table requires an Alembic migration, while cache table schema changes take effect automatically on the next restart.

## Analytics Integration

The backend integrates with a GoatCounter sidecar container for server-side page view analytics. The analytics service (`backend/services/analytics_service.py`) has three responsibilities:

- **Hit recording**: when a reader fetches a post or page through the API, it fires an async hit to GoatCounter's internal API. Hits are fire-and-forget — network failures are logged but never affect the reader's response. Authenticated users and detected bots are excluded.
- **Stats proxy**: admin dashboard data (total views, per-path hits, referrers, browser/OS breakdowns) is proxied from GoatCounter's stats API through admin-only backend endpoints.
- **Settings management**: analytics-enabled and show-views-on-posts toggles are stored in a durable `analytics_settings` table (Alembic-managed).

Public post view counts are only exposed when the requested slug or canonical post path still resolves to a published post in `posts_cache`. The public analytics endpoint normalizes canonical file paths like `posts/hello/index.md` back to the short `/post/hello` GoatCounter path before looking up hits, and it returns the same `views: null` response for draft, deleted, or non-existent posts to avoid leaking hidden content state.

GoatCounter is treated as a soft dependency — the backend starts and serves content normally when GoatCounter is unavailable. The API token is loaded lazily from a shared Docker volume (`/data/goatcounter/token`).

## API Surface

The API is organized around a small set of concerns:

- content reads and writes
- authentication and account management
- labels and site configuration
- preview and rendering
- sync and cross-posting
- analytics (admin dashboard stats + public view counts)
- health and operational endpoints

Public read paths are broad for published content, while mutations are concentrated behind authorization boundaries.

## Failure Handling

The backend is designed around graceful degradation:

- canonical content stays on disk even when derived state needs rebuilds
- integrations are isolated behind service boundaries
- internal failures are translated into generic client-facing errors
- startup validates critical runtime prerequisites up front

The goal is to preserve content, preserve service availability where possible, and keep internal failures from leaking through the HTTP boundary.

## Code Entry Points

- `backend/main.py` is the main runtime entry point.
- `backend/api/` contains the HTTP-facing modules grouped by feature area.
- `backend/services/` contains the orchestration and business-logic layer.
- `backend/models/` contains SQLAlchemy ORM models for both durable tables (users, tokens, social accounts, cross-posts, analytics settings) and cache tables (posts, labels, sync manifest).
- `backend/schemas/` contains Pydantic request/response schemas that define the API contracts.
- `backend/filesystem/` contains the canonical content model.
- `backend/pandoc/server.py` manages the long-lived Pandoc server process used by the application.
- `backend/pandoc/renderer.py` exposes the shared markdown-rendering boundary used across backend features.
- `backend/migrations/` contains Alembic migration scripts for durable table schema changes.
- `backend/utils/slug.py` provides canonical post path validation and slug extraction used across API, filesystem, sync, and rendering modules.
