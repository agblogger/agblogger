"""Post service: queries and CRUD operations."""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import func, select, text

from backend.models.label import PostLabelCache
from backend.models.post import PostCache
from backend.models.user import AdminUser
from backend.schemas.post import (
    PostDetail,
    PostListResponse,
    PostSummary,
    SearchResult,
)
from backend.services.datetime_service import format_iso, parse_datetime

if TYPE_CHECKING:
    from sqlalchemy import Select
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Shared SQL expression: resolve author display name via LEFT JOIN to users table.
_resolved_author = func.coalesce(AdminUser.display_name, PostCache.author).label("resolved_author")


def _select_posts_with_author() -> Select[tuple[PostCache, str]]:
    """Base select joining PostCache with resolved author display name."""
    return select(PostCache, _resolved_author).outerjoin(
        AdminUser, PostCache.author == AdminUser.username
    )


_SQLITE_MAX_INTEGER = 2**63 - 1
_MAX_API_PER_PAGE = 100
MAX_SAFE_PAGE = (_SQLITE_MAX_INTEGER // _MAX_API_PER_PAGE) + 1


async def resolve_author_display_name(session: AsyncSession, username: str | None) -> str | None:
    """Resolve a username to the user's display name, falling back to the raw username."""
    if not username:
        return username
    stmt = select(AdminUser.display_name).where(AdminUser.username == username)
    result = await session.execute(stmt)
    display_name = result.scalar_one_or_none()
    return display_name or username


async def _post_labels(session: AsyncSession, post_id: int) -> list[str]:
    """Get label IDs for a post."""
    stmt = select(PostLabelCache.label_id).where(PostLabelCache.post_id == post_id)
    result = await session.execute(stmt)
    return [r[0] for r in result.all()]


def validate_pagination(page: int, per_page: int) -> None:
    """Reject pagination inputs that would overflow SQLite LIMIT/OFFSET integers."""
    if page < 1:
        msg = "Page must be greater than or equal to 1"
        raise ValueError(msg)
    if per_page < 1:
        msg = "per_page must be greater than or equal to 1"
        raise ValueError(msg)

    max_page = (_SQLITE_MAX_INTEGER // per_page) + 1
    if page > max_page:
        msg = f"Page is too large for per_page={per_page}; maximum supported page is {max_page}"
        raise ValueError(msg)


async def list_posts(
    session: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 20,
    label: str | None = None,
    labels: list[str] | None = None,
    label_mode: Literal["or", "and"] = "or",
    include_descendants: bool = False,
    author: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    draft_owner_username: str | None = None,
    sort: Literal["created_at", "modified_at", "title", "author"] = "created_at",
    order: Literal["asc", "desc"] = "desc",
) -> PostListResponse:
    """List posts with pagination and filtering."""
    validate_pagination(page, per_page)

    stmt = _select_posts_with_author()

    if draft_owner_username:
        # Authenticated admin — show all posts including drafts.
        pass
    else:
        # No authenticated user — hide all drafts
        stmt = stmt.where(PostCache.is_draft.is_(False))

    if author:
        escaped = author.replace("%", r"\%").replace("_", r"\_")
        stmt = stmt.where(_resolved_author.ilike(f"%{escaped}%", escape="\\"))

    if from_date:
        try:
            from_dt = parse_datetime(from_date)
            stmt = stmt.where(PostCache.created_at >= from_dt)
        except ValueError:
            logger.warning("Failed to parse 'from' date %r", from_date, exc_info=True)
            msg = f"Invalid 'from' date format: {from_date!r}. Expected ISO 8601."
            raise ValueError(msg) from None

    if to_date:
        try:
            to_dt = parse_datetime(to_date)
            # Bare dates (no time component) should be inclusive of the entire day.
            if "T" not in to_date and " " not in to_date.strip():
                to_dt = to_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            stmt = stmt.where(PostCache.created_at <= to_dt)
        except ValueError:
            logger.warning("Failed to parse 'to' date %r", to_date, exc_info=True)
            msg = f"Invalid 'to' date format: {to_date!r}. Expected ISO 8601."
            raise ValueError(msg) from None

    # Label filtering
    label_ids: list[str] = []
    if label:
        label_ids.append(label)
    if labels:
        label_ids.extend(labels)

    if label_ids:
        if include_descendants:
            from backend.services.label_service import get_label_descendants_batch

            descendants_by_label = await get_label_descendants_batch(session, label_ids)

            if label_mode == "and":
                # AND mode: post must have ALL specified labels (or descendants)
                for lid in label_ids:
                    stmt = stmt.where(
                        PostCache.id.in_(
                            select(PostLabelCache.post_id).where(
                                PostLabelCache.label_id.in_(descendants_by_label[lid])
                            )
                        )
                    )
            else:
                # OR mode (default): post must have ANY specified label (or descendants)
                all_label_ids: set[str] = set()
                for desc_set in descendants_by_label.values():
                    all_label_ids.update(desc_set)

                stmt = stmt.where(
                    PostCache.id.in_(
                        select(PostLabelCache.post_id).where(
                            PostLabelCache.label_id.in_(all_label_ids)
                        )
                    )
                )
        else:
            # Exact match only — no descendant expansion
            if label_mode == "and":
                for lid in label_ids:
                    stmt = stmt.where(
                        PostCache.id.in_(
                            select(PostLabelCache.post_id).where(PostLabelCache.label_id == lid)
                        )
                    )
            else:
                stmt = stmt.where(
                    PostCache.id.in_(
                        select(PostLabelCache.post_id).where(PostLabelCache.label_id.in_(label_ids))
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
    sort_col = _resolved_author if sort == "author" else getattr(PostCache, sort)
    stmt = stmt.order_by(sort_col.asc()) if order == "asc" else stmt.order_by(sort_col.desc())

    # Paginate
    offset = (page - 1) * per_page
    stmt = stmt.offset(offset).limit(per_page)

    result = await session.execute(stmt)
    rows = result.all()

    # Batch load labels for all posts in one query
    post_ids = [row[0].id for row in rows]
    labels_map: dict[int, list[str]] = {pid: [] for pid in post_ids}
    if post_ids:
        label_stmt = select(PostLabelCache.post_id, PostLabelCache.label_id).where(
            PostLabelCache.post_id.in_(post_ids)
        )
        label_result = await session.execute(label_stmt)
        for label_row in label_result.all():
            labels_map[label_row[0]].append(label_row[1])

    summaries: list[PostSummary] = []
    for row in rows:
        post = row[0]
        display_author = row[1]
        summaries.append(
            PostSummary(
                id=post.id,
                file_path=post.file_path,
                title=post.title,
                subtitle=post.subtitle,
                author=display_author,
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


async def get_post(
    session: AsyncSession,
    file_path: str,
    *,
    draft_owner_username: str | None = None,
) -> PostDetail | None:
    """Get a single post by file path.

    When *draft_owner_username* is provided (i.e., the requester is the
    authenticated admin), draft posts are visible.  Otherwise drafts are
    hidden (returns ``None``).
    """
    stmt = _select_posts_with_author().where(PostCache.file_path == file_path)
    result = await session.execute(stmt)
    row = result.one_or_none()

    if row is None:
        return None

    post = row[0]
    display_author = row[1]

    if post.is_draft and not draft_owner_username:
        return None

    post_label_ids = await _post_labels(session, post.id)

    return PostDetail(
        id=post.id,
        file_path=post.file_path,
        title=post.title,
        subtitle=post.subtitle,
        author=display_author,
        created_at=format_iso(post.created_at),
        modified_at=format_iso(post.modified_at),
        is_draft=post.is_draft,
        rendered_excerpt=post.rendered_excerpt,
        labels=post_label_ids,
        rendered_html=post.rendered_html or "",
        content=None,  # Raw content not included in public view; use the /edit endpoint
    )


async def search_posts(session: AsyncSession, query: str, *, limit: int = 20) -> list[SearchResult]:
    """Full-text search for posts."""
    # Build FTS5 query with prefix matching: each word becomes "word"* so that
    # e.g. "test" matches "testing". Double-quote wrapping escapes special chars.
    terms = query.split()
    if not terms:
        return []
    safe_query = " ".join('"' + t.replace('"', '""') + '"*' for t in terms if t)
    stmt = text("""
        SELECT p.id, p.file_path, p.title, p.subtitle, p.rendered_excerpt, p.created_at,
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
        created_at_val = r[5]
        if isinstance(created_at_val, datetime):
            created_at_str = format_iso(created_at_val)
        else:
            created_at_str = str(created_at_val)
        results.append(
            SearchResult(
                id=r[0],
                file_path=r[1],
                title=r[2],
                subtitle=r[3],
                rendered_excerpt=r[4],
                created_at=created_at_str,
                rank=float(r[6]) if r[6] else 0.0,
            )
        )
    return results


async def get_posts_by_label(
    session: AsyncSession,
    label_id: str,
    *,
    page: int = 1,
    per_page: int = 20,
    draft_owner_username: str | None = None,
) -> PostListResponse:
    """Get posts for a specific label (exact match only, no descendants)."""
    return await list_posts(
        session,
        page=page,
        per_page=per_page,
        label=label_id,
        include_descendants=False,
        draft_owner_username=draft_owner_username,
    )
