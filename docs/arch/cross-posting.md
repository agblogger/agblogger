# Cross-Posting

## Purpose

Cross-posting lets AgBlogger publish a blog post to external social platforms while keeping the AgBlogger post as the canonical source of truth. External posts are treated as derived distribution artifacts, not as primary content records.

## Architecture

The feature is built around a provider-adapter model:

- the application exposes a common publishing workflow
- provider-specific adapters encapsulate platform OAuth, token lifecycle, and publication behavior
- a service layer prepares publishable content from the canonical post and records publication results

Provider-specific rules stay inside adapters and services.

## Security and Ownership Boundaries

Connected accounts are user-scoped. Credentials are encrypted at rest, decrypted only for active operations, and kept behind the backend trust boundary. Cross-post history is also scoped to the owning user, so one user’s integrations do not become shared application state.

## Content Relationship

Cross-post payloads are derived from AgBlogger content such as the post title, excerpt, canonical URL, and user-supplied publishing context. The external platform receives a transformed view of an existing post; it is not an alternative editing surface for the blog.

## UI Placement

The UI exposes cross-posting in three places:

- account and provider connection management in the admin social tab
- publication actions for individual posts, using explicit cross-post wording that stays distinct from the public share UI
- history and status views for prior external publications, including a direct path to connect accounts when none are available

The admin social tab presents both connected accounts and available connection options in alphabetical order by displayed platform name, while each connected row still shows the linked account handle or page name as secondary identity information.

The post-view cross-post section surfaces backend/API load failures to the user instead of silently hiding controls. When no social accounts are connected, the empty state includes a direct link to the admin social tab so authors can connect an account and return to cross-post the current post.

Draft posts are not eligible for browser-side distribution actions. The web UI disables both sharing controls and cross-post actions for drafts, and the editor disables "cross-post after saving" while the draft flag is enabled. Authors must publish the post before sharing or cross-posting.

These are related but distinct concerns.

## Code Entry Points

- `backend/api/crosspost.py` exposes the HTTP boundary for connected accounts and publishing actions.
- `backend/services/crosspost_service.py` orchestrates publication, account lookup, and result persistence.
- `backend/crosspost/` contains the provider registry plus platform-specific adapters and OAuth helpers.
- `frontend/src/api/crosspost.ts` and the relevant page components in `frontend/src/pages/` contain the browser-facing integration points.
