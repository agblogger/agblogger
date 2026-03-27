"""Label service: DAG operations and queries."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select, text

from backend.models.label import LabelCache, LabelParentCache, PostLabelCache
from backend.models.post import PostCache
from backend.schemas.label import (
    LabelGraphEdge,
    LabelGraphNode,
    LabelGraphResponse,
    LabelResponse,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


_JSON_PARSE_ERRORS = (json.JSONDecodeError, TypeError)


def _safe_parse_names(raw: str) -> list[str]:
    """Parse label names JSON, returning empty list on error."""
    try:
        result = json.loads(raw)
    except _JSON_PARSE_ERRORS:
        logger.warning("Invalid label names JSON: %s", raw[:100])
        return []
    return result if isinstance(result, list) else []


async def ensure_label_cache_entry(session: AsyncSession, label_id: str) -> None:
    """Ensure a label exists in cache tables, creating an implicit label if needed."""
    existing = await session.get(LabelCache, label_id)
    if existing is None:
        session.add(LabelCache(id=label_id, names="[]", is_implicit=True))
        await session.flush()


async def get_all_labels(
    session: AsyncSession,
    *,
    include_drafts: bool = False,
) -> list[LabelResponse]:
    """Get all labels with parent/child info and post counts.

    When *include_drafts* is True (i.e., the requester is the authenticated
    admin), post_count includes all posts including drafts.  Otherwise only
    published posts are counted.
    """
    # Get all labels
    stmt = select(LabelCache)
    result = await session.execute(stmt)
    labels = result.scalars().all()

    # Batch: get all parent relationships in one query
    parent_stmt = select(LabelParentCache)
    parent_result = await session.execute(parent_stmt)
    all_parents = parent_result.scalars().all()

    parents_map: dict[str, list[str]] = {}
    children_map: dict[str, list[str]] = {}
    for rel in all_parents:
        parents_map.setdefault(rel.label_id, []).append(rel.parent_id)
        children_map.setdefault(rel.parent_id, []).append(rel.label_id)

    # Batch: get all post counts in one query, filtered by visibility
    if include_drafts:
        count_stmt = select(PostLabelCache.label_id, func.count()).group_by(PostLabelCache.label_id)
    else:
        count_stmt = (
            select(PostLabelCache.label_id, func.count())
            .join(PostCache, PostLabelCache.post_id == PostCache.id)
            .where(PostCache.is_draft.is_(False))
            .group_by(PostLabelCache.label_id)
        )
    count_result = await session.execute(count_stmt)
    post_counts: dict[str, int] = {row[0]: row[1] for row in count_result.all()}

    responses: list[LabelResponse] = []
    for label in labels:
        responses.append(
            LabelResponse(
                id=label.id,
                names=_safe_parse_names(label.names),
                is_implicit=label.is_implicit,
                parents=parents_map.get(label.id, []),
                children=children_map.get(label.id, []),
                post_count=post_counts.get(label.id, 0),
            )
        )

    return responses


async def get_label(
    session: AsyncSession,
    label_id: str,
    *,
    include_drafts: bool = False,
) -> LabelResponse | None:
    """Get a single label by ID.

    When *include_drafts* is True (i.e., the requester is the authenticated
    admin), post_count includes all posts including drafts.  Otherwise only
    published posts are counted.
    """
    label = await session.get(LabelCache, label_id)
    if label is None:
        return None

    parent_stmt = select(LabelParentCache.parent_id).where(LabelParentCache.label_id == label_id)
    parent_result = await session.execute(parent_stmt)
    parents = [r[0] for r in parent_result.all()]

    child_stmt = select(LabelParentCache.label_id).where(LabelParentCache.parent_id == label_id)
    child_result = await session.execute(child_stmt)
    children = [r[0] for r in child_result.all()]

    if include_drafts:
        count_stmt = (
            select(func.count())
            .select_from(PostLabelCache)
            .where(PostLabelCache.label_id == label_id)
        )
    else:
        count_stmt = (
            select(func.count())
            .select_from(PostLabelCache)
            .join(PostCache, PostLabelCache.post_id == PostCache.id)
            .where(PostLabelCache.label_id == label_id)
            .where(PostCache.is_draft.is_(False))
        )
    count_result = await session.execute(count_stmt)
    post_count = count_result.scalar() or 0

    return LabelResponse(
        id=label.id,
        names=_safe_parse_names(label.names),
        is_implicit=label.is_implicit,
        parents=parents,
        children=children,
        post_count=post_count,
    )


async def get_label_descendant_ids(session: AsyncSession, label_id: str) -> list[str]:
    """Get all descendant label IDs using recursive CTE."""
    stmt = text("""
        WITH RECURSIVE descendants(id) AS (
            SELECT :label_id
            UNION ALL
            SELECT lp.label_id
            FROM label_parents_cache lp
            JOIN descendants d ON lp.parent_id = d.id
        )
        SELECT DISTINCT id FROM descendants
    """)
    result = await session.execute(stmt, {"label_id": label_id})
    return [r[0] for r in result.all()]


async def get_label_descendants_batch(
    session: AsyncSession,
    label_ids: list[str],
) -> dict[str, set[str]]:
    """Get all descendant label IDs for multiple seed labels in a single query.

    Returns a mapping of each input label ID to the set of all its descendants
    (including the label itself).  An empty input returns an empty dict.

    Uses ``json_each()`` to unpack the seed IDs from a single JSON array
    parameter so the SQL template is static (no dynamic string interpolation).
    """
    if not label_ids:
        return {}

    # Pass all seed IDs as a single JSON array.  json_each() unpacks them into
    # rows inside the query so the SQL itself contains no dynamic fragments.
    #
    # Query structure:
    #   seeds(root, id)       — one row per seed: (seed, seed)
    #   descendants(root, id) — recursive expansion via label_parents_cache
    #   Final SELECT returns (root, descendant) pairs.
    sql = text("""
        WITH RECURSIVE
        seeds(root, id) AS (
            SELECT je.value, je.value
            FROM json_each(:label_ids_json) AS je
        ),
        descendants(root, id) AS (
            SELECT root, id FROM seeds
            UNION
            SELECT d.root, lp.label_id
            FROM label_parents_cache lp
            JOIN descendants d ON lp.parent_id = d.id
        )
        SELECT root, id FROM descendants
    """)
    result = await session.execute(sql, {"label_ids_json": json.dumps(label_ids)})
    rows = result.all()

    mapping: dict[str, set[str]] = {lid: set() for lid in label_ids}
    for root, descendant in rows:
        mapping[root].add(descendant)
    return mapping


async def create_label(
    session: AsyncSession,
    label_id: str,
    names: list[str] | None = None,
    parents: list[str] | None = None,
) -> LabelResponse | None:
    """Create a new label. Returns None if it already exists.

    When *names* is None or an empty list, the label is created with no display names.
    Raises ValueError if adding a parent would create a cycle.
    """
    existing = await session.get(LabelCache, label_id)
    if existing is not None:
        return None

    display_names = names if names is not None else []
    label = LabelCache(
        id=label_id,
        names=json.dumps(display_names),
        is_implicit=False,
    )
    session.add(label)
    await session.flush()

    # Add parent edges with cycle detection (validate all before inserting any)
    if parents:
        for parent_id in parents:
            if await would_create_cycle(session, label_id, parent_id):
                raise ValueError(f"Adding parent '{parent_id}' would create a cycle")
        for parent_id in parents:
            edge = LabelParentCache(label_id=label_id, parent_id=parent_id)
            session.add(edge)
        await session.flush()

    return await get_label(session, label_id)


async def update_label(
    session: AsyncSession,
    label_id: str,
    names: list[str],
    parents: list[str],
) -> LabelResponse | None:
    """Update a label's names and parent edges.

    Deletes existing parent edges, checks for cycles with each new parent,
    then inserts new edges. Returns None if label not found.
    Raises ValueError if adding a parent would create a cycle.
    """
    label = await session.get(LabelCache, label_id)
    if label is None:
        return None

    # Update names
    label.names = json.dumps(names)

    # Delete existing parent edges first so cycle detection uses clean state
    await session.execute(delete(LabelParentCache).where(LabelParentCache.label_id == label_id))
    await session.flush()

    # Check all proposed parents for cycles against clean edge state
    for parent_id in parents:
        if await would_create_cycle(session, label_id, parent_id):
            raise ValueError(f"Adding parent '{parent_id}' would create a cycle")

    for parent_id in parents:
        edge = LabelParentCache(label_id=label_id, parent_id=parent_id)
        session.add(edge)

    await session.flush()
    return await get_label(session, label_id)


async def delete_label(session: AsyncSession, label_id: str) -> bool:
    """Delete a label and all its edges. Returns False if not found."""
    label = await session.get(LabelCache, label_id)
    if label is None:
        return False

    await session.delete(label)
    await session.flush()
    return True


async def would_create_cycle(
    session: AsyncSession,
    label_id: str,
    proposed_parent_id: str,
) -> bool:
    """Check if adding label_id -> proposed_parent_id would create a cycle.

    Walks ancestors of proposed_parent_id via recursive CTE. If label_id
    is found among those ancestors, the new edge would close a cycle.
    Also returns True for self-loops (label_id == proposed_parent_id).
    """
    if label_id == proposed_parent_id:
        return True

    stmt = text("""
        WITH RECURSIVE ancestors(id) AS (
            SELECT :proposed_parent_id
            UNION ALL
            SELECT lp.parent_id
            FROM label_parents_cache lp
            JOIN ancestors a ON lp.label_id = a.id
        )
        SELECT 1 FROM ancestors WHERE id = :label_id LIMIT 1
    """)
    result = await session.execute(
        stmt, {"proposed_parent_id": proposed_parent_id, "label_id": label_id}
    )
    return result.first() is not None


async def get_label_graph(
    session: AsyncSession,
    *,
    include_drafts: bool = False,
) -> LabelGraphResponse:
    """Get the full label DAG for visualization."""
    labels = await get_all_labels(session, include_drafts=include_drafts)

    nodes = [
        LabelGraphNode(
            id=label.id,
            names=label.names,
            post_count=label.post_count,
        )
        for label in labels
    ]

    # Reuse parent/child data already loaded by get_all_labels rather than
    # re-querying LabelParentCache.
    edges = [
        LabelGraphEdge(source=label.id, target=parent_id)
        for label in labels
        for parent_id in label.parents
    ]

    return LabelGraphResponse(nodes=nodes, edges=edges)
