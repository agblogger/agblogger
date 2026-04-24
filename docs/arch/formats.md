# Content Formats

Read this document when a task touches the canonical on-disk content model. It describes the file formats used for markdown content, site configuration, and labels.

## Content Directory Shape

The `content/` directory is the canonical content tree. It contains:

```text
content/
├── assets/           Shared content assets not scoped to a single post
├── index.toml        Site-wide metadata and top-level page/navigation configuration
├── labels.toml       Label graph definition
└── posts/            Directory-backed markdown posts with optional co-located assets
```

Posts are stored as directory-backed content units so each post keeps its markdown source and related assets together. The tree may also contain internal dotfiles used by local workflows or integrations, but those are not part of the publishing model.

Example:

```text
content/posts/example-post/
├── index.md
└── diagram.png
```

## Posts

Posts are markdown files with YAML front matter followed by a markdown body.

Example:

```md
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

This is the markdown body.
```

Field meanings:

- `title`: human-readable post title shown in the UI and downstream integrations
- `subtitle`: optional short description displayed below the title; omitted from front matter when absent
- `created_at`: canonical creation timestamp for the post
- `modified_at`: canonical last-modified timestamp used to track content changes
- `author`: logical author identity associated with the post
- `labels`: list of label references; each entry points to a label id such as `#architecture`
- `draft`: publication-state flag; draft posts remain part of canonical content but are unpublished

Format notes:

- the YAML front matter carries canonical metadata
- the markdown body carries the post content itself
- assets that belong to a post live next to its `index.md`
- the canonical on-disk post path is always `posts/<slug>/index.md`
- public post slugs and post-asset URLs are derived from these directory-backed post units
- shared assets can live under `content/assets/` when they are not scoped to a single post

## Site Configuration

Site-wide configuration lives in `content/index.toml`. It defines global blog metadata and top-level navigational structure.

Example:

```toml
[site]
title = "Example Blog"
description = "Notes on software and systems"
timezone = "UTC"
# favicon = "assets/favicon.png"  # optional; set via admin panel

[[pages]]
id = "timeline"
title = "Posts"

[[pages]]
id = "labels"
title = "Labels"

[[pages]]
id = "about"
title = "About"
file = "about.md"
```

Field meanings:

- `[site]`: global blog metadata shared across the application
- `site.title`: site title presented in the UI and related outputs
- `site.description`: short site summary used where the application needs a top-level description
- `site.timezone`: canonical site timezone for content- and display-related decisions
- `site.favicon`: optional relative path within `content/` for the site favicon image
- `[[pages]]`: top-level page definitions used for navigation and presentation structure
- `pages.id`: stable page identifier referenced by the application
- `pages.title`: human-readable page label shown in navigation or page chrome
- `pages.file`: optional markdown file path for a page backed by content on disk

Format notes:

- this file is canonical content, not derived runtime configuration
- it describes site-level structure rather than per-post content
- page entries can represent navigational structure, file-backed pages, or both

## Labels

`content/labels.toml` stores the label graph as a TOML-defined directed acyclic graph. Each label entry can declare names and parent references.

Example:

```toml
[labels.programming]
names = ["programming"]

[labels.python]
names = ["python"]
parent = "#programming"

[labels.async]
names = ["async", "asynchronous"]
parents = ["#programming", "#python"]
```

Field meanings:

- `labels.<id>`: stable label definition keyed by label id
- `names`: optional display names or aliases associated with the label; the list may be empty
- `parent`: single parent label reference
- `parents`: multiple parent label references for labels that belong in more than one branch

Format notes:

- labels are referenced elsewhere by `#label-id`
- the label graph is hierarchical, but multiple parents are allowed
- label definitions are canonical source data rather than derived taxonomy output

## Code Entry Points

- `backend/filesystem/frontmatter.py` handles markdown post front matter parsing and serialization.
- `backend/filesystem/toml_manager.py` handles site and label TOML parsing and writing.
- `backend/filesystem/content_manager.py` ties the canonical content files into the rest of the backend.
