# Test Suite Review — 2026-03-12

**Scope**: ~160 test files (107 backend, 53 frontend) across pytest + Vitest.

**Overall verdict**: This is a strong, production-grade test suite. The majority of tests make meaningful assertions, error paths are systematically covered, and property-based tests encode genuine domain invariants. The issues below are relative weaknesses in an otherwise high-quality suite.

---

## 1. Assertion Quality

**Verdict: Strong.** Most tests verify response bodies, disk state, and side effects — not just status codes or mock calls.

**Standout examples:**
- `test_post_assets_upload.py:113` — verifies the uploaded file exists on disk with correct bytes, not just 200 status
- `test_post_rename.py:122` — resolves both old and new paths to confirm symlink targets match
- `test_write_locking.py:173` — uses `asyncio.gather` with execution-order tracking to prove operations don't interleave
- `test_frontmatter_merge.py` — 20 pure-function tests with concrete input/output, zero mocks

**Issues found:**

| Location | Problem |
|----------|---------|
| `test_api_security.py:69` | Asserts `status_code != 200 and < 500` — overly permissive. Should assert specific 400/404. Same at line 81. |
| `test_content_api.py:207` | `assert status_code in (403, 404)` — pick one canonical answer |
| `test_api_integration.py:196` | `test_list_labels` only checks `len(data) >= 1` without verifying label structure |
| `test_crash_hunting_consistency.py:101-149` | `TestUploadPostOrphanedAssets` — **tests never invoke production code**. They manually create/delete files and assert the manual deletion worked. These are tautologies. |
| `test_crash_hunting_consistency.py:160` | `test_file_survives_if_commit_fails` — never calls `delete_post_endpoint`. Passes trivially. |
| `test_crash_hunting_errors.py:288` | Uses `ast.parse`/`inspect.getsource` to check source code structure. Fragile; breaks on any refactor without testing behavior. Same pattern at line 228. |
| `test_remaining_error_fixes.py:179,268` | Source-code inspection via `inspect.getsource` / string matching. Fragile. |
| `test_crash_hunting_runtime.py:165-181` | `ensure_content_dir` tests assert only "no exception raised" without checking resulting directory state |
| `test_crash_hunting_runtime.py:77` | `assert hasattr(server, "_start_impl")` — pure structural check, zero behavior |
| `test_crash_hunting_runtime.py:59` | Concurrent starts test asserts `call_count == 3` but doesn't verify serialization (non-overlapping execution) |
| `test_crosspost_error_handling.py:127-159` | Three tests verifying Pydantic model defaults — trivially testing framework behavior |

---

## 2. Error Path Coverage

**Verdict: Excellent.** This is a standout strength of the suite.

