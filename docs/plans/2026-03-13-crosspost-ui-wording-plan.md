# Cross-Post UI Wording And Error Handling

## Goal

Make the web UI use explicit cross-post wording for cross-posting workflows, keep that language distinct from public sharing, surface cross-post-related loading failures to the user, and provide a direct route to account connection when no social accounts are connected.

## Plan

1. Add failing frontend tests for cross-post wording, visible fetch errors, and direct navigation to the social account connection tab.
2. Update the post-view cross-post section, dialog, editor save-time cross-post controls, and admin tab deep-linking behavior.
3. Update the relevant architecture doc and verify the repository with focused tests plus `just check`.
