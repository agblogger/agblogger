# Testing

## Backend (pytest)

```
tests/
├── conftest.py                             Fixtures: tmp content dir, settings, DB engine/session
├── test_api/
│   ├── test_api_integration.py             Full API tests via httpx AsyncClient + ASGITransport
│   ├── test_api_security.py                Security-related API tests
│   ├── test_auth_hardening.py              Auth abuse protections and rate limiting
│   ├── test_bluesky_oauth_endpoints.py     Bluesky OAuth endpoint tests
│   ├── test_content_api.py                 Content serving API tests
│   ├── test_crosspost_api.py               Cross-post API tests
│   ├── test_crosspost_helpers.py           Cross-post helper function tests
│   ├── test_crosspost_robustness.py        Cross-post error handling/resilience
│   ├── test_draft_visibility.py            Draft access control tests
│   ├── test_error_handling.py              API error response tests
│   ├── test_input_validation.py            Request validation tests
│   ├── test_path_safety_hypothesis.py      Property-based path safety checks
│   ├── test_post_assets_upload.py          Post asset upload tests
│   ├── test_post_directory.py              Post-per-directory tests
│   ├── test_post_rename.py                 Post rename/symlink tests
│   ├── test_post_upload.py                 Post file/folder upload tests
│   └── test_security_regressions.py        Security regression tests
├── test_cli/
│   ├── test_deploy_production.py           Deployment script tests
│   ├── test_dev_server.py                  Dev server manager tests
│   ├── test_mutation_backend.py            Mutation testing orchestration tests
│   ├── test_safe_path.py                   CLI path safety tests
│   ├── test_sync_client.py                 CLI sync client tests
│   └── test_zap_scan.py                    OWASP ZAP orchestration tests
├── test_labels/
│   ├── test_label_dag.py                   Label DAG operations
│   ├── test_label_dag_hypothesis.py        Property-based DAG cycle-breaking
│   └── test_label_service.py              Label service tests
├── test_rendering/
│   ├── test_frontmatter.py                 Frontmatter parsing tests
│   ├── test_frontmatter_parsing_hypothesis.py  Property-based frontmatter parsing
│   ├── test_pandoc_server.py               Pandoc server integration tests
│   ├── test_renderer_no_dead_code.py       Renderer dead-code checks
│   ├── test_sanitizer.py                   HTML sanitizer tests
│   └── test_url_rewriting.py              Relative URL rewriting tests
├── test_services/
│   ├── _ssrf_helpers.py                    SSRF testing utilities
│   ├── test_admin_service.py               Admin service operations
│   ├── test_atproto_oauth.py               AT Protocol OAuth tests
│   ├── test_auth_edge_cases.py             Auth edge case tests
│   ├── test_auth_service.py                Auth service operations
│   ├── test_auth_service_hypothesis.py     Property-based auth tests
│   ├── test_bluesky_oauth_state.py         OAuth state store tests
│   ├── test_cache_rebuild_resilience.py    Cache rebuild robustness
│   ├── test_config.py                      Settings loading
│   ├── test_content_manager.py             ContentManager operations
│   ├── test_crosspost_decrypt_fallback.py  Credential decryption fallback
│   ├── test_crosspost_error_handling.py    Cross-post error handling
│   ├── test_crosspost_formatting.py        Cross-post text formatting
│   ├── test_crosspost.py                   Cross-posting platforms
│   ├── test_crypto_service.py              Fernet encryption
│   ├── test_crypto_service_hypothesis.py   Property-based crypto tests
│   ├── test_database.py                    DB engine creation
│   ├── test_datetime_service.py            Date/time parsing
│   ├── test_datetime_service_hypothesis.py Property-based datetime tests
│   ├── test_ensure_content_dir.py          Content directory scaffolding
│   ├── test_error_handling.py              Service-level error handling
│   ├── test_frontmatter_hypothesis.py      Property-based frontmatter tests
│   ├── test_frontmatter_merge.py           Semantic front matter merge
│   ├── test_frontmatter_parsing_hypothesis.py  Property-based frontmatter parsing
│   ├── test_git_merge_file.py              git merge-file wrapper tests
│   ├── test_git_service.py                 Git service operations
│   ├── test_hybrid_merge.py                Hybrid merge (front matter + body)
│   ├── test_invite_code.py                 Invite code tests
│   ├── test_label_schema_validation.py     Label schema validation
│   ├── test_pat_last_used.py               PAT last-used tracking
│   ├── test_rate_limiter.py                Rate limiter tests
│   ├── test_scan_posts_exception.py        Post scanning error handling
│   ├── test_slug_service.py                Slug generation tests
│   ├── test_slug_service_hypothesis.py     Property-based slug tests
│   ├── test_ssrf.py                        SSRF protection tests
│   ├── test_startup_hardening.py           Startup security validation tests
│   ├── test_sync_merge_integration.py      Full sync merge API flow
│   ├── test_sync_normalization.py          Sync frontmatter normalization
│   ├── test_sync_service_hypothesis.py     Property-based sync invariants
│   ├── test_sync_service.py                Sync plan computation
│   ├── test_toml_manager.py                TOML config parsing
│   ├── test_toml_manager_hypothesis.py     Property-based TOML tests
│   └── test_toml_validation.py             TOML input validation
└── test_sync/
    ├── test_normalize_frontmatter.py       Frontmatter normalization in sync
    └── test_sync_client.py                 Sync client integration tests
```

