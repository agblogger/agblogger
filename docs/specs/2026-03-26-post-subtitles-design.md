# Post Subtitles

Optional subtitle support for posts. Subtitles are stored in YAML front matter, cached in the database, exposed via the API, searchable via FTS, and displayed in the frontend.

## Front Matter & Parsing

Add `subtitle` to `RECOGNIZED_FIELDS` in `backend/filesystem/frontmatter.py`. Add an optional `subtitle: str | None` field to `PostData`.

- `parse_post()` reads `subtitle` from YAML, defaulting to `None` when absent.
- `serialize_post()` writes `subtitle` immediately after `title`, only when non-None.
- Existing posts without a subtitle are unaffected — the field is simply absent from their front matter.

Example front matter with subtitle:

```yaml
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

## Data Model & Database

Add a nullable `subtitle: Text` column to `PostCache` in `backend/models/post.py`.

Update the `PostsFTS` virtual table to index `title`, `subtitle`, and `content` (subtitle inserted between title and content).

Since the database is a derived cache rebuilt from the filesystem on startup, no migration is needed — the schema change takes effect on next rebuild.

Update cache-refresh logic that populates `PostCache` from `PostData` to include `subtitle`.

## API Schemas

In `backend/schemas/post.py`:

- `PostSummary`: add `subtitle: str | None = None`
- `PostDetail`: inherits from `PostSummary`, gets it automatically
- `PostEditResponse`: add `subtitle: str | None = None`
- `PostSave`: add `subtitle: str | None = None` with max length 500, whitespace-stripped

API endpoints that build responses (`_build_post_detail`, list endpoint, edit endpoint) pass through the cached subtitle value. Create/update endpoints pass subtitle through to the filesystem write.

## Frontend: Editor

In `EditorPage.tsx`, add a text input below the title field with placeholder "Subtitle". New `subtitle` state alongside existing `title` state.

- `fetchPostForEdit` response populates it.
- `PostSave` includes it on save.
- When empty/blank, sent as `null` so it is omitted from front matter.

## Frontend: Display

**Post detail page** (`PostPage.tsx`): When subtitle is present, render a `<p>` immediately below the `<h1>` title. Styled with `font-display`, smaller than the title (e.g. `text-xl md:text-2xl`), and a muted color (e.g. `text-ink/70`) to establish visual hierarchy.

**Post cards** (`PostCard.tsx`): When subtitle is present, render it below the card's `<h2>` title, above the excerpt. Smaller and muted relative to the card title (e.g. `text-base text-ink/60`).

**Search results**: Same treatment as post cards — subtitle below the result title when present.

When subtitle is `null`, nothing renders and layout is unchanged from current behavior.

## Testing

**Backend unit tests:**
- Front matter round-trip (parse then serialize) with and without subtitle
- `PostSave` validation: max length, whitespace stripping, null handling

**Backend integration tests:**
- Create/update posts with subtitle via API
- Verify subtitle appears in list, detail, and edit responses
- Verify subtitle persists in front matter on disk
- Verify FTS search matches subtitle content

**Frontend tests:**
- Editor renders subtitle input and includes it in save payload
- Post card and post detail conditionally render subtitle

## Documentation

Update `docs/arch/formats.md` to add `subtitle` to the front matter spec example and field list.
