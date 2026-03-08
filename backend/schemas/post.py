"""Post-related schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from backend.schemas.label import LABEL_ID_PATTERN


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

    @field_validator("labels")
    @classmethod
    def validate_labels(cls, v: list[str]) -> list[str]:
        """Each label must be a valid label ID (lowercase alphanumeric with hyphens)."""
        _ = cls
        for label in v:
            if not LABEL_ID_PATTERN.match(label):
                msg = f"Invalid label {label!r}: must match pattern '^[a-z0-9][a-z0-9-]*$'"
                raise ValueError(msg)
        return v


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

    name: str = Field(min_length=1)
    size: int = Field(ge=0)
    is_image: bool


class AssetListResponse(BaseModel):
    """Response for listing post assets."""

    assets: list[AssetInfo]


class AssetRenameRequest(BaseModel):
    """Request body for renaming an asset."""

    new_name: str = Field(min_length=1, max_length=255)
