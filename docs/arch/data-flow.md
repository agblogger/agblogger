# Data Flow

## Canonical Flow

AgBlogger’s data flow is organized around one rule: content on disk is canonical.

Content-changing operations follow the same high-level pattern:

1. the backend accepts a mutation through the API or sync boundary
2. the filesystem is updated as the durable source of truth
3. derived cache and search state is refreshed
4. read paths serve cached or interpreted views of that canonical content

This gives the application fast reads without moving ownership of content into the database.

## Mutation Paths

The editor, uploads, administrative configuration changes, and sync all converge on the same content model. Different entry points may collect different inputs, but they ultimately update the same on-disk structures and then refresh derived state. That convergence is a core architectural choice because it keeps alternate workflows from creating alternate truth models.

## Read Paths

Published post reads, search, labels, and page views are served through backend-controlled representations rather than direct filesystem exposure. This allows one shared boundary for authorization, rendering policy, sanitization, and asset access.

## Derived Consumers

Several features consume canonical content without becoming authoritative themselves:

- rendered HTML used for publication and preview
- search and filtering data stored in the cache
- metadata used for link previews
- cross-post payloads sent to external platforms

These are all downstream views of the same content system rather than separate content stores.

## Code Entry Points

- `backend/api/posts.py`, `backend/api/pages.py`, and related API modules define the entry points for reads and mutations.
- `backend/filesystem/content_manager.py` owns the canonical on-disk content operations.
- `backend/services/cache_service.py` and `backend/services/post_service.py` expose the main derived read models.
- `backend/pandoc/renderer.py` and related rendering code handle the shared HTML rendering path.
