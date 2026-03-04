# Test Suite Review — 2026-03-03

## Overview

The test suite is **substantial and well-organized**: ~1,150 backend test functions across 83 files (~21K lines), and ~490 frontend test cases across 45 files. There are 10 Hypothesis property-based test modules (backend) and 5 fast-check modules (frontend). This is a solid foundation, but there are meaningful gaps.

---

## 1. Assertion Quality: Trivial vs. Meaningful

**Verdict: Mostly strong, with specific weak spots in the backend API integration tests.**

The frontend suite is excellent here — nearly every test verifies specific content, call arguments, or state transitions. The backend has several tests that check only `status_code` without verifying the response body:

| File | Test | Issue |
|------|------|-------|
| `tests/test_api/test_api_integration.py:1631` | `test_update_page` | Asserts 200 but never verifies the title actually changed |
| `tests/test_api/test_api_integration.py:1668` | `test_update_page_order` | Asserts 200 but never verifies the new order |
| `tests/test_api/test_api_integration.py:1339` | `test_search_special_characters` | Asserts 200 but never checks the result is a valid list |
| `tests/test_services/test_sync_merge_integration.py:199` | `test_upload_new_file` | Downloads the file after upload but never asserts the content matches |
| `tests/test_api/test_security_regressions.py:220` | `test_flat_draft_markdown_returns_200_for_author` | Only checks 200, never verifies the draft content is actually returned |

Status-code-only assertions for **auth/security boundary tests** (401, 403, 404) are appropriate — the test's purpose is verifying the gate itself.

---

## 2. Error Path Testing

**Verdict: Strong overall. Dedicated error-handling test files are a major strength.**

The backend has two dedicated error-handling test files (`test_api/test_error_handling.py` at 1,215 lines and `test_services/test_error_handling.py` at 754 lines) that systematically inject `OSError`, `RuntimeError`, `PermissionError`, and network failures via mocks. The security regression suite (`test_security_regressions.py`) tests abuse paths (impersonation, draft isolation, CSRF bypass, IP spoofing).

The frontend tests error states comprehensively — `EditorPage.test.tsx` alone tests 10+ distinct HTTP error scenarios (401, 409, 422 with string/array/field-message/empty/non-string/unparseable detail, 404, 500, generic).

**Gaps in error path testing:**

- **`csrf_service.validate_csrf_token()`** — Tests verify that a *missing* CSRF token is rejected (403), but a *wrong/tampered* CSRF token is never tested. The constant-time comparison logic is unverified.
- **`POST /api/auth/register`** when both `auth_self_registration=False` AND `auth_invites_enabled=False` — the "Registration is disabled" 403 path is never exercised.
- **`POST /api/auth/token-login`** rate limiting — the `/login` endpoint has rate-limit tests, but `token-login` (which shares the same underlying helper) has no test that exhausts attempts to trigger a 429.
- **`_enforce_login_origin()` with `Referer` header** — tests only cover `Origin` header rejection; the fallback from missing `Origin` to `Referer` is uncovered.
- **Admin service error paths** — `test_admin_service.py` tests only happy paths. Error injection (OSError during `update_site_settings`, `delete_page`) is only tested at the API layer via mocks, not at the service unit level.
- **Frontend `PageViewPage`** — does not distinguish 404 from generic network error; both show the same message.

---

## 3. Edge Cases

**Verdict: Good at the parsing/utility level, thin at the API workflow level.**

**Well-covered edge cases:**
- Unicode normalization, CJK, emoji, accented characters in slugs and git merges
- Empty/whitespace-only inputs for titles, labels, search queries
- Null bytes in files, oversized uploads (exact boundary at 10MB+1 byte)
- Symlinks: within content dir (allowed), escaping content dir (blocked), broken symlinks during delete
- Path traversal: `..`, `..%2F`, encoded slashes, absolute paths — tested via 3 separate path validators plus Hypothesis
- Concurrent git commits with event-based synchronization

