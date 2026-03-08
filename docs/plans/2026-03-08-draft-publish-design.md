# Draft Publish UX Design

## Problem

Draft posts lack prominent visual indication on the post page, and publishing requires navigating to the editor to uncheck a checkbox. The `created_at` timestamp is set at post creation rather than at publish time.

## Design

### Backend: Draft-to-Published Transition

In the existing `PUT /api/posts/{file_path}` endpoint, detect when `existing.is_draft` is `True` and `body.is_draft` is `False`. When this transition occurs, set `created_at` to `now_utc()`. This applies uniformly whether triggered from the editor or the post page Publish button.

No new endpoints, schemas, or API functions.

### Frontend: Post Page Draft Indicator

When a post is a draft and the authenticated user is the author:
- **Draft badge**: amber "Draft" badge next to the title (left side), reusing the existing `PostCard` badge style.
- **Publish button**: primary-styled button on the right side of the title row. One-click publish (no confirmation). Disabled with loading state during the API call. On success, refreshes the post data so the badge disappears and `created_at` updates.

Not shown for published posts or unauthenticated users. No "Unpublish" button on the post page; unpublishing is done through the editor.

### Post List

No changes. The existing amber badge in `PostCard.tsx` is sufficient.

## Testing

### Backend
- Draft-to-published transition updates `created_at` to now
- Non-transition update preserves `created_at`
- Re-draft then re-publish updates `created_at` again

### Frontend
- Badge + Publish button render for draft post when user is author
- Not rendered for published posts
- Not rendered for unauthenticated users
- Publish button calls update API with `is_draft: false`
- Button disabled during API call
