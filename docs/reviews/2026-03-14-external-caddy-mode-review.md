# PR Review: feat/external-caddy-mode

**Date:** 2026-03-14
**Branch:** `feat/external-caddy-mode` vs `origin/main`
**Scope:** 15 files, ~5000 lines, 37 commits
**Summary:** Adds external Caddy deployment mode, hardens crosspost SSRF/OAuth security.

## Review Agents Used

- Code reviewer (general quality, CLAUDE.md compliance)
- Silent failure hunter (error handling, catch blocks, fallback behavior)
- Test analyzer (test coverage gaps and quality)
- Comment analyzer (comment accuracy and documentation consistency)
- Type design analyzer (new types/dataclasses design quality)

---

## Critical Issues (3 found)

### 1. Missing regression test for Bluesky OAuth `iss` bypass [security]

**Flagged by:** code-reviewer, test-analyzer, error-reviewer

`backend/api/crosspost.py:382` -- The fix from `if iss and iss != ...` to `if not iss or iss != ...` closes a real OAuth vulnerability, but there is no test verifying a missing `iss` is now rejected. Existing tests were only updated to *include* `iss` so they keep passing. CLAUDE.md requires: "Any security-sensitive bug fix must include failing-first regression tests covering abuse paths."

**Action:** Add a test where `iss` is omitted from the callback, asserting HTTP 400.

### 2. Dead test -- nested function will never run [testing]

**Flagged by:** test-analyzer

`tests/test_cli/test_deploy_production.py:3209-3237` -- `test_daemon_check_skipped_for_dry_run` has a `self` parameter and is nested inside a standalone test function. Pytest will never discover or execute it.

**Action:** Move it to the appropriate test class (likely `TestDockerDaemonCheck`).

### 3. Generated `setup.sh` silently continues if subnet detection fails [error-handling]

**Flagged by:** error-reviewer

`cli/deploy_production.py:522-536` -- If `docker network inspect caddy` fails or returns empty, `$CADDY_SUBNET` becomes empty and `sed` replaces the placeholder with nothing. Result: `TRUSTED_PROXY_IPS=[""]` -- a silent security misconfiguration.

**Action:** Add a guard in the generated script: `if [ -z "$CADDY_SUBNET" ]; then echo "Error: ..." >&2; exit 1; fi`

---

## Important Issues (6 found)

### 4. No error handling for filesystem I/O in `ensure_shared_caddy` [error-handling]

**Flagged by:** error-reviewer

`cli/deploy_production.py:831-841` -- `mkdir`/`write_text` against `/opt/caddy` (requires root). `PermissionError` is not caught by `main()`, producing a raw traceback.

**Action:** Wrap in try/except, raise `DeployError` with actionable message.

### 5. No error handling for filesystem I/O in `write_caddy_site_snippet` [error-handling]

**Flagged by:** error-reviewer

`cli/deploy_production.py:848-853` -- Same issue as above for the site snippet write.

**Action:** Wrap in try/except, raise `DeployError` with actionable message.

### 6. Missing timeout in `_is_container_running` [error-handling]

**Flagged by:** error-reviewer

`cli/deploy_production.py:817-822` -- `subprocess.run` without timeout. All other subprocess calls in the file have timeouts. A hanging Docker daemon freezes deployment silently.

**Action:** Add `timeout=10`.

### 7. `use_caddy` computed inconsistently across call sites [code-quality]

**Flagged by:** code-reviewer, type-analyzer

Lines 1350/1375/1381 use `caddy_config is not None and caddy_mode != EXTERNAL` but lines 1115/1472 use just `caddy_config is not None`. The inconsistency is currently harmless but fragile.

**Action:** Add a `@property` on `DeployConfig` or extract a helper to eliminate the 3x repetition.

### 8. `caddy_mode` is stringly-typed [type-design]

**Flagged by:** type-analyzer

`cli/deploy_production.py:147` -- `caddy_mode: str` accepts any string. The codebase already uses `Literal` in `cli/zap_scan.py`. `CaddyMode = Literal["bundled", "external", "none"]` gives static checking at zero runtime cost.

