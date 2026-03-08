# Data Flow

## Creating a Post (Editor)

```
Frontend sends structured data: { title, body, labels, is_draft }
    → POST /api/posts
        → Require admin
        → Backend generates directory path: posts/<date>-<slug>/index.md
        → Backend sets author from authenticated user
        → Backend sets created_at and modified_at to now
        → Constructs PostData from structured fields
        → serialize_post() assembles YAML front matter + body
        → write to content/ directory (creates directory)
        → render full HTML via Pandoc + render excerpt via excerpt-specific Pandoc/sanitizer path
        → rewrite relative URLs, store in PostCache
```

## Updating a Post (Editor)

```
Frontend sends structured data: { title, body, labels, is_draft }
    → PUT /api/posts/{path}
        → Require admin
        → Backend uses title from request body
        → Backend preserves original author and created_at from filesystem
        → Backend sets modified_at to now
        → Constructs PostData from structured fields
        → serialize_post() assembles YAML front matter + body
        → write to content/ directory
        → If title slug changed: rename directory, create symlink at old path
        → render full HTML via Pandoc + render excerpt via excerpt-specific Pandoc/sanitizer path
        → rewrite relative URLs, update PostCache
        → Returns new file_path (may differ from request path after rename)
```

## Publishing a Post (Filesystem)

```
Write .md file → ContentManager.write_post()
    → serialize YAML front matter + body
    → write to content/ directory
    → rebuild_cache()
        → parse all .md files
        → render full HTML via Pandoc + render excerpts via excerpt-specific Pandoc/sanitizer path
        → populate PostCache + PostsFTS
        → parse labels.toml
        → populate LabelCache + PostLabelCache
```

## Editing a Post (Loading)

```
GET /api/posts/{path}/edit (admin required)
    → ContentManager.read_post()
        → parse .md file from filesystem
        → return structured JSON: title, body, labels, is_draft, timestamps, author
```

## Reading a Post

```
GET /api/posts/{path}
    → PostService.get_post()
        → query PostCache (pre-rendered HTML)
        → return cached metadata + HTML
```

## Viewing a Post (Social Media Crawler)

```
GET /post/{file_path}
    → Query PostCache by file_path
    → If found and not draft:
        → Strip HTML from rendered_excerpt for description
        → Read site_config.title for og:site_name
        → inject_og_tags() into cached index.html
        → Return enriched HTML (SPA boots normally)
    → If not found or draft:
        → Return unmodified index.html
```

## Uploading a Post (File or Folder)

```
User selects a .md file or a folder (with index.md + assets) on the Timeline page
    → POST /api/posts/upload (multipart form data)
        → Require admin
        → Find the markdown file (index.md preferred, else single .md file)
        → Parse frontmatter via parse_post() (same as sync/cache rebuild)
        → Normalize: title from frontmatter → first heading → ?title param → 422
        → Set created_at, modified_at, author, labels, is_draft with defaults
        → Generate post directory via generate_post_path()
        → Write all files (normalized markdown + assets)
        → Create PostCache, render HTML, update FTS index
        → Git commit
        → Return PostDetail → frontend navigates to new post
    → If 422 with "no_title": frontend shows title prompt, retries with ?title=
```

## Uploading Assets (Editor)

```
Frontend sends multipart file upload
    → POST /api/posts/{path}/assets
        → Require admin
        → Verify post exists in DB cache
        → Reject flat-file post paths; asset management requires `.../index.md`
        → Write files to post's directory (10 MB limit per file)
        → Git commit
        → Return list of uploaded filenames
        → Frontend inserts markdown at cursor: ![name](name) for images, [name](name) for others
```

## Serving Content Files

```
GET /api/content/{file_path}
    → Validate path (no traversal, allowed prefixes: posts/, assets/)
    → Verify resolved path stays within content directory
    → For draft content files (directory assets and flat draft markdown): require draft author authentication
    → Return FileResponse with guessed content type
```

## Deleting a Post

```
DELETE /api/posts/{path}?delete_assets=true|false
    → Require admin
    → If delete_assets=true and post is index.md:
        → Remove symlinks pointing to directory
        → Remove entire directory (post + all assets)
    → If delete_assets=false (default):
        → Remove only the .md file
    → Clean up DB cache, FTS index, label associations
    → Git commit
```

## Searching

```
GET /api/posts/search?q=...
    → PostService.search_posts()
        → FTS5 MATCH query on posts_fts
        → join with PostCache for metadata
        → return ranked results with snippets
```
