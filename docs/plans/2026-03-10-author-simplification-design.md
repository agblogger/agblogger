# Author Simplification Design

## Problem

Posts store two author fields in YAML front matter: `author` (display name) and `author_username` (stable username). This creates unnecessary complexity — a `sync_default_author_from_admin()` startup routine, a `post_owner_service` for resolving ownership, and an `update_user_display_name()` service that retroactively rewrites all post files when a display name changes. Since usernames are immutable and display names live in the users table, the dual-field pattern is redundant.

## Design

### Front matter

`author` stores the username (e.g., `author: admin`). `author_username` is dropped. `default_author` is removed from `index.toml` — the server sets `author` from the authenticated user's JWT identity when creating posts.

### Display name resolution

Display names are resolved at query time via a LEFT JOIN from `PostCache.author` to `users.username`. The API returns `users.display_name`, falling back to the raw username if the user doesn't exist or has no display name set. This means renaming a display name is instantly reflected everywhere with no file rewrites.

### Database

- Drop `author_username` column (and index) from `PostCache` via Alembic migration
- `PostCache.author` stores the username from front matter
- `users.username` already has a UNIQUE index, making the join efficient

### Filtering and sorting

The `author` query parameter on `GET /api/posts` filters on the resolved display name (via the LEFT JOIN), not the raw username. Sorting by `author` also uses the resolved display name.

### Ownership and draft visibility

Draft visibility checks change from `PostCache.author_username == current_user.username` to `PostCache.author == current_user.username`.

### Sync

`author_username` is removed from the front matter merge conflict detection field list. `author` (username) remains — server wins on conflict as before. The CLI sync client is unchanged.

### Deleted code

| Component | What | Why |
|-----------|------|-----|
| `post_owner_service.py` | Entire file | No owner resolution needed |
| `admin_service.py` | `update_user_display_name()`, `sync_default_author_from_admin()` | Display names resolved at query time |
| `admin.py` (API) | `PUT /api/admin/display-name` endpoint | No longer needed |
| `toml_manager.py` | `default_author` from `SiteConfig` | Server uses JWT identity |
| `index.toml` | `default_author` field | Same |
| `PostCache` model | `author_username` column + index | Redundant |
| `frontmatter.py` | `author_username` from `RECOGNIZED_FIELDS` and `PostData` | Dropped field |
| `cache_service.py` | Owner resolution logic in `rebuild_cache()` | No longer needed |

### Deleted users

Posts by deleted users display the raw username as the author name — no data loss.