### 9. Missing `acme_email` validation for `SharedCaddyConfig` [type-design]

**Flagged by:** type-analyzer

`_validate_config` checks `CaddyConfig.email` for `@` (line 978) but never validates `SharedCaddyConfig.acme_email`. Invalid emails reach Caddy unvalidated.

**Action:** Add parallel validation in `_validate_config`.

---

## Suggestions (6 found)

### 10. `reload_shared_caddy` -- no diagnostic context on failure [error-handling]

**Flagged by:** error-reviewer

`cli/deploy_production.py:856-872` -- Catch `CalledProcessError`, include Caddy stderr in the `DeployError`.

### 11. `.env.production` comment says "Only used in no-Caddy mode" [comments]

**Flagged by:** comment-analyzer

`cli/deploy_production.py:257-258` -- Now also unused in external Caddy mode. Update to "Not used in Caddy modes."

### 12. `build_image_compose_content` docstring says "Caddy-first" [comments]

**Flagged by:** comment-analyzer

`cli/deploy_production.py:704-705` -- Misleading; Caddy doesn't start first. Reword to "with a bundled Caddy reverse proxy."

### 13. `docs/arch/deployment.md:36` trailing slash inconsistency [comments]

**Flagged by:** comment-analyzer

Documentation says `/opt/caddy/` but constant is `/opt/caddy` (no slash).

### 14. No test for `collect_config` interactive flow with external Caddy [testing]

**Flagged by:** test-analyzer

The interactive prompt sequence for external Caddy mode is untested.

### 15. No test for `reload_shared_caddy` failure propagation in deploy flow [testing]

**Flagged by:** test-analyzer

Only the happy path is tested.

---

## Strengths

- **Security hardening is solid**: SSRF-safe client swap in crosspost modules is clean, tests properly updated, OAuth issuer fix is correct.
- **Test coverage is extensive**: ~1200 new test lines covering validation, config construction, compose generation, setup script phases, bundle files, and end-to-end deploy flows.
- **Architecture is well-designed**: SharedCaddyConfig, site snippet generation, subnet placeholder, and idempotent setup script are all sound design choices.
- **Comments are accurate and purposeful**: The `0.0.0.0` workaround comment, regex documentation, and generated script comments are all high quality.
- **Documentation is consistent with code**: deployment.md and security.md updates accurately reflect the implementation.

---

## Type Design Analysis

### `CaddyMode` Constants (lines 52-55)

Bare module-level string constants with no type-level safety. `Literal["bundled", "external", "none"]` would match the existing `ScanMode` precedent in `cli/zap_scan.py`.

- Encapsulation: 2/10
- Invariant Expression: 3/10
- Invariant Usefulness: 7/10
- Invariant Enforcement: 5/10

### `SharedCaddyConfig` (lines 119-124)

Frozen dataclass with correct field types. Missing construction-time validation for `acme_email` and `caddy_dir`.

- Encapsulation: 7/10
- Invariant Expression: 5/10
- Invariant Usefulness: 7/10
- Invariant Enforcement: 4/10

### `DeployConfig` -- New Fields (lines 147-148)

Cross-field invariants (mode vs config presence) are representable in illegal combinations. The repeated `use_caddy` derivation (3 occurrences) indicates a missing abstraction.

- Encapsulation: 5/10
- Invariant Expression: 3/10
- Invariant Usefulness: 8/10
- Invariant Enforcement: 6/10

**Pragmatic recommendations:** (1) Use `Literal` for `caddy_mode`, (2) add `use_caddy` property, (3) add missing validations. **Aspirational:** Consider discriminated union (`BundledCaddy | ExternalCaddy | None`).

---

## Recommended Action Plan

1. Fix **Critical #1** (missing `iss` regression test) -- security compliance requirement
2. Fix **Critical #2** (dead test) -- test code that will never run
3. Fix **Critical #3** (subnet guard in setup script) -- silent security misconfiguration
4. Address **Important #4-6** (error handling gaps) -- raw tracebacks in production CLI
5. Address **Important #7-9** (code quality) -- before the patterns spread further
6. Consider suggestions as time permits
