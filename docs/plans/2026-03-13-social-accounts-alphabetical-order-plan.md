# Social Accounts Alphabetical Order

## Goal

Keep the admin "Social" tab predictable by rendering connected social accounts in alphabetical order.

## Plan

1. Add a frontend regression test that proves connected accounts render in alphabetical order by displayed account name.
2. Sort fetched social accounts before storing them in `SocialAccountsPanel`, using the platform name as a fallback when an account name is missing.
3. Run focused frontend tests and `just check` to verify the change does not regress existing cross-posting behavior.

## Result

- Added a Vitest regression test for alphabetical ordering in the admin social accounts panel.
- Sorted connected accounts client-side in the social accounts panel.
- Verified with a focused Vitest run and a full `just check` pass.
