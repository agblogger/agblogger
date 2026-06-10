# Email Subscriptions — Design Spec

**Date:** 2026-06-10
**Status:** Approved for planning

## 1. Overview

Add an email subscription mechanism to AgBlogger where **the email provider (Resend) is the
system of record for subscriber email addresses — AgBlogger stores none of them.** Public
readers subscribe via confirmed (double) opt-in; on confirmation their address is written
directly into a Resend **Segment** (formerly "Audience"). When a post is published, AgBlogger
asks Resend to send a **Broadcast** containing the post's rendered HTML to that Segment;
Resend fans out delivery and manages unsubscribes. An admin-panel tab configures the feature.

This is not legal advice: the software is built to **support** GDPR/ePrivacy compliance, but
full compliance also depends on operator actions outside the code (a signed Data Processing
Agreement with Resend, a published privacy policy, and correct handling of data-subject
requests). Note that under this design **Resend is both the processor and the store** of
subscriber data.

## 2. Core principle — store zero subscriber PII

AgBlogger never persists subscriber email addresses. Emails are handled only **transiently**
(forwarded to Resend during subscribe/confirm) and never written to any AgBlogger database.
What we store locally is strictly **non-PII**: the encrypted Resend API key, the Resend
segment id, sender + compliance settings, and a broadcast ledger that references Resend
broadcast ids (not recipients).

Consequences vs. a self-hosted list: there is **no separate subscriptions database, no second
engine, no subscribers table, no unsubscribe tokens/endpoints, no per-recipient send loop,
and no suppression list** — Resend owns all of that.

## 3. Verified Resend capabilities (June 2026)

- **Contacts/Segments:** create a contact (email, optional first/last name, `unsubscribed`,
  properties, `segments`) via API. Creation is immediate; **no native double opt-in**.
- **Broadcasts:** `create` with `segmentId`, `from`, `subject`, `html`/`text`, and `send: true`
  sends in one request (or `scheduledAt` to schedule); returns a broadcast id.
- **Managed unsubscribe:** including `{{{RESEND_UNSUBSCRIBE_URL}}}` in the HTML makes Resend
  handle the unsubscribe flow and **skip unsubscribed contacts** on later broadcasts.

(Sources: Resend Contacts API, Broadcasts API, and Audiences/Broadcasts product docs.)

## 4. Goals / Non-goals

**Goals**
- Public confirmed-opt-in subscribe flow with a layered GDPR notice, storing no PII locally.
- Stateless double opt-in (no pending storage) via a signed confirmation token.
- Contact written to a Resend Segment on confirmation.
- Auto-broadcast on the web-editor publish transition (once per post) + manual admin trigger.
- Admin panel: enable/disable, live subscriber count (read from Resend), manual send, Resend
  key + sender + compliance config, broadcast history.

**Non-goals (v1)**
- Self-hosting the subscriber list or unsubscribe (delegated to Resend).
- Per-recipient retry/tracking on our side (Resend owns delivery; we keep a per-broadcast
  reference + optional stats read-back).
- Auto-send for posts published outside the web editor (sync/CLI/git) — manual trigger only.
- Segmentation, scheduling beyond "send now", multiple newsletters.

## 5. Architecture

### 5.1 No separate database
All locally-stored state is **non-PII config** and lives in the **main durable DB**
(Alembic-managed):
- a singleton `subscription_settings` row, and
- a thin `subscription_broadcasts` ledger.

The earlier separate-file/second-engine design is dropped: its only justification was
isolating a subscriber-email write path, which no longer exists.

### 5.2 Stateless double opt-in
On subscribe we persist nothing. The confirmation link carries a **signed token** — payload
`{email, issued_at}` signed with `SECRET_KEY` (HMAC-SHA256 / `itsdangerous`-style), expiring
in ~24–48h. The token exists only inside the confirmation email and the confirm URL. On
click we verify signature + expiry and **then** create the Resend contact. The
confirmation-link click is the unambiguous affirmative action proving consent + ownership
(GDPR Art. 4(11)); the resulting Resend contact (with its created-at) is the consent record
(Art. 7(1)). Confirming is idempotent (re-creating an existing contact is harmless).

