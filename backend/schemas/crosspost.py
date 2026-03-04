"""Cross-posting schemas."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class CrossPostStatus(StrEnum):
    PENDING = "pending"
    POSTED = "posted"
    FAILED = "failed"
    UNKNOWN = "unknown"


class SocialAccountCreate(BaseModel):
    """Request to connect a social media account."""

    platform: str = Field(
        min_length=1, max_length=50, description="Platform name, e.g. 'bluesky' or 'mastodon'"
    )
    account_name: str = Field(default="", description="Display name for the account")
    credentials: dict[str, str] = Field(
        description="Platform-specific credentials (stored as JSON)"
    )


class SocialAccountResponse(BaseModel):
    """Response for a connected social account."""

    id: int
    platform: str
    account_name: str | None = None
    created_at: str


class CrossPostRequest(BaseModel):
    """Request to cross-post a blog post."""

    post_path: str = Field(
        min_length=1, max_length=500, description="Relative file path of the post to cross-post"
    )
    platforms: list[str] = Field(min_length=1, description="List of platform names to post to")
    custom_text: str | None = Field(
        default=None, description="Optional custom text to post instead of auto-generated content"
    )


class CrossPostResponse(BaseModel):
    """Response for a single cross-post result."""

    id: int
    post_path: str
    platform: str
    platform_id: str | None = None
    status: CrossPostStatus
    posted_at: str | None = None
    error: str | None = None


class CrossPostHistoryResponse(BaseModel):
    """Response containing cross-post history for a post."""

    items: list[CrossPostResponse]


class BlueskyAuthorizeRequest(BaseModel):
    """Request to start Bluesky OAuth flow."""

    handle: str = Field(min_length=1, description="Bluesky handle, e.g. 'alice.bsky.social'")


class BlueskyAuthorizeResponse(BaseModel):
    """Response with authorization URL for Bluesky OAuth."""

    authorization_url: str


class MastodonAuthorizeRequest(BaseModel):
    """Request to start Mastodon OAuth flow."""

    instance_url: str = Field(
        min_length=1, description="Mastodon instance URL, e.g. 'https://mastodon.social'"
    )


class MastodonAuthorizeResponse(BaseModel):
    """Response with authorization URL for Mastodon OAuth."""

    authorization_url: str


class XAuthorizeResponse(BaseModel):
    """Response with authorization URL for X OAuth."""

    authorization_url: str


class FacebookAuthorizeResponse(BaseModel):
    """Response with authorization URL for Facebook OAuth."""

    authorization_url: str


class FacebookSelectPageRequest(BaseModel):
    """Request to select a Facebook Page after OAuth."""

    state: str = Field(min_length=1, description="OAuth state token from callback")
    page_id: str = Field(min_length=1, description="Selected Facebook Page ID")


class FacebookSelectPageResponse(BaseModel):
    """Response after selecting a Facebook Page."""

    account_name: str


class FacebookPageInfo(BaseModel):
    """A Facebook Page available for selection."""

    id: str
    name: str


class FacebookPagesResponse(BaseModel):
    """Response with available Facebook Pages."""

    pages: list[FacebookPageInfo]
