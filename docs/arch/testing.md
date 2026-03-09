# Testing

## Backend (pytest)

Tests live under `tests/` with shared fixtures in `conftest.py` (tmp content dir, settings, DB engine/session). Modules are organized by layer:

- **`test_api/`** — API integration tests via `httpx.AsyncClient` + `ASGITransport`: CRUD, security, auth hardening, input validation, cross-posting, content serving, draft visibility, post uploads/renames, and security regressions.
- **`test_services/`** — Service-layer unit tests: auth, admin, sync, content manager, cross-posting, crypto, datetime, git, slug generation, rate limiting, SSRF protection, TOML/frontmatter parsing, cache rebuild resilience, and startup hardening.
- **`test_labels/`** — Label DAG operations and label service tests.
- **`test_rendering/`** — Pandoc integration, frontmatter parsing, HTML sanitization, URL rewriting, and dead-code checks.
- **`test_cli/`** — CLI tools: sync client, deployment, dev server, mutation testing orchestration, ZAP scanning of the local Caddy-backed build profile (including scoped hook-based hardening and stale-report cleanup), and path safety.
- **`test_sync/`** — Sync client integration and frontmatter normalization.

Configuration in `pyproject.toml`: `asyncio_mode = "auto"`, coverage via `pytest-cov`, `fail_under = 80` with branch coverage enabled.

Slow backend tests which take more than 1s to run should be marked @pytest.mark.slow. If a fixture setup takes more than 1s, the entire group of tests using that fixture should be marked @pytest.mark.slow.

Property-based testing is implemented with Hypothesis for high-invariant backend logic:
- sync plan classification and symmetry invariants
- front matter merge, normalization, and parsing invariants
- label DAG cycle-breaking invariants
- URL/path safety invariants across rendering, sync, content serving, and CLI path resolution
- auth service token/password invariants
- crypto service encrypt/decrypt round-trip invariants
- datetime service parsing invariants
- slug generation invariants
- TOML manager round-trip invariants

## Frontend (Vitest)

Vitest with jsdom environment, `@testing-library/react`, and `@testing-library/user-event`. Test setup (`src/test/setup.ts`) fails tests on unexpected `console.error`/`console.warn` output.

Coverage thresholds: statements 80%, branches 70%, functions 80%, lines 80%.

Property-based testing is implemented with `fast-check` for deterministic frontend logic:
- share utility invariants (`shareUtils`): URL/query encoding, hostname validation, and platform fallbacks
- editor transformation invariants (`wrapSelection`): splice correctness, cursor bounds, and block newline semantics
- label graph invariants (`graphUtils`): cycle detection, depth computation, and descendant traversal
- cross-post text/url invariants (`crosspostText`): post-path normalization and hashtag truncation/content assembly
