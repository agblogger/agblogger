# Subscriptions

## Purpose

Email subscriptions let readers opt in to receive new posts via email. The feature is built around a store-zero-PII principle: AgBlogger persists no subscriber email addresses. Resend is the system of record for contacts and handles delivery and unsubscribe flows. AgBlogger stores only the non-PII configuration needed to orchestrate with Resend and a broadcast ledger that tracks outbound attempts.

## Architecture

The feature has three moving parts:

- a **Resend account** that owns the contact segment, broadcast delivery, and unsubscribe management
- a **backend subscription service** that orchestrates settings, stateless double opt-in, and broadcast firing
- a **frontend surface** for public subscription and admin management

All local state lives in two durable Alembic-managed tables: a singleton settings row (enabled flag, encrypted Resend API key and webhook signing secret, segment id, sender identity, and optional GDPR compliance fields) and a broadcast ledger with one row per send attempt — post reference, trigger, status, and error, but never recipient data.

The HTTP surface follows the same split: a public rate-limited subscribe endpoint and a backend-served confirmation page, plus admin-only endpoints for settings, test sends, the broadcast ledger, and manual broadcast triggers.

## Stateless Double Opt-in

Subscribing creates no server-side pending row. Instead, the backend signs a short-lived confirmation token carrying the normalized email address and emails a confirm link to the subscriber. The confirm endpoint verifies the token and, if valid, creates a Resend contact in the segment. A valid confirmation link may be reused until it expires; reopening it is treated as renewed consent.

Unsubscribing is delegated to Resend: every broadcast email embeds Resend's unsubscribe link. When the optional signed webhook is configured, Resend also notifies AgBlogger so the backend can permanently delete the unsubscribed contact from Resend.

## Publish → Broadcast Flow

When a post transitions from draft to published (or is created as published), the publish path fires a background broadcast task, gated on subscriptions being enabled. The task builds the post's email from the already-sanitized rendered HTML and creates and sends a Resend broadcast to the segment.

A once-guard keyed on the ledger prevents a second automatic send per post; post renames update ledger references so the guard survives path changes, while the admin's manual trigger bypasses it. Background broadcast work is bounded and drained on graceful shutdown so in-flight sends complete, mirroring the analytics shutdown pattern. Manual triggers receive a retryable error when background-task capacity is full. The admin UI treats the trigger response as queue acknowledgement, polls the ledger for completion, briefly confirms successful delivery, and directs the operator to the history when completion is not observed during polling.

The broadcast is created and sent in two sequential Resend API calls. If create succeeds but the send call fails, a `BroadcastSendError` (carrying the broadcast id) is raised and the ledger row records the id alongside the failed status — preventing the orphan from being unrecoverable. Manual retrigger after this partial failure carries a double-send risk; operators should verify the Resend dashboard before retrying.

## Email Rendering

Broadcast email construction wraps the rendered post HTML for delivery only — it never affects stored HTML or the web render path. The email layout is a header bar (view-online link and unsubscribe), the post title, the post body, and a compliance footer. Root-relative links and assets are rewritten to absolute URLs against the public post origin. Fragment links, including footnote references and backlinks, are rewritten to the online post URL because email clients do not reliably support links within an email document.

Because email clients run no JavaScript, KaTeX cannot render client-side as it does on the web (see [editor.md](editor.md)); math spans are instead rewritten into images served by an external LaTeX rendering service (`latex.codecogs.com`), with the raw TeX as alt text so blocked images still read. Images are requested at a high DPI and downsampled with CSS (inline math pinned to the text line height, display math capped to the body width) so formulas stay sharp on the high-density screens where most email is read. This involves a tradeoff: the image request leaks the reader's IP to the third-party service and acts as an open-tracking signal; availability depends on the external service. No alternative local rendering path exists.

## Enable Precondition

Enabling subscriptions requires only a Resend API key and sender address from the operator. AgBlogger attempts to register its `contact.unsubscribed` endpoint through the Resend API and encrypts the provider-generated signing secret with the application secret. Resend generates the signing secret because Resend signs webhook requests; it cannot be independently derived by AgBlogger. Webhook setup is best-effort because Resend requires a public HTTPS endpoint: localhost and temporary provider failures do not block subscribing, confirmation, test emails, or broadcasts. While the webhook is missing, the admin panel warns that unsubscribed contacts will not be automatically deleted from Resend. GDPR compliance fields (controller name, controller contact, privacy policy URL, postal address) are optional — the subscribe page renders each part of the GDPR notice conditionally based on what is configured, and the public site config exposes the compliance object only while subscriptions are enabled.

The first enable lazily auto-creates the Resend segment and attempts to create the unsubscribe webhook. If the current URL is not HTTPS, webhook registration is skipped without calling Resend. If registration fails or was skipped, every later settings update that leaves subscriptions enabled retries when the request uses HTTPS. Every enabled settings update also revalidates the required API key and sender address, so those fields cannot be cleared while the feature is active. Missing-field and required Resend-resource errors surface as client errors so the admin UI can show a useful message.

## Built-in Privacy Policy

When no user-created `content/pages/privacy.md` exists, the pages API serves a dynamically generated privacy policy covering the email subscription data-processing practices (Resend as processor, consent lawful basis, EEA transfer, retention, user rights), with operator details injected from subscription settings. The frontend shows a discreet "Privacy Policy" link in the footer whenever subscriptions are enabled.

## Security Model

- **No PII at rest**: subscriber emails are never stored locally; Resend is the sole custodian while subscribed.
- **Deletion on unsubscribe**: when the signed Resend webhook is configured, unsubscribe processing permanently deletes the Resend contact; the admin sees a warning while this cleanup is unavailable.
- **Provider credentials encrypted at rest**: the Resend API key and provider-generated webhook signing secret are encrypted with a key derived from the app secret and are never returned by any API endpoint or logged — responses expose only whether each value is configured.
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
