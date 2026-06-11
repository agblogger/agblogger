# Subscriptions

## Purpose

Email subscriptions let readers opt in to receive new posts via email. The feature is built around a store-zero-PII principle: AgBlogger persists no subscriber email addresses. Resend is the system of record for contacts and handles delivery and unsubscribe flows. AgBlogger stores only the non-PII configuration needed to orchestrate with Resend and a broadcast ledger that tracks outbound attempts.

## Architecture

The feature has three moving parts:

- a **Resend account** that owns the contact segment, broadcast delivery, and unsubscribe management
- a **backend subscription service** that orchestrates settings, stateless double opt-in, and broadcast firing
- a **frontend surface** for public subscription and admin management

Two durable Alembic-managed tables in the main database hold all local state:

- `subscription_settings` — singleton config row: enabled flag, Fernet-encrypted Resend API key, Resend segment id, sender identity, and GDPR compliance fields (controller name/contact, privacy policy URL, postal address).
- `subscription_broadcasts` — one ledger row per broadcast attempt: post path/title, Resend broadcast id, trigger (auto|manual), status (sent|failed), error. No recipient data.

## Stateless Double Opt-in

Subscribing creates no server-side pending row. Instead, the backend signs a short-lived PyJWT confirmation token carrying the normalized email address and emails a confirm link to the subscriber. The token is signed with a key derived from the app `SECRET_KEY` via `key_derivation.derive_subscribe_confirm_key`. The confirm endpoint verifies the token and, if valid, creates a Resend contact in the segment. A valid confirmation link may be reused until it expires; reopening it is treated as renewed consent. Unsubscribes are embedded in every broadcast email as Resend's `{{{RESEND_UNSUBSCRIBE_URL}}}` merge tag. Resend sends a signed unsubscribe webhook, and AgBlogger deletes the contact from Resend.

## Publish → Broadcast Flow

When a post transitions from draft to published (or is created as published), the publish hook in `backend/api/posts.py` fires a background task via `subscription_service.fire_post_broadcast`, gated on subscriptions being enabled. The task builds the post's HTML email from the already-sanitized rendered HTML and creates+sends a Resend broadcast to the segment.

## Email Layout & Rendering

`subscription_email.build_broadcast_email` wraps the rendered post HTML for delivery; it transforms only its email copy and never affects stored HTML or the web render path. The broadcast email has a visually separated header bar (View-online link + Unsubscribe), then the post title as a heading, then the post body, then the compliance footer (controller/address + Unsubscribe). Root-relative links/assets are rewritten to absolute URLs against the public post origin. Because email clients run no JavaScript, KaTeX cannot render client-side as it does on the web (see [editor.md](editor.md)/`useKatex`); instead `_render_math_images` rewrites Pandoc's `<span class="math …">` TeX into images from an external LaTeX service (`_MATH_IMAGE_BASE_URL`), with the raw TeX as `alt` so blocked images still read.

An `already_broadcast` once-guard (keyed on a prior `sent` ledger row for the post path) prevents a second automatic send per post. The admin's manual trigger bypasses the once-guard. Background broadcast work is bounded and drained on graceful shutdown so in-flight sends complete, mirroring the analytics shutdown pattern. Manual triggers receive a retryable error when background-task capacity is full, and the admin UI polls the ledger until the resulting attempt is visible.

## Enable Precondition

Enabling subscriptions requires a Resend API key, `from_email`, and a Resend webhook signing secret. The webhook secret is mandatory because unsubscribe events must delete the contact from Resend; processing failures return a retryable non-success response instead of acknowledging deletion. GDPR compliance fields (controller name, controller contact, privacy policy URL, postal address) are optional — the subscribe page renders each part of the GDPR notice conditionally based on what is configured. The first enable lazily auto-creates the Resend segment. Every settings update that leaves subscriptions enabled revalidates the resulting configuration, so required fields cannot be cleared while the feature is active. `EnablePreconditionError` is raised and mapped to HTTP 400 if required fields are missing; Resend API errors during settings updates also return HTTP 400 so the admin UI can surface a useful message.

