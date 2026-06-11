---
name: resend-webhook-contact-deletion
description: Webhook endpoint that receives Resend contact.unsubscribed events and permanently deletes the contact, making unsubscribe equivalent to GDPR erasure.
metadata:
  type: project
---

# Resend Webhook — Contact Deletion on Unsubscribe

## Problem

Resend's managed unsubscribe flow marks a contact as `unsubscribed: true` but does not delete it. The generated privacy policy claims "we keep your email address until you unsubscribe", which is inaccurate. Under GDPR Art. 6(1)(a) (consent), withdrawing consent should erase the data.

## Solution

Add a `POST /api/webhooks/resend` endpoint. Resend pushes a `contact.unsubscribed` event when a subscriber uses the managed unsubscribe link. The endpoint verifies the svix signature, then calls Resend's `DELETE /audiences/{audience_id}/contacts/{id}` API to permanently erase the contact. Update the privacy policy to reflect true erasure.

## Data Model

One new nullable column on `SubscriptionSettings`:

- `resend_webhook_secret_encrypted` (text, nullable) — Fernet-encrypted at rest, same pattern as `resend_api_key_encrypted`.

Exposed in the admin settings response as `webhook_secret_configured: bool`. The raw value is never returned.

The admin configures it via the existing `PUT /api/admin/subscriptions/settings` endpoint — a new optional `webhook_secret` field in `SubscriptionSettingsUpdate`. A new Alembic migration adds the column.

## Components

### `resend_client.delete_contact(api_key, audience_id, contact_id)`

New function. Calls `DELETE /audiences/{audience_id}/contacts/{contact_id}`. Treats 404 as success (contact already gone). Raises `ResendError` on other failures.

### `subscription_service.handle_resend_webhook(session, raw_body, headers, secret_key)`

- Loads `SubscriptionSettings` from DB; if no webhook secret configured, logs warning and returns (caller returns 200).
- Decrypts the webhook secret.
- Calls `svix.webhooks.Webhook(secret).verify(raw_body, headers)` — raises `WebhookVerificationError` on bad signature.
- Parses JSON payload; ignores unknown event types silently.
- On `contact.unsubscribed`: extracts `data.contact.id` and `data.audience_id`, calls `resend_client.delete_contact`. Logs success or `ResendError` (warning level). Never logs email addresses.
- On missing `contact.id` / `audience_id` in payload: logs warning, returns without raising.

### `subscriptions.py` — new `webhook_router`

`POST /api/webhooks/resend` — public, no auth, no CSRF (Resend has no session cookie).

Reads raw request body (required for svix verification — parsing JSON first would break signature check). Response behaviour:

| Condition | HTTP status |
|---|---|
| No webhook secret configured | 200 |
| Signature invalid | 400 |
| Resend API failure during deletion | 200 (logged) |
| Unexpected payload shape | 200 (logged) |
| Unknown event type | 200 |
| Success | 200 |

Returns 400 only for bad signatures — this is a genuine signal to Resend that the payload was invalid. All other failures return 200 so Resend does not retry indefinitely.

### `pages.py` — privacy policy update

Retention section: "Your email address is deleted from our email service provider when you unsubscribe." Replaces: "We keep your email address until you unsubscribe."

## Dependencies

Add `svix` to `pyproject.toml` project dependencies. The `svix` library enforces a ±5 minute replay window by default.

## Tests

**`resend_client`**
- `test_delete_contact_success`
- `test_delete_contact_404_treated_as_success`
- `test_delete_contact_other_error_raises`

**Webhook endpoint** (happy path + abuse paths per security guidelines)
- Valid `contact.unsubscribed` + correct signature → 200, `delete_contact` called
- Valid signature, unknown event type → 200, no deletion
- Invalid/missing signature → 400
- No webhook secret configured → 200, no deletion
- `ResendError` during deletion → 200
- Malformed JSON body → 400 (svix rejects)
- Missing `contact.id` or `audience_id` in payload → 200, logged warning

**Settings**
- `webhook_secret` round-trips through encrypt/decrypt
- `webhook_secret_configured` flag reflects presence correctly

**Privacy policy**
- Retention text contains "deleted", not "until you unsubscribe"