- `test_error_handling.py` is 950+ lines dedicated to error scenarios: pandoc failures, OSError on writes, directory renames, symlink creation, cache rebuilds, git timeouts, config reload failures
- `test_global_exception_handlers.py` verifies 10+ exception types map to correct status codes and never leak internal details (e.g., line 83 confirms `cmd=["git", "commit", "-m", "secret"]` doesn't leak "git" or "secret")
- Frontend tests systematically cover 401, 404, 409, 422 (with multiple detail formats), 500, and network errors across every page
- `EditorPage.test.tsx` alone tests 8 distinct error response formats for the save endpoint

**One gap**: `authStore.test.ts` doesn't test what happens when `apiLogout` fails — does the user stay cleared or get restored?

---

## 3. Edge Case Coverage

**Verdict: Good, with specific gaps.**

**Well-covered edge cases:**
- Unicode: CJK-only titles, emoji-mixed titles, combining diacritical marks, accented characters (`test_post_directory.py:338-410`)
- Path traversal: URL-encoded backslashes, `../` in config, symlinks outside content dir, directory escape attacks
- Concurrency: token refresh races, invite code double-consumption, git write serialization
- Performance: adversarial regex input with 5000 unclosed `*` chars (`test_content_manager.py:243`)
- Grapheme counting: family emoji, flag emoji for Bluesky's 300-grapheme limit
- RFC compliance: Content-Disposition header escaping of double-quotes (`test_content_api.py:210`)

**Gaps:**

| Area | Missing |
|------|---------|
| `test_safe_path.py` | Only 5 test cases for a critical security boundary. Missing: null bytes, URL-encoded traversal (`%2e%2e`), double encoding, very long paths |
| `test_rate_limiter.py` | No tests for `window_seconds=0`, negative window, or memory bounds |
| `test_sanitizer.py` | No CSS injection tests (`expression()`, `url()` redirects). Missing `vbscript:`, mixed-case `JaVaScRiPt:`, entity-encoded `java&#115;cript:` |
| `test_admin_service.py` | No path-traversal test for `page_id` in `create_page` |
| Frontend | No test for editor keyboard shortcuts actually triggering formatting (Cmd+B -> bold). No test for login via Enter key. No concurrent save (double-click) test. |
| `posts.test.ts` | Only `fetchPosts`/`searchPosts` tested. `createPost`, `updatePost`, `deletePost`, `uploadPost` have no direct unit tests. |

---

## 4. Workflow Coverage

**Verdict: Excellent.**

- `test_editorial_workflow.py:59-165` — full post lifecycle: login -> create draft -> add labels -> preview -> edit -> publish -> verify public visibility -> delete -> verify 404
- `test_admin_workflow.py:55-137` — admin page lifecycle: create -> update -> create second -> verify both -> reorder -> verify order -> delete -> verify
- `test_publish_transition.py:55-198` — draft/publish timing: `created_at` updates on publish, stable on edits, updates again on re-publish
- `test_auth_hardening.py:565-615` — password rotation: session + PAT invalidation after password change
- Frontend `EditorPage.test.tsx` — draft recovery with restore/discard, save-and-stay, preview with code enhancement
- Frontend `TimelinePage.test.tsx:197-240` — draft posts disappear on logout (security/UX workflow)
- Frontend `useEditorAutoSave.test.ts` — 437 lines covering dirty tracking, debounce, draft recovery, schema versioning, beforeunload

**No significant gaps in workflow testing.**

---

## 5. Property-Based Tests

**Verdict: Strong — the best files encode genuine algebraic invariants. A few missed opportunities.**

**Best properties in the suite:**
- `test_sync_service_hypothesis.py:131` — **symmetry**: swapping client/server reverses directional actions
- `test_sync_service_hypothesis.py:87` — **partition invariant**: every path classified into exactly one bucket
- `test_frontmatter_hypothesis.py:177` — **three-way merge semantics**: labels follow `(base | server_added | client_added) - server_removed - client_removed`
- `test_path_safety_hypothesis.py:231` — **cross-implementation consistency**: all three path resolvers agree on safe paths
- `graphUtils.property.test.ts:205` — **model-based testing**: production code checked against independent reference implementation
- `test_label_dag_hypothesis.py:67` — **multiset partition + acyclicity**: accepted + dropped = original edges, accepted is a DAG

**Weaker properties:**
- `crosspostText.property.test.ts:43` — re-implements the function's logic in the test assertion rather than testing a higher-level invariant
- `shareUtils.property.test.ts:83` — same pattern
- `test_crypto_service_hypothesis.py:46` — `test_ciphertext_is_nonempty_ascii` is essentially a format check

**Missed opportunities:**

| Area | Valuable property |
|------|------------------|
| `key_derivation.py` | **Context separation**: `derive_access_token_key(k) != derive_encryption_key(k) != derive_csrf_token_key(k)` for any key. This is the entire security purpose of the module and has zero PBT coverage. |
| `slug_service.py` | `generate_post_path` is untested by PBT. Properties: output always under `posts_dir`, format is `YYYY-MM-DD-{slug}/index.md` |
| `frontmatter.py` | Excerpt idempotence: applying excerpt to its own output should not further reduce it. Table/image line stripping: `\|` and `![` lines never in output |
| HTML sanitizer | "Sanitized output never contains disallowed tags" and "sanitization is idempotent" |

---

## 6. Structural/Maintenance Issues

- **Duplicated test helpers**: Nearly every API test file has its own `_login` helper. A shared conftest fixture would reduce duplication.
- **`test_crosspost.py`** (1651 lines): `DummyAsyncClient` with `__aenter__`/`__aexit__`/`get`/`post` is duplicated in ~15 test methods. Extract to shared fixture.
- **`test_startup_hardening.py:287`**: Tests the `contextlib.suppress` *pattern*, not the actual `lifespan` shutdown code. Would still pass if lifespan changed.
- **`test_cache_rebuild_resilience.py:161`**: Inspects function signature for parameter name `session_factory`. A rename breaks the test without affecting behavior.
- **Frontend `MockHTTPError` casting**: `new (MockHTTPError as unknown as new (s: number) => Error)(404)` repeated throughout. A factory function would clean this up.
- **`App.test.tsx`**: Only checks header renders. Provides almost no value — the weakest test file in the suite.