### 5.3 Broadcast via Resend
Publishing (or a manual trigger) builds the email HTML and issues one Resend `create-broadcast`
call with `send: true`. Resend handles fan-out, the unsubscribe flow, and suppression. We
record the returned broadcast id locally for the once-guard and admin history.

## 6. Data model — main durable DB (no PII)

### `subscription_settings` (singleton, `id = 1`, CheckConstraint)
| column | type | notes |
| --- | --- | --- |
| `id` | int PK = 1 | |
| `enabled` | bool | gates the public subscribe surface |
| `resend_api_key_encrypted` | text, nullable | Fernet via `crypto_service`; never returned |
| `resend_segment_id` | text, nullable | target Segment; auto-created on first enable if absent |
| `from_email` | text, nullable | verified Resend sender |
| `from_name` | text, nullable | display name |
| `controller_name` | text, nullable | data controller identity (Art. 13) |
| `controller_contact` | text, nullable | contact for rights requests |
| `privacy_policy_url` | text, nullable | layered-notice link target |
| `postal_address` | text, nullable | email footer (CAN-SPAM) |
| `updated_at` | text | |

**Enable precondition.** `enabled = true` is only accepted when *all* of these are present:
configured API key, `resend_segment_id` (or auto-created at that moment), `from_email`,
`controller_name`, `controller_contact`, `privacy_policy_url`, `postal_address`. Compliant
collection is therefore a structural invariant.

### `subscription_broadcasts` (ledger, no PII)
| column | type | notes |
| --- | --- | --- |
| `id` | int PK | |
| `post_path` | text, NOT NULL | canonical post file_path at send time |
| `post_title` | text | snapshot |
| `resend_broadcast_id` | text, nullable | id returned by Resend |
| `trigger` | text | `auto` \| `manual` |
| `status` | text | `sent` \| `failed` |
| `sent_at` | text | |
| `error` | text, nullable | |

