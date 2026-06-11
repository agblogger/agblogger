# Resend Segment Recovery Design

**Date:** 2026-06-11

## Problem

When a Resend segment is deleted externally (via Resend dashboard or API), AgBlogger holds
a stale `resend_segment_id` in `subscription_settings`. Subsequent opt-in confirmations
and broadcasts silently fail with Resend 404 errors. There is currently no way to recover
without editing the database directly.

## Goal

Allow an admin to recover from accidental segment deletion by disabling and re-enabling
subscriptions in the panel. The enable flow will verify whether the stored segment still
exists in Resend and, if not, automatically create a fresh one.

## Design

### Backend — `resend_client.py`

Add `check_segment_exists(*, api_key: str, segment_id: str) -> bool`:

- Calls `GET /audiences/{segment_id}`.
- Returns `True` on 2xx.
- Returns `False` on a Resend-returned not-found error (segment no longer exists).
- Re-raises `ResendError` for all other failures (network errors, auth failures, unexpected
  status codes) so callers cannot accidentally swallow real problems.

### Backend — `subscription_service._prepare_enable`

Current behaviour: if `resend_segment_id` is already stored, accept it unconditionally;
if missing, create a new segment.

New behaviour:

1. If `resend_segment_id` is stored → call `check_segment_exists`.
   - Returns `True` → keep the existing ID (no change).
   - Returns `False` → clear `row.resend_segment_id`, fall through to creation.
2. If `resend_segment_id` is not set → create a new segment (unchanged).

The creation path (`resend_client.create_segment`) is unchanged.

`ResendError` from `check_segment_exists` (non-404 failures) propagates up to
`update_settings`, which rolls back and re-raises; the API layer already maps this to
HTTP 400 with the Resend error message, surfacing it to the admin.

### Frontend — `SubscriptionsPanel.tsx`

No new button. The existing Enable toggle is the recovery action.

When subscriptions are enabled **and** `subscriber_count` is `null` (the existing signal
that the segment is unreachable — `count_contacts` already catches `ResendError` and
returns `null`), display a small inline hint next to the subscriber count:

> *Segment unreachable — disable then re-enable subscriptions to recover.*

This guides the admin to the correct action without adding a dedicated control.

### Tests

- Unit: `check_segment_exists` — 2xx → `True`, not-found error → `False`, other
  `ResendError` → re-raises.
- Unit: `_prepare_enable` with a stale stored segment ID — verify returns `False`,
  `resend_segment_id` is cleared, new segment created and stored.
- Unit: `_prepare_enable` with a valid stored segment ID — verify returns `True`, no new
  segment is created.
- Existing segment-creation tests (no stored ID path) remain unchanged.

## What This Does Not Cover

- Detecting a stale segment while subscriptions are *already* enabled and running (only
  triggered on re-enable).
- Listing or managing multiple Resend segments.
- The frontend hint does not distinguish between "segment deleted" and other transient
  Resend errors that also cause `subscriber_count` to be null.
