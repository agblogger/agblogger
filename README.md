# AgBlogger

A self-hosted, markdown-first blogging platform where markdown files with YAML front matter are the source of truth. A SQLite database provides fast search and stores durable application state. Configuration lives in TOML files, and a bidirectional sync engine keeps a local content directory and the server in sync.

## Features

- **Markdown-first** — Pandoc rendering with KaTeX math, syntax highlighting, video embeds, pages, drafts, and post assets
- **Web editor** — Live preview, autosave, formatting shortcuts, fullscreen mode, and asset management
- **Label DAG** — Hierarchical labels with multiple parents and interactive visualization
- **Bidirectional sync** — Manifest-based sync with three-way merge and conflict resolution
- **Cross-posting** — Publish to Bluesky, Facebook, Mastodon, and X
- **Email subscriptions** — Resend-powered double opt-in and new-post broadcasts without storing subscriber emails locally
- **Self-hosted analytics** — Optional GoatCounter analytics dashboard and public post view counts
- **Search and discovery** — Full-text search, RSS, sitemap, social metadata, and Markdown content negotiation
- **Hardened authentication** — HttpOnly cookie sessions for web and interactive login for the CLI

## Quick Start

```bash
just setup    # Install dependencies, create .env, create database directory
just start    # Start backend (:8000) + frontend (:5173) in the background
just health   # Check backend and frontend health
just stop     # Stop the dev server
```

The default development login is `admin` / `admin`. Update `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and optionally `ADMIN_DISPLAY_NAME` in `.env`.

Run `just --list` to see all available commands.

## Testing

```bash
just check          # Full gate: static checks + all tests with coverage
just check-extra    # Additional security and dependency scans
just test           # Tests only (backend + frontend) with coverage
just clean          # Reset generated artifacts plus local data and content
```

## Deployment

```bash
just deploy
```

The interactive deployment helper supports local, registry, and remote tarball deployments. It can configure bundled or shared Caddy HTTPS and the optional GoatCounter analytics sidecar.

Back up both `content/` and the persistent database volumes. Content files are the source of truth, while the database also stores authentication, integration, analytics, subscription, and sync state.

## Sync CLI

```bash
just install-uv
agblogger --dir ./content init --server https://blog.example.com --username admin
agblogger --dir ./content login
agblogger --dir ./content status
agblogger --dir ./content sync
```

## Project Structure

```text
backend/                  Python FastAPI application
frontend/                 React + TypeScript SPA
cli/                      Standalone sync CLI
packages/agblogger-core/  Shared backend and CLI path rules
tools/                    Development, deployment, and release tooling
tests/                    Backend and CLI test suite
content/                  Blog content, configuration, and assets
docs/                     Architecture and design documentation
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
draft: false
---

Post content here with **markdown**, $\LaTeX$ math, and `code blocks`.
```

Site configuration and navigation live in `content/index.toml`, labels are defined in `content/labels.toml`, and markdown-backed pages can live directly under `content/`.