**Missing edge cases:**
- **Very long post body** through the CRUD API (only the file scan path has a size test)
- **Post with empty body** (only front matter, no content) via the create endpoint
- **Concurrent post creation with identical titles** (slug collision race condition)
- **Deeply nested label hierarchy** (10+ levels) with recursive descendant queries
- **Pagination boundary** — tests create 3-4 posts; no test with 50+ posts across multiple pages
- **Trusted proxy `X-Forwarded-For` handling** — the untrusted case is tested, but the trusted-proxy case (where the forwarded IP should be used as the rate-limit key) is not
- **Rename collision loop** — the `-2`, `-3` suffix counter during title renames is untested
- **`POST /api/sync/commit`** with `deleted_files` containing non-list or non-string elements is not validated in tests

---

## 4. Complex User Workflows

**Verdict: Several good multi-step tests exist, but no end-to-end editorial lifecycle.**

**Good examples of workflow tests:**
- Password rotation -> all tokens and PATs revoked -> old credentials rejected (`test_auth_hardening.py`)
- Create draft -> upload asset -> rename -> verify old symlink blocked for unauthenticated (`test_draft_visibility.py`)
- Register with impersonated display name -> attempt 4 different access paths -> all blocked (`test_security_regressions.py`)
- Create label -> create post with label -> filter by label -> verify post_count (`test_api_integration.py`)
- Session login -> token login -> create PAT -> change password -> verify all 3 revoked (`test_auth_hardening.py`)

**Missing workflow tests:**
- **Full editorial lifecycle**: create post -> add labels -> preview -> edit -> publish (draft->published) -> crosspost -> delete. No single test exercises this complete flow.
- **Full bidirectional sync round-trip**: client upload -> status check (clean) -> server-side modification -> status check (download needed) -> client download -> commit with merged content. Individual legs are tested but not the full multi-round cycle.
- **Admin page management lifecycle**: create page -> update content -> reorder -> delete — only individual operations are tested, never sequentially.

---

## 5. Property-Based Tests

**Verdict: Most are strong with meaningful semantic invariants. A few are misused or trivial.**

**Excellent property tests:**
- **`test_sync_service_hypothesis.py`**: Tests that every file appears in exactly one plan bucket, that plan buckets are disjoint and complete, and that swapping client/server swaps directional actions (structural symmetry). This is the strongest in the suite.
- **`test_label_dag_hypothesis.py`**: Output partitions the input multiset, accepted set is always a DAG, breaking cycles is idempotent. Good mathematical invariants.
- **`test_path_safety_hypothesis.py`**: Three path validators never return outside root; URL rewriting is idempotent. Important security properties.
- **`test_frontmatter_hypothesis.py`**: Labels follow set-delta merge semantics, server-wins for scalar fields on conflict, `modified_at` never in output. Meaningful merge invariants.
- **Frontend `graphUtils.property.test.ts`**: Tests cycle detection, depth computation, and descendant computation against independent BFS reference implementations. Smart oracle-based testing.

**Weak property tests:**
- **`test_auth_service_hypothesis.py:116-137`** — Three "property" tests using `st.just(None)` as input: `test_refresh_token_is_nonempty_url_safe`, `test_personal_access_token_has_prefix`, `test_token_generators_produce_unique_values`. These call the function with no randomized input 150 times each. They're unit tests masquerading as property tests — they should either be plain unit tests or use meaningful strategies.
- **`test_slug_service_hypothesis.py`** — `test_slug_is_deterministic` (same input -> same output) is a trivially true purity check. The other slug properties (valid format, no consecutive hyphens, length <= 80) are meaningful.
- **`test_frontmatter_parsing_hypothesis.py`** — `test_never_returns_empty_string` for `extract_title` only checks non-emptiness. A stronger property: "if text contains a heading, `extract_title(text)` equals that heading's text."

---

## 6. Untested Endpoints and Modules

### Completely untested API endpoints:
| Endpoint | Status |
|----------|--------|
| `DELETE /api/crosspost/accounts/{account_id}` | Success, 404, and 401 paths all untested |
| `GET /api/labels/{label_id}` (404 case) | No test for nonexistent label |
| `GET /api/auth/csrf` (401 case) | Not tested when unauthenticated |

