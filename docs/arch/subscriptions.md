# Subscriptions

## Purpose

Email subscriptions let readers opt in to receive new posts via email. The feature is built around a store-zero-PII principle: AgBlogger persists no subscriber email addresses. Resend is the system of record for contacts and handles delivery and unsubscribe flows. AgBlogger stores only the non-PII configuration needed to orchestrate with Resend and a broadcast ledger that tracks outbound attempts.

## Architecture

The feature has three moving parts:

- a **Resend account** that owns the contact segment, broadcast delivery, and unsubscribe management
- a **backend subscription service** that orchestrates settings, stateless double opt-in, and broadcast firing
- a **frontend surface** for public subscription and admin management

All local state lives in two durable Alembic-managed tables: a singleton settings row (enabled flag, encrypted Resend API key, segment id, sender identity, and optional GDPR compliance fields) and a broadcast ledger with one row per send attempt — post reference, trigger, status, and error, but never recipient data.

The HTTP surface follows the same split: a public rate-limited subscribe endpoint and a backend-served confirmation page, plus admin-only endpoints for settings, test sends, the broadcast ledger, and manual broadcast triggers.

## Stateless Double Opt-in

Subscribing creates no server-side pending row. Instead, the backend signs a short-lived confirmation token carrying the normalized email address and emails a confirm link to the subscriber. The confirm endpoint verifies the token and, if valid, creates a Resend contact in the segment. A valid confirmation link may be reused until it expires; reopening it is treated as renewed consent.

Unsubscribing is delegated to Resend: every broadcast email embeds Resend's unsubscribe link, and Resend notifies AgBlogger through a signed webhook, upon which the backend deletes the contact from Resend.

## Publish → Broadcast Flow

When a post transitions from draft to published (or is created as published), the publish path fires a background broadcast task, gated on subscriptions being enabled. The task builds the post's email from the already-sanitized rendered HTML and creates and sends a Resend broadcast to the segment.

A once-guard keyed on the ledger prevents a second automatic send per post; post renames update ledger references so the guard survives path changes, while the admin's manual trigger bypasses it. Background broadcast work is bounded and drained on graceful shutdown so in-flight sends complete, mirroring the analytics shutdown pattern. Manual triggers receive a retryable error when background-task capacity is full, and the admin UI polls the ledger until the resulting attempt is visible.

The broadcast is created and sent in two sequential Resend API calls. If create succeeds but the send call fails, a `BroadcastSendError` (carrying the broadcast id) is raised and the ledger row records the id alongside the failed status — preventing the orphan from being unrecoverable. Manual retrigger after this partial failure carries a double-send risk; operators should verify the Resend dashboard before retrying.

## Email Rendering

Broadcast email construction wraps the rendered post HTML for delivery only — it never affects stored HTML or the web render path. The email layout is a header bar (view-online link and unsubscribe), the post title, the post body, and a compliance footer. Root-relative links and assets are rewritten to absolute URLs against the public post origin.

Because email clients run no JavaScript, KaTeX cannot render client-side as it does on the web (see [editor.md](editor.md)); math spans are instead rewritten into images served by an external LaTeX rendering service (`latex.codecogs.com`), with the raw TeX as alt text so blocked images still read. This involves a tradeoff: the image request leaks the reader's IP to the third-party service and acts as an open-tracking signal; availability depends on the external service. No alternative local rendering path exists.

## Enable Precondition

Enabling subscriptions requires a Resend API key, a sender address, and a Resend webhook signing secret. The webhook secret is mandatory because unsubscribe events must delete the contact from Resend; webhook processing failures return a retryable non-success response instead of acknowledging deletion. GDPR compliance fields (controller name, controller contact, privacy policy URL, postal address) are optional — the subscribe page renders each part of the GDPR notice conditionally based on what is configured, and the public site config exposes the compliance object only while subscriptions are enabled.

The first enable lazily auto-creates the Resend segment. Every settings update that leaves subscriptions enabled revalidates the resulting configuration, so required fields cannot be cleared while the feature is active. Missing-field and Resend API errors during settings updates surface as client errors so the admin UI can show a useful message.

## Built-in Privacy Policy

When no user-created `content/pages/privacy.md` exists, the pages API serves a dynamically generated privacy policy covering the email subscription data-processing practices (Resend as processor, consent lawful basis, EEA transfer, retention, user rights), with operator details injected from subscription settings. The frontend shows a discreet "Privacy Policy" link in the footer whenever subscriptions are enabled.

## Security Model

- **No PII at rest**: subscriber emails are never stored locally; Resend is the sole custodian while subscribed.
- **Deletion on unsubscribe**: enabling requires a signed Resend webhook, and unsubscribe processing deletes the Resend contact.
- **API key encrypted at rest**: the Resend API key is encrypted with a key derived from the app secret and is never returned by any API endpoint or logged — responses expose only whether a key is configured.
- **Confirm token signing**: confirmation tokens are signed with a key derived from the app secret; an expired or tampered token returns a generic failure page with no information leak.
- **No enumeration**: the public subscribe endpoint does not reveal whether an address is already subscribed — new and existing addresses receive the same confirmation response.
- **Rate limiting**: the public subscribe endpoint is rate-limited per IP to protect against confirmation-email abuse and Resend quota exhaustion.
- **Controllership retained**: Resend acts as a data processor; the operator remains the GDPR data controller and must sign Resend's DPA.

## Code Entry Points

- `backend/api/subscriptions.py` contains the public, confirmation-page, and admin routers.
- `backend/services/subscription_service.py` orchestrates settings, subscribe/confirm, broadcast firing, and the once-guard ledger.
- `backend/services/resend_client.py` is the shared async HTTP boundary over the Resend API.
- `backend/services/subscription_email.py` builds confirmation and broadcast email payloads.
- `backend/services/subscription_tokens.py` handles signed token creation and verification for stateless double opt-in.
- `backend/models/subscription.py` defines the durable settings and broadcast-ledger models.
- `frontend/src/pages/SubscribePage.tsx` is the public opt-in form with the layered GDPR notice.
- `frontend/src/components/admin/SubscriptionsPanel.tsx` is the admin tab for settings, the enable toggle, subscriber count, test email, manual broadcast, and broadcast history.