## Built-in Privacy Policy

When no user-created `content/pages/privacy.md` exists, `GET /api/pages/privacy` returns a dynamically generated privacy policy page covering the email subscription data-processing practices (Resend as processor, consent lawful basis, EEA transfer, retention, user rights). Controller name and contact are HTML-escaped before being injected from subscription settings. The frontend shows a discreet "Privacy Policy" link in the footer whenever subscriptions are enabled.

## Security Model

- **No PII at rest**: subscriber emails are never stored locally; Resend is the sole custodian while subscribed.
- **Deletion on unsubscribe**: enabling requires a signed Resend webhook, and unsubscribe processing deletes the Resend contact.
- **API key encrypted at rest**: the Resend API key is Fernet-encrypted using the app `SECRET_KEY` via `crypto_service` and is never returned by any API endpoint or logged — responses expose only a `key_configured` boolean.
- **Confirm token signing**: tokens are signed with a `SECRET_KEY`-derived key; an expired or tampered token returns a generic failure page with no information leak.
- **No enumeration**: enabling-state aside, `POST /api/subscribe` does not reveal whether a given address is already subscribed — new and existing addresses both receive the same confirmation response, because `subscribe()` sends the confirmation without querying Resend's contact list.
- **Rate limiting**: `POST /api/subscribe` is rate-limited per IP (3/min burst, 10/hr sustained) to protect against confirmation-email abuse and Resend transactional quota exhaustion.
- **Controllership retained**: Resend acts as a data processor; the operator remains the GDPR data controller. The operator must sign Resend's DPA.

## API

- `POST /api/subscribe` — public, rate-limited, no-enumeration response.
- `GET /subscribe/confirm` — backend-served HTML page (registered before the SPA catch-all); verifies the token and creates the Resend contact.
- `GET /api/admin/subscriptions/settings` — admin-only settings read (never returns the API key).
- `PUT /api/admin/subscriptions/settings` — admin-only settings update + enable gate.
- `POST /api/admin/subscriptions/test` — send a test email (does not require `enabled=True`).
- `GET /api/admin/subscriptions/broadcasts` — broadcast ledger (last 100 attempts).
- `POST /api/admin/subscriptions/broadcasts` — manual broadcast trigger → 202 Accepted, or 503 when task capacity is full.

The public `GET /api/pages` site-config response exposes the subscription compliance object (with optional fields) when subscriptions are enabled; fields are null when not configured. The subscribe page renders each part of the GDPR notice conditionally. Broadcast email HTML rewrites root-relative post links and asset URLs to absolute URLs using the public post origin.

## Code Entry Points

- `backend/api/subscriptions.py` contains public, page, and admin routers.
- `backend/services/subscription_service.py` orchestrates settings, subscribe/confirm, broadcast firing, and the once-guard ledger.
- `backend/services/resend_client.py` is the shared async HTTP boundary over the Resend API; contact counts follow Resend cursor pagination, and the client is closed on app shutdown.
- `backend/services/subscription_email.py` builds confirmation and broadcast email HTML/text payloads.
- `backend/services/subscription_tokens.py` handles signed token creation and verification for stateless double opt-in.
- `backend/models/subscription.py` defines the `SubscriptionSettings` and `SubscriptionBroadcast` durable models.
- `backend/migrations/versions/0006_subscription_tables.py` is the Alembic migration for both tables.
- `frontend/src/pages/SubscribePage.tsx` is the public opt-in form with GDPR layered notice.
- `frontend/src/components/admin/SubscriptionsPanel.tsx` is the admin tab for settings, enable toggle, subscriber count, test email, manual broadcast, and broadcast history. It loads all post-list pages for the manual picker and refreshes shared site config after toggles.