Configuration in `pyproject.toml`: `asyncio_mode = "auto"`, coverage via `pytest-cov`, `fail_under = 80` with branch coverage enabled.

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

```
src/
├── App.test.tsx
├── components/
│   ├── crosspost/__tests__/
│   │   ├── CrossPostDialog.test.tsx
│   │   ├── CrossPostHistory.test.tsx
│   │   ├── CrossPostSection.test.tsx
│   │   ├── PlatformIcon.test.tsx
│   │   ├── SocialAccountsPanel.test.tsx
│   │   └── crosspostText.property.test.ts    Property-based (fast-check)
│   ├── editor/__tests__/
│   │   ├── LabelInput.test.tsx
│   │   ├── MarkdownToolbar.test.tsx
│   │   └── wrapSelection.property.test.ts    Property-based (fast-check)
│   ├── filters/__tests__/
│   │   └── FilterPanel.test.tsx
│   ├── labels/__tests__/
│   │   ├── LabelChip.test.tsx
│   │   ├── graphUtils.test.ts
│   │   └── graphUtils.property.test.ts       Property-based (fast-check)
│   ├── layout/__tests__/
│   │   └── Header.test.tsx
│   ├── posts/__tests__/
│   │   ├── PostCard.test.tsx
│   │   └── TableOfContents.test.tsx
│   └── share/__tests__/
│       ├── MastodonSharePrompt.test.tsx
│       ├── ShareBar.test.tsx
│       ├── ShareButton.test.tsx
│       ├── shareUtils.test.ts
│       ├── shareUtils.property.test.ts       Property-based (fast-check)
│       ├── testUtils.ts                      Share test helpers
│       └── testUtils.test.ts
├── hooks/__tests__/
│   ├── useActiveHeading.test.ts
│   ├── useCodeBlockEnhance.test.ts
│   ├── useEditorAutoSave.test.ts
│   └── useKatex.test.ts
├── pages/__tests__/
│   ├── AdminPage.test.tsx
│   ├── EditorPage.test.tsx
│   ├── LabelGraphPage.test.tsx
│   ├── LabelPostsPage.test.tsx
│   ├── LabelSettingsPage.test.tsx
│   ├── LabelsPage.test.tsx
│   ├── LoginPage.test.tsx
│   ├── PageViewPage.test.tsx
│   ├── PostPage.test.tsx
│   ├── SearchPage.test.tsx
│   └── TimelinePage.test.tsx
└── stores/__tests__/
    ├── authStore.test.ts
    ├── siteStore.test.ts
    └── themeStore.test.ts
```

Coverage thresholds: statements 80%, branches 70%, functions 80%, lines 80%.

Property-based testing is implemented with `fast-check` for deterministic frontend logic:
- share utility invariants (`shareUtils`): URL/query encoding, hostname validation, and platform fallbacks
- editor transformation invariants (`wrapSelection`): splice correctness, cursor bounds, and block newline semantics
- label graph invariants (`graphUtils`): cycle detection, depth computation, and descendant traversal
- cross-post text/url invariants (`crosspostText`): post-path normalization and hashtag truncation/content assembly

## Mutation Testing

Mutation testing is implemented in three production phases with dedicated `just` targets.

### Backend targeted profile

- Runner: `cli/mutation_backend.py`, profile `backend`
- Goal: strict mutation gate for high-risk backend paths (auth, sync, front matter normalization, slugging, SSRF, rate limiting)
- Command: `just mutation-backend`
- Runtime mode: `mutate_only_covered_lines = false` (full-file mutation for stronger robustness at the cost of runtime)
- Quality enforcement:
  - minimum strict mutation score (`killed / (total - skipped - not_checked)`)
  - explicit budgets for `survived`, `timeout`, `suspicious`, `no tests`, `segfault`, and interrupted mutants
