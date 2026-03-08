"""Post-related schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class PostSummary(BaseModel):
    """Post summary for timeline listing."""

    id: int
    file_path: str
    title: str
    author: str | None = None
    created_at: str
    modified_at: str
    is_draft: bool = False
    rendered_excerpt: str | None = None
    labels: list[str] = Field(default_factory=list)


class PostDetail(PostSummary):
    """Full post detail with rendered HTML."""

    rendered_html: str
    content: str | None = None
    warnings: list[str] = Field(default_factory=list)


class PostEditResponse(BaseModel):
    """Structured post data for the editor."""

    file_path: str
    title: str
    body: str
    labels: list[str] = Field(default_factory=list)
    is_draft: bool = False
    created_at: str
    modified_at: str
    author: str | None = None


class PostSave(BaseModel):
    """Request body for creating or updating a post."""

    title: str = Field(
        min_length=1,
        max_length=500,
        description="Post title",
    )
    body: str = Field(
        min_length=1,
        max_length=500_000,
        description="Markdown body without front matter",
    )
    labels: list[str] = Field(default_factory=list)
    is_draft: bool = False

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, v: str) -> str:
        _ = cls
        return v.strip()


class PostListResponse(BaseModel):
    """Paginated post list response."""

    posts: list[PostSummary]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    per_page: int = Field(ge=1)
    total_pages: int = Field(ge=0)


class SearchResult(BaseModel):
    """Search result item."""

    id: int
    file_path: str
    title: str
    rendered_excerpt: str | None = None
    created_at: str
    rank: float = 0.0


class AssetInfo(BaseModel):
    """Info about a single asset file."""

    name: str
    size: int
    is_image: bool


class AssetListResponse(BaseModel):
    """Response for listing post assets."""

    assets: list[AssetInfo]