The once-guard checks for an existing `sent` row for the `post_path`; manual trigger ignores
it. Post identity is the path-at-send-time (no stable UUID; renames don't rematch).

## 7. API surface

### Public (unauthenticated)
- `POST /api/subscribe` `{ email }` — per-IP rate-limited; rejected when disabled. Validate
  (`EmailStr`) + normalize. **Persist nothing.** Send a confirmation email (transactional
  Resend send) with a signed-token confirm link. **Always returns the same generic response**
  ("check your inbox to confirm") — no enumeration, and (since we store nothing) we cannot and
  do not reveal whether the address is already subscribed.
- `GET /subscribe/confirm?token=…` — backend-served minimal HTML page. Verify the signed token;
  on success call Resend create-contact into `resend_segment_id`; show "You're subscribed."
  Invalid/expired/tampered → friendly error page. Idempotent.

Unsubscribe is **entirely Resend-managed** (the `{{{RESEND_UNSUBSCRIBE_URL}}}` link in
broadcasts) — AgBlogger exposes no unsubscribe endpoint.

`/subscribe/confirm` is registered before the StaticFiles catch-all (like SEO routes); the
exact `/subscribe` path falls through to the SPA shell (`SubscribePage`).

### Admin (`require_admin`)
- `GET /api/admin/subscriptions/settings` — `enabled`, `from_email`, `from_name`, compliance
  fields, `segment_configured`, `key_configured` (bool; **never the key**), and
  `subscriber_count` (read live from Resend; degrades to "unavailable" on API failure).
- `PUT /api/admin/subscriptions/settings` — update fields; `api_key` write-only; enforces the
  §6 enable precondition; auto-creates the Resend segment if needed.
- `POST /api/admin/subscriptions/test` `{ email }` — send one test email to verify key +
  sender; surfaces Resend's real error (admin is trusted).
- `GET /api/admin/subscriptions/broadcasts` — local ledger, newest first.
- `POST /api/admin/subscriptions/broadcasts` `{ post_path }` — manual broadcast for a published
  post; overrides the once-guard.

`SiteConfigResponse` gains a public `subscriptions_enabled` boolean so the header conditionally
renders the Subscribe link without an extra request.

## 8. Flows

### Subscribe (stateless double opt-in)
1. Reader opens `/subscribe` → email input + "Subscribe" + layered notice.
2. `POST /api/subscribe`: rate-limit (per-IP burst + sustained); validate/normalize.
3. Send confirmation email via Resend with a signed-token link
   `{base}/subscribe/confirm?token=…`, controller identity, and "If you didn't request this,
   ignore this email." Base URL derived from the request (same mechanism SEO uses).
4. Return the generic response. **Nothing is stored.**
5. Reader clicks → `GET /subscribe/confirm` verifies token → Resend create-contact → confirmed.

### Broadcast
**Triggers**
- **Auto:** in `backend/api/posts.py`, after a successful draft→published transition (and
  create-as-published), *post-commit*, when `enabled` and no `sent` ledger row exists for the
  `post_path`. Scope: web-editor publish path only.
- **Manual:** admin endpoint; always sends (override).

**Execution** — a background `asyncio` task (so publish is never blocked/crashed by the
integration):
1. Build HTML: subject = post title; body = the **already-sanitized** `PostCache.rendered_html`
   wrapped in a minimal inline-styled shell (post link at top; footer with controller identity,
   `postal_address`, and `{{{RESEND_UNSUBSCRIBE_URL}}}` at bottom); plain-text fallback.
2. POST Resend `create-broadcast` (`segmentId`, `from`, `subject`, `html`, `text`, `send:true`).
3. Record the ledger row (`sent` + broadcast id, or `failed` + error). All exceptions caught and
   logged — the task can never crash the server.

## 9. Admin panel — new "Subscriptions" tab

- **Settings:** enable toggle (blocked with an explanatory message until the §6 precondition is
  met); Resend key (write-only, "configured ✓ / not set"); segment status (auto-created); from
  email/name; controller name + contact, privacy policy URL, postal address; "Send test email";
  Save.
- **Subscribers:** live count read from Resend (no list — we hold no addresses).
- **Send to subscribers:** published-post picker + "Send broadcast" with a confirm dialog.
- **Broadcast history:** local ledger table (title, date, status, Resend broadcast id).

New `frontend/src/api/subscriptions.ts`; components under
`frontend/src/components/admin/subscriptions/`; public `SubscribePage`; backend-served confirm
page.

## 10. GDPR / compliance

**Controllership is not offloaded by not storing the data.** The operator decides the purpose
and means (collect emails to send post notifications via Resend), so the operator is the
**data controller** and Resend is the **processor** — regardless of where the addresses are
stored. The notice must identify the operator as controller; it must **not** deflect
responsibility to Resend ("Resend processes your data, not us" would omit the legally required
controller identification). Not storing the data reduces operational/security burden (no local
PII breach surface, no access/erasure tooling to build) but does not remove the transparency
(Art. 13), lawful-basis, DPA (Art. 28), or transfer-safeguard obligations.

- **Layered notice** on the subscribe page (concise inline + privacy-policy link), rendered from
  the configured compliance fields: controller identity + contact; purpose (new-post
  notifications) and basis (consent, Art. 6(1)(a)); **Resend (Resend Inc., USA) as processor and
  store**, with the **EEA→US transfer** under appropriate safeguards; retention (held by the
  email provider until the reader unsubscribes); rights (access, rectify, erase, restrict, port,
  **withdraw consent**, **complain to a supervisory authority**).
- **Consent record** lives at Resend (the confirmed contact + created-at). AgBlogger retains
  nothing, consistent with the store-zero-PII principle.
- **Data-subject requests** (access/erasure) are fulfilled in Resend: unsubscribe removes the
  reader from broadcasts; deletion via Resend's contact management.
- **Emails** identify the sender, include the configured postal address, and the Resend-managed
  unsubscribe (GDPR + CAN-SPAM).
- **Operator responsibilities** (documented): sign Resend's DPA; publish a privacy policy noting
  Resend as the subscriber data store; maintain Art. 30 records if applicable.

## 11. Security, rate-limiting, reliability

- **Rate limiting** on `POST /api/subscribe` via the existing `InMemoryRateLimiter`: per-IP
  burst (~3/min) + sustained (~10/hour), tunable. With stateless double opt-in this is also the
  key defense against **confirmation-email spam to arbitrary victims** (any submitted address
  receives one confirmation email) — the email's "ignore if you didn't request this" line and a
  signed, expiring token bound the abuse, and rate limiting caps volume. This also protects
  Resend's finite **transactional** quota (confirmations) from exhaustion; if that quota is
  temporarily spent, subscribe fails safe with a generic "try again later" response and never
  crashes.
- **No enumeration:** subscribe always returns the generic response; we cannot leak subscription
  state because we hold none.
- **Key at rest:** Fernet-encrypted (SECRET_KEY-derived), never returned, decrypted only for
  Resend calls.
- **Signed token:** HMAC over `{email, issued_at}` with `SECRET_KEY`, short expiry; tampering or
  expiry → rejected.
- **Email content** reuses the server-sanitized cached `rendered_html`; no new unsanitized path.
  Resend host is fixed (no SSRF).
- **Never crash:** all Resend calls behind try/except; broadcast runs in a background task;
  public errors generic, admin errors detailed; business validation (bad email, disabled,
  precondition) returns clear 4xx.

## 12. Configuration & dependencies

- `email-validator` already present (enables `EmailStr`).
- Resend via existing `httpx` (no SDK).
- New durable `subscription_settings` + `subscription_broadcasts` in the main DB (one Alembic
  migration). **No** `subscriptions_database_url`.
- Confirmation/broadcast base URL derived from the triggering request (same as SEO).

### 12.1 Resend plan & limits (free-tier feasibility)

Resend separates **marketing** and **transactional** quotas, and our two email types land on
different sides — which is what makes the free tier viable:

- **Broadcasts to a Segment are marketing emails:** free tier allows **unlimited sends to up to
  1,000 contacts/month** and they do **not** count against the transactional cap. Broadcasting
  every post to the whole list is free for up to 1,000 subscribers.
- **Confirmation + test emails are transactional:** free tier caps these at **100/day,
  3,000/month**. Normal signup volume is well within this; the per-IP subscribe rate limit also
  protects this shared quota from signup spikes/abuse.
- **A verified sending domain is required** to email real subscribers (free tier includes 1
  domain). Without one, Resend permits only test sends to the account owner's address — so the
  operator must own and verify a domain. Hard prerequisite on every tier.
- **Beyond 1,000 contacts**, a paid marketing plan is required (~$40/mo from 5,000 contacts as
  of June 2026).

Net: fully usable on the free tier for a typical self-hosted blog (≤1,000 subscribers,
unlimited post broadcasts); the only non-obvious prerequisite is a verified domain.

## 13. Testing (TDD, failing-first)

- **Pure / property:** signed-token round-trip (sign→verify), tamper/expiry rejection; email
  normalization idempotence; once-guard vs manual override; "key never leaks" serialization.
- **Integration (Resend mocked via httpx mock transport):** subscribe (happy → confirmation
  sent, persists nothing; disabled; rate-limited; bad email; all → generic response); confirm
  (valid token → create-contact called; expired/tampered → rejected; idempotent); settings (key
  stored encrypted, never returned; enable precondition; segment auto-create); test-email;
  broadcast (auto-once, manual override, correct create-broadcast payload incl. unsubscribe
  merge tag, Resend failure → ledger `failed` + server stays up); subscriber count read from
  Resend (and graceful degradation on failure).
- **Security regressions:** token tamper/expiry, rate limit, confirmation-spam bound, key never
  exposed, no PII written to any DB.

## 14. Documentation updates

- New `docs/arch/subscriptions.md` (emphasize: no subscriber PII stored locally; Resend is the
  system of record); link from `docs/arch/index.md`.
- Update `backend.md` (new durable settings + ledger, Resend integration, no separate DB),
  `data-flow.md` (publish→Resend broadcast), `security.md` (store-zero-PII, key at rest, consent
  delegated to Resend), `frontend.md` (subscribe route + admin tab), `deployment.md` (Resend DPA
  note, SECRET_KEY now also protects the Resend key + signs confirm tokens).

## 15. Known limitations

- Auto-send covers only the web-editor publish path; sync/CLI/git publishes use the manual
  trigger.
- Subscriber relationship and deliverability now depend on Resend (vendor dependency); migrating
  providers means exporting contacts from Resend.
- Broadcast history keys on path-at-send-time; post renames don't rematch.
- Full HTML post content in email may render imperfectly in some clients; this is the explicit
  requirement and is sent with a plain-text fallback.
