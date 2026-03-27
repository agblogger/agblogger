# Security

## Security Model

AgBlogger uses a defense-in-depth model built around a few primary trust boundaries:

- the browser or API client boundary
- the application boundary
- the content filesystem boundary
- external services such as OAuth providers and social platforms
- the deployment and ingress boundary

Security controls are layered so a failure in one area does not automatically compromise the rest of the system.

## Identity and Session Security

Browser authentication is cookie-based, CSRF protection is required for unsafe browser actions, and long-lived browser-readable credentials are avoided. Short-lived bearer tokens (via the token-login endpoint) exist for non-browser clients so CLI workflows do not need to reuse the browser session model. Startup also enforces the single-admin invariant in durable auth state, collapsing stale admin rows and revoking stale refresh sessions before the app begins serving traffic.

## Authorization Boundaries

Authorization is enforced at the API boundary. Published content is broadly readable, while mutations are concentrated behind admin authentication and admin-scoped account boundaries. Draft content is treated as non-public content rather than merely unpublished public content.

## Content Security

User-authored content is treated as untrusted input. Rendering and sanitization happen on the server, and asset access stays behind controlled application routes instead of direct filesystem exposure.

## Filesystem and Sync Boundaries

Filesystem access is constrained to managed content paths, and sync exposes only the subset of the content tree that belongs to the portable authoring model. Private runtime state and hidden files are outside that boundary.

## External Integration Security

External providers are treated as untrusted systems. Their credentials are protected at rest, provider-specific behavior is isolated behind adapters and services, and external failures are prevented from redefining core content ownership or application identity boundaries.

## Runtime Hardening

Production hardening combines application and deployment controls: startup validation of critical security settings, controlled proxy and host boundaries, hardened HTTP behavior, and container-oriented deployment practices that minimize exposed surface area.

## Verification Strategy

Security verification is spread across multiple layers:

- static analysis and dependency auditing of the shipped runtime dependency set
- focused regression tests for security-sensitive behavior
- deployment-style dynamic scanning outside the normal development server path

Security checks are part of normal engineering workflow rather than a separate late-stage review.

## Code Entry Points

- `backend/config.py` contains runtime security configuration and startup validation.
- `backend/main.py` wires up security-relevant middleware and global request handling.
- `backend/api/deps.py` contains shared authorization dependencies.
- `backend/services/csrf_service.py` and `backend/services/rate_limit_service.py` cover request-boundary protections.
- `backend/crosspost/ssrf.py` and related integration code cover external-request hardening for provider integrations.
