# PR Review Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all 14 issues identified in docs/reviews/2026-03-10-comprehensive-pr-review.md

**Architecture:** Grouped into 4 categories: quick non-code fixes (docs/comments/trivial), rename/refactor, behavioral changes requiring TDD, and new test coverage.

**Tech Stack:** Python (FastAPI, pytest), shell, markdown

---

## Group A: Quick Fixes (no TDD)

### Task 1: CR-4 — Remove duplicate Path import in test_config.py
- Modify: `tests/test_services/test_config.py:5-10`
- Remove the `TYPE_CHECKING` block (lines 5-8) since `Path` is already imported unconditionally on line 10.

### Task 2: CR-1 — Fix docker-entrypoint.sh chown suppression
- Modify: `docker-entrypoint.sh:9`
- Replace `chown -R ... 2>/dev/null || true` with logged warning pattern.

### Task 3: CR-9 — Annotate security best practices report as resolved
- Modify: `docs/reviews/2026-03-09-security-best-practices-report.md`
- Add remediation status after Executive Summary marking all 3 findings as resolved.

### Task 4: CR-13 — Add `assets/` to sync surface documentation
- Modify: `docs/arch/sync.md:13`, `docs/arch/security.md:280`, `docs/guidelines/security.md:144`

### Task 5: CR-14 — Add comment for ZAP scanner ID 40026
- Modify: `cli/zap_hooks.py:12-13`

### Task 6: CR-7 — Improve chmod failure warning in deploy script
- Modify: `cli/deploy_production.py:569-572`

## Group B: Rename/Refactor (TDD — update existing tests)

### Task 7: CR-6 — Rename `_sqlite_database_path` to public
- Modify: `backend/config.py:47`, `backend/main.py:34`, `tests/test_services/test_config.py:12,39`
- Rename `_sqlite_database_path` → `sqlite_database_path` everywhere.

### Task 8: CR-5 — Extract shared `is_valid_trusted_host` function
- Create: `backend/validation.py` with the shared function
- Modify: `backend/config.py:19-29` — import from `backend.validation`
- Modify: `cli/deploy_production.py:254-264` — import from `backend.validation`
- Test: Add unit tests in `tests/test_services/test_validation.py`

## Group C: Behavioral Changes (TDD)

### Task 9: CR-2 — `_wait_for_healthy` raises on timeout
- Test: `tests/test_cli/test_deploy_production.py` — write failing test that expects `DeployError` on timeout
- Modify: `cli/deploy_production.py:867-870` — raise `DeployError` instead of printing warning

### Task 10: CR-3 — Wrap zap_scan cleanup in try-except
- Test: `tests/test_cli/test_zap_scan.py` — write failing test where cleanup raises but original error preserved
- Modify: `cli/zap_scan.py:286-288` — wrap in try-except

### Task 11: CR-8 — Log malformed trusted proxy IPs
- Test: `tests/test_api/test_security_regressions.py` — write failing test checking log output
- Modify: `backend/api/auth.py:107-108` — add logger.warning

## Group D: New Test Coverage

### Task 12: CR-10 — Add negative tests for `is_sync_managed_path`
- Test: `tests/test_services/test_sync_service.py` — new `TestIsSyncManagedPath` class

### Task 13: CR-11 — Add comprehensive `sqlite_database_path` tests
- Test: `tests/test_services/test_config.py` — expand test coverage

### Task 14: CR-12 — Add CIDR integration test for trusted proxy
- Test: `tests/test_api/test_security_regressions.py` — new test in `TestTrustedProxyForwarding`
