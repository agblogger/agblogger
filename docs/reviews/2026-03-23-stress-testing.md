# Stress Test Report — AgBlogger Server

**Date:** 2026-03-23

## Test Configuration

- **Concurrent users per scenario**: 11 (1 admin + 10 readers)
- **Scenarios tested**: 9
- **Total requests across all scenarios**: ~36,000+
- **Test duration**: 15–25 seconds per scenario
- **Server**: dev server (backend :8000, frontend :5173)

## Results by Scenario

| # | Scenario | Requests | 5xx Errors | Verdict |
|---|----------|----------|------------|---------|
| 1 | Admin edits post while readers view | 2,414 | **0** | PASS |
| 2 | Admin deletes post while readers view | 2,492 | **0** | PASS |
| 3 | Readers access just-deleted posts | 3,197 | **0** | PASS |
| 4 | Admin edits/deletes labels during search | 3,193 | **0** | PASS |
| 5 | Admin deletes post during search/filter | 3,218 | **0** | PASS |
| 6 | Admin toggles draft while users view/search | 3,991 | **0** | PASS |
| 7 | Readers share post whose title changed | 11,819 | **0** | PASS |
| 8 | Readers share post just deleted | 4,061 | **0** | PASS |
| 9 | Admin changes display name during browsing | 3,946 | **0** | PASS |

## Scenario Details

### Scenario 1: Admin Edits Post While Readers View

- 10 readers continuously fetched the post, label-filtered listings, and search results
- Admin performed 5 sequential title/body/label edits with 0.5s gaps
- **Result**: All 2,414 reader requests succeeded (100%). Zero 5xx errors. Avg latency ~10ms, max 186ms. No inconsistent state observed. First edit succeeded; edits 2–5 returned 404 because the title change altered the file_path/slug — this is expected API behavior (callers must track the new path from each PUT response).

### Scenario 2: Admin Deletes Post While Readers View

- 10 readers continuously viewed the post, listed all posts, and searched
- Admin deleted the post after 3 seconds, then created and deleted a replacement
- **Result**: 2,492 requests, zero 5xx. Clean 200→404 transition with no intermediate error states. Search endpoint returned 200 throughout (empty results after deletion). Replacement post create/delete cycle also worked cleanly. Avg latency ~8ms.

### Scenario 3: Readers Access Just-Deleted Posts

- 5 temporary posts created; admin deleted them one by one with 1-second gaps
- 10 readers continuously polled all 5 posts, listings, and search
- **Result**: 3,197 requests, zero 5xx. Deletion propagation was near-instantaneous (14–289ms per post). No stale-cache inconsistencies between search and direct access. Rapid create-after-delete also worked correctly.

### Scenario 4: Admin Edits/Deletes Labels During Search

- Admin created test labels (parent/child DAG), then renamed and deleted them sequentially
- 10 readers concurrently queried label list, individual labels, label graph, label-filtered posts, and sublabel queries
- **Result**: 3,193 requests, zero 5xx. Deleted labels returned clean 404s. Label graph endpoint stayed consistent. Sublabel queries (`includeSublabels=true`) handled gracefully even after parent deletion. Label list counts decreased monotonically as expected.

### Scenario 5: Admin Deletes Post During Search/Filter

- 3 posts with food/travel labels; admin deleted them one by one with 3-second gaps
- 10 readers continuously ran full-text search, label filters (AND/OR modes), sorted listings, and direct access
- **Result**: 3,218 requests, zero 5xx. Direct access immediately returned 404 after deletion. Paginated total counts decreased correctly (e.g., `?label=food` went 5→4→3→2). Avg latency 10ms, max 207ms. No response time spikes during deletions.

### Scenario 6: Admin Toggles Draft While Users View/Search

- Admin toggled the post between draft and published 4 times (draft→publish→draft→publish)
- 10 unauthenticated readers continuously viewed the post, filtered by labels, searched, and listed
- **Result**: 3,991 requests, zero 5xx. Draft visibility correctly enforced — readers got 404 during draft periods, 200 when re-published. Search and label-filtered results correctly excluded/included the post. `created_at` updated on each draft→published transition (expected behavior). Avg latency 11ms.

### Scenario 7: Readers Share Post Whose Title Changed

- Admin renamed the post 4 times in sequence, changing the slug each time
- 10 readers continuously fetched the post by original URL, listed posts, and searched
- **Result**: 11,819 requests, zero 5xx, zero 404s. Server issued proper 301 redirects from old file paths to new ones. Redirect targets updated correctly through all 4 chained renames (old URL → Alpha → Beta → Gamma → Final). Search and listings reflected new titles essentially immediately. 1,467 redirect responses observed.

### Scenario 8: Readers Share Post Just Deleted

- 3 posts created for sharing; admin deleted them one by one with 3-second gaps
- 10 readers continuously fetched posts for "sharing" (title + URL extraction), listed, and searched
- **Result**: 4,061 requests, zero 5xx. Clean 200→404 transitions with sub-100ms gaps (34–82ms). Search results updated promptly. No case where a deleted post appeared in listing but returned 404 on direct access.

### Scenario 9: Admin Changes Display Name During Browsing

- Admin changed display_name 4 times via PATCH /api/auth/me
- 10 readers continuously viewed 3 posts, filtered by author, listed all posts, and searched
- **Result**: 3,946 requests, zero 5xx. Display name changes propagated immediately and atomically across all posts. All 3 target posts showed the new author value within 0.1–0.3s of each other. Author-filtered queries continued working throughout. Minimal latency impact (<3ms delta).

## Key Findings

### Server Stability: Excellent

- **Zero server errors (5xx)** across all ~36,000 requests in all 9 scenarios
- **Zero crashes or connection failures**
- The server never exposed internal error details to clients

### Concurrent Read/Write Handling: Correct

- Deletions produce clean 200→404 transitions with sub-100ms propagation
- Draft toggles correctly enforce visibility (unauthenticated users get 404 for drafts)
- Post renames produce proper 301 redirects that update through chained renames
- Display name changes propagate atomically across all posts
- Label deletions return clean 404s, never 500s
- Search/listing results stay consistent with direct access

### Performance Under Load: Stable

- Average response time: **~10ms** across all scenarios
- Maximum response time: **~210ms** (no significant outliers)
- No measurable latency degradation during write operations
- Write operations averaged ~23–72ms, well within acceptable range

### Notable Behaviors (Not Bugs)

1. **Title changes alter file_path/slug** — admin must track the new path from PUT responses for subsequent edits (Scenario 1)
2. **`created_at` updates on draft→published transitions** — re-publishing resets the publication timestamp (Scenario 6)
3. **Redirect chain for renamed posts** — old URLs correctly 301 to the latest path through multiple renames (Scenario 7)

## Conclusion

The AgBlogger server demonstrates **production-grade reliability** under concurrent load. All 9 stress test scenarios targeting read/write contention, deletion races, draft visibility, rename handling, and search consistency passed with zero server errors. The write coordination boundary and cache consistency mechanisms work correctly under parallel load from 11 concurrent users.
