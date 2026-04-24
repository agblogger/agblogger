# Testing

## Strategy

AgBlogger’s testing architecture mirrors the application architecture:

- API-level tests validate behavior at the HTTP boundary
- service-level tests validate business logic and failure handling
- content and rendering tests validate the markdown pipeline
- CLI tests validate operational tooling
- frontend tests validate route behavior, state management, and user workflows

The focus is boundary behavior, not only narrow implementation-level unit tests.

## Backend

Backend testing emphasizes correctness at the boundaries that matter most for the system:

- content mutations and reads
- failure handling and graceful degradation
- security-sensitive behavior
- sync, rendering, and integration workflows

Because the filesystem is authoritative, backend tests focus heavily on preserving content correctly even when caches, external tools, or integrations fail.

## Frontend

Frontend testing focuses on user-visible behavior in the SPA: navigation, editor workflows, authenticated flows, and UI logic layered on top of backend-rendered content.

## Property-Based and Higher-Invariant Tests

Where the codebase has deterministic, high-invariant logic, tests favor property-based coverage and other approaches that validate whole classes of behavior instead of a small set of fixed examples.

## Code Entry Points

- `tests/test_api/` covers HTTP-level backend behavior.
- `tests/test_services/`, `tests/test_rendering/`, `tests/test_labels/`, and `tests/test_sync/` cover core backend subsystems.
- `frontend/src/**/__tests__/` and `frontend/src/**/*.test.ts*` cover the SPA.
- `tests/test_cli/` covers operational tooling, including quality-gate helper CLIs such as the locked runtime dependency audit.
- `justfile` defines the repository-level validation gates.
