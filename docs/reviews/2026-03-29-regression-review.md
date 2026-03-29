# Regression Review — 2026-03-29

**Scope**: Follow-up review of the SEO/server-preload patch. Focused on generated post URLs, SWR preload behavior, RSS timestamp handling, and route title updates.

## Findings

1. **[P1] Preserve nested slug segments in generated post URLs** — `backend/main.py`
   Homepage, label-detail, sitemap, and feed generation used `p.file_path.split("/")[1]`, which truncates canonical nested post paths such as `posts/2026/recap/index.md` to `2026`. Generated URLs like `/post/2026` are incorrect; these routes must use the shared `file_path_to_slug()` helper so nested directory-backed posts keep their full slug.

2. **[P2] Scope SWR preload fallback to the current route key** — `frontend/src/hooks/usePost.ts`, `frontend/src/hooks/usePage.ts`, `frontend/src/hooks/useLabelPosts.ts`
   Each hook captures `fallbackData` once per component mount and reuses it after route-param changes. On client-side navigation that reuses the same route component, SWR shows stale content from the previous route until the new fetch resolves. The preload fallback must only apply to the initial matching key.

3. **[P2] Normalize feed pubDate timestamps to UTC before formatting** — `backend/main.py`
   RSS generation passes non-UTC aware datetimes directly to `email.utils.format_datetime(..., usegmt=True)`. That raises `ValueError` for offsets such as `+02:00`, which can turn `/feed.xml` into a 500. Feed timestamps need conversion to UTC before RFC 2822 formatting.

4. **[P3] Reset the tab title when returning to the timeline** — `frontend/src/pages/TimelinePage.tsx`
   Post/page/label/search routes update `document.title`, but the timeline route does not. In SPA navigation, returning to `/` leaves the previous page title in the tab until something else resets it. The timeline page should restore the site title on navigation.

## Recommended Work

1. Add failing-first regression tests for nested slug URLs across SEO outputs, RSS UTC normalization, SWR key changes, and timeline title reset.
2. Replace ad-hoc slug extraction in backend SEO/feed paths with `file_path_to_slug()`.
3. Gate SWR `fallbackData` by the initial route key so it is ignored after key changes.
4. Convert feed timestamps to UTC before calling `format_datetime(..., usegmt=True)`.
5. Restore the site title from the timeline route on mount/navigation.