### Backend modules with no dedicated test file:
| Module | Risk |
|--------|------|
| `backend/services/page_service.py` | `get_page()` paths (no file, timeline special case) untested |
| `backend/services/post_owner_service.py` | Display-name deduplication and multi-user collision logic untested |
| `backend/services/csrf_service.py` | `validate_csrf_token()` never tested in isolation |
| `backend/services/key_derivation.py` | `derive_csrf_token_key()` untested |
| `backend/api/deps.py` | PAT-only branch, sub-is-not-digit validation untested directly |
| `backend/filesystem/content_manager.py` | `build_index()` method is dead code -- never called anywhere |

### Frontend coverage gaps:
| Module | Status |
|--------|--------|
| `api/posts.ts`, `api/labels.ts`, `api/auth.ts`, `api/admin.ts`, `api/crosspost.ts` | Zero unit tests (URL construction, parameter serialization untested) |
| `App.tsx` | Single trivial smoke test (no routing, auth, or error testing) |
| `useShareHandlers.ts` | Only tested indirectly through component integration |
| `MockHTTPError` class | Duplicated in 7+ test files -- should be a shared test utility |

---

## Summary

| Dimension | Rating | Notes |
|-----------|--------|-------|
| **Assertion quality** | Good | A few status-code-only assertions for mutations need body checks |
| **Error path testing** | Strong | Dedicated error-handling files are excellent; CSRF tamper and register-disabled are gaps |
| **Edge cases** | Good at unit level, thin at API level | Missing: concurrent slug collision, deep label hierarchies, large pagination, trusted proxy |
| **Workflow tests** | Moderate | Good multi-step auth/security tests; no full editorial or sync lifecycle test |
| **Property-based tests** | Strong with exceptions | Sync, DAG, path safety, and merge properties are excellent; 3 auth "property" tests are misused |
| **Coverage breadth** | Good | ~5 untested backend modules, 1 untested API endpoint, and the entire frontend API layer |

---

## Recommendations (Implementation Checklist)

### R1. Strengthen weak assertions in existing tests
- [ ] `test_update_page` — verify response body and re-fetch to confirm persistence
- [ ] `test_update_page_order` — fetch pages after update and verify order
- [ ] `test_search_special_characters` — assert result is a list
- [ ] `test_upload_new_file` — assert uploaded content matches download
- [ ] `test_flat_draft_markdown_returns_200_for_author` — assert draft content in response

### R2. Add missing error path tests
- [ ] CSRF tampered token test (wrong value, not missing)
- [ ] Registration disabled test (`self_registration=False`, `invites_enabled=False`)
- [ ] `token-login` rate limiting (exhaust to 429)
- [ ] Origin enforcement via `Referer` header fallback
- [ ] Admin service error paths at service unit level

### R3. Add missing edge case tests
- [ ] Very long post body via CRUD API
- [ ] Post with empty body (front matter only)
- [ ] Deeply nested label hierarchy (10+ levels) with descendant query
- [ ] Pagination with 20+ posts across multiple pages
- [ ] Rename collision counter (`-2`, `-3` suffix)
- [ ] Trusted proxy `X-Forwarded-For` for rate limiting

### R4. Add missing workflow tests
- [ ] Full editorial lifecycle: create -> labels -> preview -> edit -> publish -> delete
- [ ] Full bidirectional sync round-trip (multi-round)
- [ ] Admin page management lifecycle: create -> update -> reorder -> delete

### R5. Fix misused property-based tests
- [ ] Convert `st.just(None)` auth tests to proper unit tests or use meaningful strategies
- [ ] Strengthen `extract_title` property to verify heading extraction, not just non-emptiness

### R6. Add tests for untested endpoints and modules
- [ ] `DELETE /api/crosspost/accounts/{account_id}` (success, 404, 401)
- [ ] `GET /api/labels/{label_id}` 404 case
- [ ] `GET /api/auth/csrf` 401 case
- [ ] `csrf_service.validate_csrf_token()` unit tests
- [ ] `key_derivation.derive_csrf_token_key()` unit test
- [ ] `post_owner_service` unit tests (display-name dedup, collision)
- [ ] `page_service.get_page()` unit tests (no file, timeline)

### R7. Remove dead code
- [ ] Investigate `content_manager.build_index()` — if truly dead, remove it

### R8. Frontend improvements
- [ ] Extract shared `MockHTTPError` into a test utility
- [ ] Add unit tests for API layer parameter serialization (at least posts.ts and labels.ts)
