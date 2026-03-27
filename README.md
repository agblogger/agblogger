# AgBlogger

A markdown-first blogging platform where markdown files with YAML front matter are the source of truth. A lightweight SQLite database serves as a cache for search/filtering and stores authentication data. Configuration lives in TOML files. A bidirectional sync engine keeps a local directory and the server in lockstep.

## Features

- **Markdown-first** — Pandoc rendering with KaTeX math, syntax highlighting, and video embeds
- **Label DAG** — Hierarchical labels forming a directed acyclic graph with interactive visualization
- **Bidirectional sync** — SHA-256 hash-based sync with three-way merge and conflict resolution
- **Cross-posting** — Publish to Bluesky, Mastodon, X (Twitter), and Facebook
- **Full-text search** — SQLite FTS5 index over post content and metadata
- **Hardened authentication** — HttpOnly cookie sessions for web, interactive login for CLI

## Quick Start

```bash
just setup    # Install deps, create .env from .env.example, create db dir
just start    # Start backend (:8000) + frontend (:5173) in the background
just stop     # Stop the dev server
```

The admin account is bootstrapped from environment configuration (`ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH`, `ADMIN_DISPLAY_NAME`). Update `.env` with your admin credentials before first start.

Run `just --list` to see all available commands.

## Testing

```bash
just check          # Full gate: static checks + tests
just check-extra    # Additional security/dependency scans + slow tests
just test           # Tests only (backend + frontend)
just clean          # Reset generated artifacts plus local data/ and content/
```

## Deployment

```bash
just deploy
```

The interactive script configures production settings, generates `.env.production` and Docker Compose overrides, and prints the exact commands to manage the deployed server. Caddy is available as an optional HTTPS reverse proxy.

The `content/` directory is the source of truth — back it up to preserve your blog. The database is regenerable from content files on startup (auth data is the exception).

## Project Structure

```
backend/          Python FastAPI application (API, services, models, sync engine)
frontend/         React + TypeScript SPA (Vite, TailwindCSS)
cli/              Sync and deployment CLIs
tests/            pytest test suite
content/          Sample blog content (markdown, TOML, assets)
docs/             Architecture and design documentation
```

## Content Authoring

Posts are markdown files with YAML front matter inside `content/posts/<slug>/index.md`:

```markdown
---
title: Hello World
created_at: 2026-02-02 22:21:29.975359+00
modified_at: 2026-02-02 22:21:35.000000+00
author: admin
labels:
- '#swe'
---

Post content here with **markdown**, $\LaTeX$ math, and `code blocks`.
```

Site configuration lives in `content/index.toml` and labels are defined in `content/labels.toml`.
