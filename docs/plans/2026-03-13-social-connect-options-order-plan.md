# Social Connect Options Order

## Goal

Keep the admin "Social" tab fully alphabetical by displayed platform name, including the empty-state connect options.

## Plan

1. Add a regression test for the no-accounts state so the connect buttons must render as `Bluesky`, `Facebook`, `Mastodon`, then `X`.
2. Reorder the connect-card blocks in `SocialAccountsPanel` to match the platform-name ordering already used for connected accounts.
3. Update the architecture note and rerun focused frontend tests plus `just check`.

## Result

- Added a regression test for available connect-card ordering.
- Reordered the no-accounts/admin connect options to `Bluesky`, `Facebook`, `Mastodon`, `X`.
- Revalidated with a focused Vitest run and a full `just check` pass.
