# Cross-Posting

## Plugin Architecture

- `CrossPoster` protocol (`backend/crosspost/base.py`) defines the interface
- `CrossPostContent` dataclass carries the data for each cross-post
- `CrossPostResult` dataclass reports the outcome

## Platforms

- **Bluesky** — AT Protocol OAuth (confidential client / BFF pattern). Uses DPoP-bound access tokens, PKCE, and Pushed Authorization Requests (PAR). Builds rich text facets for URLs and hashtags. 300-character limit.
- **Mastodon** — OAuth 2.0 with dynamic app registration and PKCE. Posts statuses via httpx. 500-character limit.
- **X (Twitter)** — OAuth 2.0 with PKCE. Posts text tweets via X API v2 (`POST /2/tweets`). 280-character limit. Token refresh on 401.
- **Facebook** — OAuth 2.0 for Facebook Pages. Posts to Pages via Graph API v22.0 (`POST /{page-id}/feed`). Page Access Tokens are non-expiring. Multi-page selection supported.

A platform registry maps names to poster classes. Each cross-post attempt is recorded in the `cross_posts` table with status, platform ID, timestamp, and error message. When tokens are refreshed during a cross-post (Bluesky or X), the updated credentials are re-encrypted and persisted.

Connected account credentials are accepted only in encrypted form at read time. If a stored `SocialAccount.credentials` value cannot be decrypted or parsed after decryption, cross-posting fails closed and the user must reconnect the account; the service does not fall back to plaintext JSON in the database.

Cross-posting supports an optional `custom_text` field: when provided via the API (`CrossPostRequest.custom_text`), platforms use it verbatim instead of auto-generating text from the post title, excerpt, and URL.

## Bluesky OAuth Flow

AgBlogger authenticates with Bluesky using AT Protocol OAuth with three mandatory extensions:

- **PKCE (S256)**: Prevents authorization code interception.
- **PAR**: Authorization parameters are pushed server-side, not exposed in the browser URL.
- **DPoP**: Every token request and API call includes an ES256-signed JWT proof binding the token to the client.

The flow:

1. User enters their Bluesky handle → `POST /api/crosspost/bluesky/authorize`
2. Backend resolves handle → DID → PDS → authorization server metadata
3. Backend validates the discovered PAR and authorization endpoints as HTTPS, non-local, SSRF-safe URLs, then sends a PAR request with PKCE challenge + client assertion (signed with the app's ES256 key)
4. Frontend redirects user to Bluesky's authorization page
5. Bluesky redirects back to `GET /api/crosspost/bluesky/callback`
6. Backend exchanges authorization code for DPoP-bound tokens, stores encrypted credentials in `SocialAccount`

**Client identity**: An ES256 keypair is generated on first startup and stored in a private state directory alongside the configured database, outside `content/`. The public key is served in the client metadata document at `GET /api/crosspost/bluesky/client-metadata.json`. The `BLUESKY_CLIENT_URL` setting provides the public base URL used to construct the `client_id`, and production startup validation requires it to be a canonical `https://` origin when configured.

**OAuth state**: Pending authorization flows are stored in an in-memory `OAuthStateStore` (`backend/crosspost/bluesky_oauth_state.py`) with a 10-minute TTL, keyed by the `state` parameter. The store enforces per-user pending-flow limits and rejects new flows when saturated instead of evicting another user's state.

**Token lifecycle**: Access tokens are short-lived and DPoP-bound. Refresh tokens last up to 3 months. On 401 responses during cross-posting, the `BlueskyCrossPoster` automatically refreshes tokens and retries. Updated tokens are persisted after each successful cross-post.

## Mastodon OAuth Flow

Mastodon uses standard OAuth 2.0 with dynamic client registration and PKCE:

1. User enters their Mastodon instance URL → `POST /api/crosspost/mastodon/authorize`
2. Backend validates and normalizes the instance URL (SSRF protection via `_normalize_instance_url()`)
3. Backend dynamically registers an app on the instance via `POST /api/v1/apps`, generating PKCE challenge
4. OAuth state (client credentials, PKCE verifier, instance URL) is stored in the in-memory `OAuthStateStore` with 10-minute TTL and per-user pending-flow limits
5. Frontend redirects user to the instance's `/oauth/authorize` endpoint
6. Instance redirects back to `GET /api/crosspost/mastodon/callback`
7. Backend exchanges authorization code for access token, verifies credentials via `GET /api/v1/accounts/verify_credentials`, stores encrypted credentials in `SocialAccount`

## X OAuth Flow

X uses OAuth 2.0 with PKCE:

1. User clicks "Connect X" on the admin page → `POST /api/crosspost/x/authorize`
2. Backend builds the authorization URL with PKCE challenge using `X_CLIENT_ID` and `X_CLIENT_SECRET` settings
3. OAuth state (PKCE verifier, client credentials) is stored in the in-memory `OAuthStateStore` with 10-minute TTL and per-user pending-flow limits
4. Frontend redirects user to X's authorization page
5. X redirects back to `GET /api/crosspost/x/callback`
6. Backend exchanges authorization code for access and refresh tokens, fetches user profile via `GET /2/users/me`, stores encrypted credentials in `SocialAccount`

**Token lifecycle**: Access tokens are short-lived. Refresh tokens are used to obtain new access tokens. On 401 responses during cross-posting, `XCrossPoster` automatically refreshes tokens and retries. Updated tokens are persisted after refresh.

## Facebook OAuth Flow

Facebook uses OAuth 2.0 for Pages:

1. User clicks "Connect Facebook" on the admin page → `POST /api/crosspost/facebook/authorize`
2. Backend builds the authorization URL using `FACEBOOK_APP_ID` and `FACEBOOK_APP_SECRET` settings, requesting `pages_manage_posts` and `pages_read_engagement` scopes
3. OAuth state is stored in the in-memory `OAuthStateStore` with 10-minute TTL and per-user pending-flow limits
4. Frontend redirects user to Facebook's authorization page
5. Facebook redirects back to `GET /api/crosspost/facebook/callback`
6. Backend exchanges the authorization code for a short-lived user token, then exchanges it for a long-lived token using server-side `POST` bodies rather than URL query parameters
7. Backend fetches managed Pages via `GET /me/accounts` with `Authorization: Bearer <token>`, presenting a page selection step if multiple pages are available
8. Page Access Tokens (non-expiring for long-lived user tokens) and selected page info are stored encrypted in `SocialAccount`

## Cross-Posting UI

The frontend cross-posting interface spans three pages:

**Admin page** (`SocialAccountsPanel`): A "Social Accounts" section lists connected accounts as cards with platform icon, handle, and disconnect button. Connect buttons open inline forms for entering a Bluesky handle, Mastodon instance URL, or initiating X/Facebook OAuth flows.

**Post page** (`CrossPostSection`, `CrossPostHistory`): An admin-only section below post content shows cross-post history (platform icon, timestamp, status badge) and a "Share" button (visible only when accounts are connected). The Share button opens the `CrossPostDialog`.

**Editor page**: When social accounts are connected, platform checkboxes appear in the metadata bar ("Share after saving"). On save with platforms selected, the `CrossPostDialog` opens pre-populated — a two-step flow ensuring the user reviews text before posting.

**Cross-post dialog** (`CrossPostDialog`): A modal with a single editable textarea (auto-generated from post title + URL), per-platform character counters (300 for Bluesky, 280 for X, 500 for Mastodon; Facebook has no limit), platform checkboxes, and a results view showing per-platform success/failure after posting.

## Post Sharing (Client-Side)

Separate from the admin-only cross-posting system, post sharing is a client-side feature available to all users (including unauthenticated visitors). It requires no backend changes — share links are constructed entirely in the browser.

**Components** live in `frontend/src/components/share/`:

```
frontend/src/components/share/
├── shareUtils.ts           Share URL generation, native share API, clipboard, Mastodon instance helpers
├── ShareButton.tsx         Compact header share button with dropdown popover
├── ShareBar.tsx            Bottom-of-post horizontal row of platform icon buttons
└── MastodonSharePrompt.tsx Inline form for Mastodon instance URL input
```

**Placement on PostPage**: `ShareButton` appears inline in the post header metadata row (date, author, labels). `ShareBar` appears as a horizontal icon row below the post content, above the admin-only cross-post section.

**Share mechanism**: On browsers that support the Web Share API (`navigator.share`), `ShareButton` invokes the native OS share sheet directly — clicking the button invokes the OS share sheet without showing platform options. On browsers without Web Share API support, it opens a dropdown popover listing platform buttons. `ShareBar` always shows individual platform buttons and additionally shows the native share button alongside them when the API is available.

**Supported platforms**: Bluesky, Mastodon, X, Facebook, LinkedIn, Reddit, Email, and Copy Link. Platform buttons open a pre-filled compose URL in a new tab (e.g., `https://bsky.app/intent/compose?text=...`). Email uses a `mailto:` link in the current window. Copy Link writes the post URL to the clipboard.

**Share text format**: When an author is present: `"\u201c{title}\u201d by {author} {url}"`. When the author is null: `"\u201c{title}\u201d {url}"`. Both formats use curly (typographic) quotes around the title.

**Mastodon instance handling**: Mastodon requires a per-instance share URL (`https://{instance}/share?text=...`). When a user clicks the Mastodon share button for the first time, `MastodonSharePrompt` asks for their instance URL (e.g., `mastodon.social`). The instance is saved to `localStorage` (key: `agblogger:mastodon-instance`) and reused on subsequent shares.

**Platform icons**: The existing `PlatformIcon` component (`frontend/src/components/crosspost/PlatformIcon.tsx`) was extended with SVG icons for X, Facebook, LinkedIn, and Reddit to support the additional share platforms.

**Distinction from cross-posting**: Sharing opens external compose pages for the reader to post from their own accounts. Cross-posting publishes server-side from the admin's connected OAuth accounts. The two features are independent and appear in separate sections on the post page.
