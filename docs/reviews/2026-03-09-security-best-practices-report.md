# Security Best Practices Report

Date: 2026-03-09
Reviewer: Codex using `security-best-practices`

## Executive Summary

AgBlogger's baseline security posture is strong for a self-hosted app. The codebase has solid defenses around cookie handling, CSRF, draft authorization, HTML sanitization, active-content serving, SSRF protection for attacker-influenced outbound requests, and production fail-fast checks for core secrets.

This review did not find any current Critical or High severity issues in the checked-in code. I found 3 actionable remaining issues:

1. One Medium issue in the sync surface that exposes secret material stored inside `content/`.
2. Two Low severity hardening gaps in production configuration validation.

This pass was a manual source review of the repository contents. I did not run live DAST or dependency-audit commands during this review.

## Medium Severity

### SBP-001: Sync API permits remote access to hidden files in `content/`, including the ATProto OAuth private key

- Severity: Medium
- Impact: Any admin session or admin PAT can remotely download, overwrite, or delete secret files stored under `content/`, including the ATProto OAuth private key. That enables compromise or forced reset of Bluesky OAuth identity and expands the remotely reachable secret surface beyond normal blog content.
- Location:
  - `backend/main.py:206`
  - `backend/api/sync.py:47`
  - `backend/api/sync.py:168`
  - `backend/api/sync.py:175`
  - `backend/api/sync.py:182`
  - `backend/api/sync.py:245`
  - `backend/api/sync.py:246`
  - `backend/api/sync.py:266`
- Evidence:
  - The ATProto keypair is stored at `settings.content_dir / ".atproto-oauth-key.json"` in `backend/main.py:206`.
  - `_resolve_safe_path()` in `backend/api/sync.py:47-53` only checks traversal; it does not block dotfiles or other sensitive non-content paths.
  - `GET /api/sync/download/{file_path}` returns `FileResponse(full_path)` for any path accepted by `_resolve_safe_path()` (`backend/api/sync.py:168-179`).
  - `POST /api/sync/commit` uses the same helper for deletions and uploaded filenames, so hidden files can also be deleted or overwritten remotely (`backend/api/sync.py:245-250`, `backend/api/sync.py:266-267`).
- Why this is vulnerable:
  - The normal sync scanner intentionally skips dotfiles, but the download and commit endpoints do not. That means hidden files are not part of the intended sync set, yet they remain directly reachable if a caller knows or guesses the path.
- Fix:
  - Restrict sync to an explicit allowlist of sync-managed paths, for example `index.toml`, `labels.toml`, `about.md`, `pages/*.md`, `posts/**`, and `assets/**`.
  - Explicitly reject dotfiles and other secret-bearing paths such as `.atproto-oauth-key.json`.
  - Move OAuth private key material out of the content tree entirely so content-sync APIs can never touch it.
- Mitigation:
  - Treat admin PATs as highly privileged and rotate the ATProto OAuth key if there is any chance the sync API has been exposed to untrusted admin credentials.
- False positive notes:
  - This requires admin-level access; it is not a public unauthenticated exposure. The issue is that the remote admin API currently reaches secret material that is not part of normal content synchronization.

## Low Severity

### SBP-002: Production `TRUSTED_HOSTS` validation can be satisfied by permissive wildcard hosts

- Severity: Low
- Impact: A deployment can pass the app's production startup checks while still effectively disabling Host-header protection. That re-opens Host-header abuse and weakens logic that derives trusted origin information from the request host.
- Location:
  - `backend/config.py:87`
  - `backend/config.py:99`
  - `backend/main.py:310`
  - `backend/main.py:314`
- Evidence:
  - `Settings.validate_runtime_security()` only checks that `trusted_hosts` is non-empty (`backend/config.py:92-104`).
  - `create_app()` passes `trusted_hosts` directly to `TrustedHostMiddleware` (`backend/main.py:310-314`).
- Why this is vulnerable:
  - The code enforces presence, but not quality. A permissive wildcard configuration can satisfy the fail-fast guard while removing the intended protection.
- Fix:
  - In non-debug mode, reject catch-all or overly broad wildcard host entries during settings validation.
  - Accept only explicit hostnames/IPs, plus narrowly scoped subdomain wildcards if there is a documented need.
- Mitigation:
  - Review deployed `TRUSTED_HOSTS` values and ensure they are explicit concrete hosts.
- False positive notes:
  - This is a misconfiguration-hardening issue rather than a shipped default exposure. It matters because the code currently treats any non-empty value as secure enough.

### SBP-003: OAuth public base URL is used directly without HTTPS/origin validation

- Severity: Low
- Impact: A production misconfiguration can silently generate OAuth redirect URIs and post-auth redirects on plain HTTP or an unintended host, increasing the risk of authorization-code leakage or credential delivery to the wrong origin.
- Location:
  - `backend/config.py:57`
  - `backend/api/crosspost.py:259`
  - `backend/api/crosspost.py:299`
  - `backend/api/crosspost.py:369`
  - `backend/api/crosspost.py:459`
  - `backend/api/crosspost.py:622`
  - `backend/api/crosspost.py:644`
  - `backend/api/crosspost.py:787`
- Evidence:
  - `bluesky_client_url` is a plain string setting with no structural validation in `backend/config.py:57-104`.
  - Cross-post OAuth endpoints call `settings.bluesky_client_url.rstrip("/")` and interpolate it directly into client metadata, redirect URIs, and admin redirects across Bluesky, Mastodon, X, and Facebook flows.
- Why this is vulnerable:
  - The code checks presence, not safety. A production operator can accidentally configure `http://...`, the wrong hostname, or a URL with extra path components, and the app will still build OAuth flows from it.
- Fix:
  - Validate this setting at startup as a canonical public origin: `https://host[:port]` only in production, with no path, query, fragment, or userinfo.
  - Allow `http://localhost` only in debug/test scenarios if needed.
  - Consider renaming it to something like `public_base_url` to match how broadly it is used.
- Mitigation:
  - Audit deployed OAuth-related base URL settings and ensure they point to the exact public HTTPS origin of the app.
- False positive notes:
  - Some providers may independently reject insecure redirect URIs. The hardening gap remains because the application itself does not enforce the expected security properties.

## Positive Controls Observed

- Auth cookies are `HttpOnly`, `SameSite=Strict`, and `Secure` outside debug: `backend/api/auth.py:57-83`
- Unsafe cookie-authenticated API requests are CSRF-protected in middleware: `backend/main.py:351-385`
- Login origin enforcement and browser rejection of token-login are present: `backend/api/auth.py:111-136`
- Draft posts and draft assets use author-only checks with `404` on unauthorized access: `backend/api/content.py:64-117`, `backend/api/posts.py:598-616`
- Rendered HTML is sanitized before frontend insertion, and active content types are forced to download from `/api/content/*`: `backend/pandoc/renderer.py:108-228`, `backend/api/content.py:130-155`
- Attacker-influenced outbound HTTP paths for Mastodon and ATProto flows use SSRF-aware clients: `backend/crosspost/ssrf.py:1-116`, `backend/crosspost/mastodon.py:59-97`, `backend/crosspost/atproto_oauth.py:299-375`

## Recommended Remediation Order

1. Lock down sync to sync-managed content only and remove secret files from the sync surface.
2. Tighten production validation for `TRUSTED_HOSTS`.
3. Validate the OAuth/public base URL as a canonical HTTPS origin at startup.
