# Draft Sharing And Cross-Posting Restriction

## Goal

Prevent draft posts from being shared or cross-posted from the web UI, while keeping the restriction explicit to the user.

## Plan

1. Add failing frontend tests covering disabled draft sharing, disabled draft cross-posting, and the editor save-time draft restriction.
2. Update the share controls, post view, cross-post section, and editor flow so drafts expose disabled controls/messages instead of allowing distribution actions.
3. Update architecture notes and verify with focused tests plus `just check`.
