# Cross-Posting

## Purpose

Cross-posting lets AgBlogger publish a blog post to external social platforms while keeping the AgBlogger post as the canonical source of truth. External posts are treated as derived distribution artifacts, not as primary content records.

## Architecture

The feature is built around a provider-adapter model:

- the application exposes a common publishing workflow
- provider-specific adapters encapsulate platform OAuth, token lifecycle, and publication behavior
- a service layer prepares publishable content from the canonical post and records publication results

This keeps provider churn and provider-specific rules from leaking across the rest of the application.

## Security and Ownership Boundaries

Connected accounts are user-scoped. Credentials are encrypted at rest, decrypted only for active operations, and kept behind the backend trust boundary. Cross-post history is also scoped to the owning user, so one user’s integrations do not become shared application state.

## Content Relationship

Cross-post payloads are derived from AgBlogger content such as the post title, excerpt, canonical URL, and user-supplied publishing context. The external platform receives a transformed view of an existing post; it does not become an alternative editing surface for the blog itself.

## UI Placement

The UI exposes cross-posting in the places where it naturally belongs:

- account and provider connection management
- publication actions for individual posts
- history and status views for prior external publications

That separation mirrors the architecture: connection management, publication, and publication history are related but distinct concerns.

## Code Entry Points

- `backend/api/crosspost.py` exposes the HTTP boundary for connected accounts and publishing actions.
- `backend/services/crosspost_service.py` orchestrates publication, account lookup, and result persistence.
- `backend/crosspost/` contains the provider registry plus platform-specific adapters and OAuth helpers.
- `frontend/src/api/crosspost.ts` and the relevant page components in `frontend/src/pages/` contain the browser-facing integration points.
