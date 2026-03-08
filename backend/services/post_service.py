"""Post service: queries and CRUD operations."""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, or_, select, text

from backend.models.label import PostLabelCache
from backend.models.post import PostCache
from backend.schemas.post import (
    PostDetail,
    PostListResponse,
    PostSummary,
    SearchResult,
)
from backend.services.datetime_service import format_iso, parse_datetime

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def _post_labels(session: AsyncSession, post_id: int) -> list[str]:
    """Get label IDs for a post."""
    stmt = select(PostLabelCache.label_id).where(PostLabelCache.post_id == post_id)
    result = await session.execute(stmt)
    return [r[0] for r in result.all()]


async def list_posts(
    session: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 20,
    label: str | None = None,
    labels: list[str] | None = None,
    label_mode: str = "or",
    author: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    draft_owner_username: str | None = None,
    sort: str = "created_at",
    order: str = "desc",
) -> PostListResponse:
    """List posts with pagination and filtering."""
    stmt = select(PostCache)

    if draft_owner_username:
        # Show published posts + drafts authored by the given user
        stmt = stmt.where(
            or_(
                PostCache.is_draft.is_(False),
                PostCache.author_username == draft_owner_username,
            )
        )
    else:
        # No authenticated author — hide all drafts
        stmt = stmt.where(PostCache.is_draft.is_(False))

    if author:
        escaped = author.replace("%", r"\%").replace("_", r"\_")
        stmt = stmt.where(PostCache.author.ilike(f"%{escaped}%", escape="\\"))

    if from_date:
        try:
            date_part = from_date.split("T")[0].split(" ")[0]
            from_dt = parse_datetime(date_part + " 00:00:00", default_tz="UTC")
            stmt = stmt.where(PostCache.created_at >= from_dt)
        except ValueError:
            logger.warning("Failed to parse 'from' date %r", from_date, exc_info=True)
            msg = f"Invalid 'from' date format: {from_date!r}. Expected YYYY-MM-DD."
            raise ValueError(msg) from None

    if to_date:
        try:
            date_part = to_date.split("T")[0].split(" ")[0]
            to_dt = parse_datetime(date_part + " 23:59:59.999999", default_tz="UTC")
            stmt = stmt.where(PostCache.created_at <= to_dt)
        except ValueError:
            logger.warning("Failed to parse 'to' date %r", to_date, exc_info=True)
            msg = f"Invalid 'to' date format: {to_date!r}. Expected YYYY-MM-DD."
            raise ValueError(msg) from None

    # Label filtering
    label_ids: list[str] = []
    if label:
        label_ids.append(label)
    if labels:
        label_ids.extend(labels)

    if label_ids:
        # Get all descendant labels for each requested label
        from backend.services.label_service import get_label_descendant_ids

        if label_mode == "and":
            # AND mode: post must have ALL specified labels (or descendants)
            for lid in label_ids:
                descendants = await get_label_descendant_ids(session, lid)
                stmt = stmt.where(
                    PostCache.id.in_(
                        select(PostLabelCache.post_id).where(
                            PostLabelCache.label_id.in_(descendants)
                        )
                    )
                )
        else:
            # OR mode (default): post must have ANY specified label
            all_label_ids: set[str] = set()
            for lid in label_ids:
                descendants = await get_label_descendant_ids(session, lid)
                all_label_ids.update(descendants)

            stmt = stmt.where(
                PostCache.id.in_(
                    select(PostLabelCache.post_id).where(PostLabelCache.label_id.in_(all_label_ids))
                )
            )

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await session.execute(count_stmt)
    total = total_result.scalar() or 0

    allowed_sort_columns = {"created_at", "modified_at", "title", "author"}
    if sort not in allowed_sort_columns:
        msg = f"Invalid sort column: {sort!r}. Allowed: {', '.join(sorted(allowed_sort_columns))}"
        raise ValueError(msg)
    sort_col = getattr(PostCache, sort)
    stmt = stmt.order_by(sort_col.asc()) if order == "asc" else stmt.order_by(sort_col.desc())

    # Paginate
    offset = (page - 1) * per_page
    stmt = stmt.offset(offset).limit(per_page)

    result = await session.execute(stmt)
    posts = result.scalars().all()

    # Batch load labels for all posts in one query
    post_ids = [post.id for post in posts]
    labels_map: dict[int, list[str]] = {pid: [] for pid in post_ids}
    if post_ids:
        label_stmt = select(PostLabelCache.post_id, PostLabelCache.label_id).where(
            PostLabelCache.post_id.in_(post_ids)
        )
        label_result = await session.execute(label_stmt)
        for row in label_result.all():
            labels_map[row[0]].append(row[1])

    summaries: list[PostSummary] = []
    for post in posts:
        summaries.append(
            PostSummary(
                id=post.id,
                file_path=post.file_path,
                title=post.title,
                author=post.author,
                created_at=format_iso(post.created_at),
                modified_at=format_iso(post.modified_at),
                is_draft=post.is_draft,
                rendered_excerpt=post.rendered_excerpt,
                labels=labels_map.get(post.id, []),
            )
        )

    total_pages = max(1, math.ceil(total / per_page))

    return PostListResponse(
        posts=summaries,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


async def get_post(session: AsyncSession, file_path: str) -> PostDetail | None:
    """Get a single post by file path."""
    stmt = select(PostCache).where(PostCache.file_path == file_path)
    result = await session.execute(stmt)
    post = result.scalar_one_or_none()

    if post is None:
        return None

    post_label_ids = await _post_labels(session, post.id)

    return PostDetail(
        id=post.id,
        file_path=post.file_path,
        title=post.title,
        author=post.author,
        created_at=format_iso(post.created_at),
        modified_at=format_iso(post.modified_at),
        is_draft=post.is_draft,
        rendered_excerpt=post.rendered_excerpt,
        labels=post_label_ids,
        rendered_html=post.rendered_html or "",
        content=None,  # Only provided when authenticated
    )


async def search_posts(session: AsyncSession, query: str, *, limit: int = 20) -> list[SearchResult]:
    """Full-text search for posts."""
    # Escape FTS5 special characters by wrapping in double quotes
    safe_query = '"' + query.replace('"', '""') + '"'
    stmt = text("""
        SELECT p.id, p.file_path, p.title, p.rendered_excerpt, p.created_at,
               rank
        FROM posts_fts fts
        JOIN posts_cache p ON fts.rowid = p.id
        WHERE posts_fts MATCH :query
        AND p.is_draft = 0
        ORDER BY rank
        LIMIT :limit
    """)
    result = await session.execute(stmt, {"query": safe_query, "limit": limit})
    rows = result.all()
    results: list[SearchResult] = []
    for r in rows:
        created_at_val = r[4]
        if isinstance(created_at_val, datetime):
            created_at_str = format_iso(created_at_val)
        else:
            created_at_str = str(created_at_val)
        results.append(
            SearchResult(
                id=r[0],
                file_path=r[1],
                title=r[2],
                rendered_excerpt=r[3],
                created_at=created_at_str,
                rank=float(r[5]) if r[5] else 0.0,
            )
        )
    return results


async def get_posts_by_label(
    session: AsyncSession, label_id: str, *, page: int = 1, per_page: int = 20
) -> PostListResponse:
    """Get posts for a specific label (including descendants)."""
    return await list_posts(session, page=page, per_page=per_page, label=label_id)