- Report: `reports/mutation/backend.json`
- Tunables:
  - `MUTATION_MAX_CHILDREN=<n>` to cap worker parallelism
  - `MUTATION_KEEP_ARTIFACTS=true` to persist mutmut workspaces in `reports/mutation/artifacts/`
  - when artifacts are persisted, clean them (`rm -rf reports/mutation/artifacts`) before running `just check` to avoid static-analysis noise from instrumented files

### Backend full profile

- Runner: `cli/mutation_backend.py`, profile `backend-full`
- Goal: broad backend + CLI mutation sweep across stable, high-signal suites
- Test selection: backend service/CLI/sync/labels/rendering suites (API-heavy suites are handled by the targeted backend profile and excluded here for mutmut stats stability)
- Uses the same full-file mutation mode (`mutate_only_covered_lines = false`)
- Excludes `tests/test_services/test_sync_merge_integration.py` from mutation runs due to mutmut instrumentation instability in that flow
- Excludes `tests/test_rendering/test_renderer_no_dead_code.py` from mutation runs because mutmut-generated symbols intentionally violate that module’s dead-code/introspection assertions
- Excludes broad API integration/security modules from full-profile stats collection because mutmut stats-mode instrumentation causes repeated false failures in shared ASGI fixture flows
- Deselects introspection-sensitive coroutine-shape assertions (for example `TestIsSafeUrlAsync::test_is_safe_url_is_async`) that are invalidated by mutmut trampoline wrapping in `stats` mode
- Excludes mutation of `backend/main.py` to avoid mutmut stats-stage bootstrap instability in full-suite runs
- Command: `just mutation-backend-full`
- Report: `reports/mutation/backend-full.json`

### Frontend mutation profiles

- Engine: StrykerJS with Vitest runner
- Tooling is pinned in `frontend/package.json` devDependencies (`@stryker-mutator/*` v`9.5.1`) and run via local `stryker` binaries
- Targeted config: `frontend/stryker.mutation.config.mjs`
- Broad full-run config: `frontend/stryker.mutation-full.config.mjs`
- Commands:
  - `just mutation-frontend`
  - `just mutation-frontend-full`
- `just` targets auto-clean `.stryker-tmp/frontend*` sandboxes on exit (success or failure) to keep frontend static checks clean after mutation runs
- Reports:
  - `frontend/reports/mutation/frontend.html`
  - `frontend/reports/mutation/frontend.json`
  - `frontend/reports/mutation/frontend-full.html`
  - `frontend/reports/mutation/frontend-full.json`

### Composite mutation gates

- PR gate: `just mutation` (backend targeted + frontend targeted)
- Nightly gate: `just mutation-full` (backend targeted + backend full + frontend full)

## Dynamic Application Security Testing (DAST)

OWASP ZAP packaged scans are wrapped by `cli/zap_scan.py` and exposed as `just zap-baseline` and `just zap-full`.

- Runner model: uses the official `ghcr.io/zaproxy/zaproxy:stable` Docker image, so ZAP is not installed on the host
- Target: the local frontend dev server (`http://127.0.0.1:<frontend_port>/` from the host, `http://host.docker.internal:<frontend_port>/` from the container)
- SPA support: both commands enable the AJAX spider (`-j`) so the React app is crawled as a browser-driven target rather than only as static HTML
- Lifecycle: the wrapper checks whether the repo dev server is already healthy; if not, it starts it, waits for health, runs ZAP, and then stops only the server instance it started
- Time limits: no `-m` limit is passed by default; operators can opt into a bounded run by providing a minute value
- Outputs:
  - `reports/zap/baseline/report.html`
  - `reports/zap/baseline/report.md`
  - `reports/zap/baseline/report.json`
  - `reports/zap/baseline/report.xml`
  - `reports/zap/full/report.html`
  - `reports/zap/full/report.md`
  - `reports/zap/full/report.json`
  - `reports/zap/full/report.xml`
- Tunables:
  - `just zap-baseline <n>` to opt into a minute limit
  - `just zap-full <n>` to opt into a minute limit
  - optional env overrides `ZAP_BASELINE_MINUTES` / `ZAP_FULL_MINUTES`

The ZAP scans are kept outside `just check` because baseline/full DAST runs are materially slower than static checks and active scanning intentionally probes the live dev app.
