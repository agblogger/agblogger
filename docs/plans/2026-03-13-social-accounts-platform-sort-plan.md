# Social Accounts Platform Sort

## Goal

Order connected social accounts in the admin "Social" tab by displayed platform name instead of by connected handle or page name.

## Plan

1. Replace the existing regression test so it proves platform ordering wins even when account names would sort differently.
2. Sort the connected accounts list by the user-facing platform labels shown in the admin UI.
3. Update the architecture note and rerun focused frontend tests plus `just check`.

## Result

- Added a regression test that verifies `Bluesky`, `Facebook`, `Mastodon`, then `X` ordering.
- Changed `SocialAccountsPanel` sorting to use displayed platform names.
- Updated architecture docs and revalidated with tests.
