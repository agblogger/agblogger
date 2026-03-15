"""Tests for label service cycle detection and batch descendant queries."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from backend.models.label import LabelCache, LabelParentCache
from backend.services.cache_service import ensure_tables
from backend.services.label_service import get_label_descendants_batch, would_create_cycle

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class TestWouldCreateCycle:
    async def test_no_cycle_simple(self, db_session: AsyncSession) -> None:
        await ensure_tables(db_session)
        db_session.add(LabelCache(id="cs", names=json.dumps(["CS"])))
        db_session.add(LabelCache(id="swe", names=json.dumps(["SWE"])))
        await db_session.flush()

        assert not await would_create_cycle(db_session, "swe", "cs")

    async def test_direct_cycle(self, db_session: AsyncSession) -> None:
        await ensure_tables(db_session)
        db_session.add(LabelCache(id="a", names="[]"))
        db_session.add(LabelCache(id="b", names="[]"))
        db_session.add(LabelParentCache(label_id="a", parent_id="b"))
        await db_session.flush()

        # b -> a would create cycle (a already has parent b)
        assert await would_create_cycle(db_session, "b", "a")

    async def test_indirect_cycle(self, db_session: AsyncSession) -> None:
        await ensure_tables(db_session)
        db_session.add(LabelCache(id="a", names="[]"))
        db_session.add(LabelCache(id="b", names="[]"))
        db_session.add(LabelCache(id="c", names="[]"))
        db_session.add(LabelParentCache(label_id="a", parent_id="b"))
        db_session.add(LabelParentCache(label_id="b", parent_id="c"))
        await db_session.flush()

        # c -> a would create cycle (a -> b -> c already exists)
        assert await would_create_cycle(db_session, "c", "a")

    async def test_self_loop(self, db_session: AsyncSession) -> None:
        await ensure_tables(db_session)
        db_session.add(LabelCache(id="a", names="[]"))
        await db_session.flush()

        assert await would_create_cycle(db_session, "a", "a")

    async def test_multi_parent_no_cycle(self, db_session: AsyncSession) -> None:
        await ensure_tables(db_session)
        for lid in ["a", "b", "c", "d"]:
            db_session.add(LabelCache(id=lid, names="[]"))
        db_session.add(LabelParentCache(label_id="a", parent_id="b"))
        db_session.add(LabelParentCache(label_id="a", parent_id="c"))
        db_session.add(LabelParentCache(label_id="b", parent_id="d"))
        await db_session.flush()

        # c -> d is fine (diamond shape, no cycle)
        assert not await would_create_cycle(db_session, "c", "d")

    async def test_multi_parent_cycle_through_one_branch(self, db_session: AsyncSession) -> None:
        """Cycle exists through one parent branch but not the other."""
        await ensure_tables(db_session)
        for lid in ["a", "b", "c", "d"]:
            db_session.add(LabelCache(id=lid, names="[]"))
        # A has parents B and C. B has parent D.
        db_session.add(LabelParentCache(label_id="a", parent_id="b"))
        db_session.add(LabelParentCache(label_id="a", parent_id="c"))
        db_session.add(LabelParentCache(label_id="b", parent_id="d"))
        await db_session.flush()

        # D -> A would create cycle (A -> B -> D exists)
        assert await would_create_cycle(db_session, "d", "a")
        # C -> D is fine (no cycle path)
        assert not await would_create_cycle(db_session, "c", "d")

    async def test_no_existing_edges(self, db_session: AsyncSession) -> None:
        await ensure_tables(db_session)
        db_session.add(LabelCache(id="x", names="[]"))
        db_session.add(LabelCache(id="y", names="[]"))
        await db_session.flush()

        assert not await would_create_cycle(db_session, "x", "y")
        assert not await would_create_cycle(db_session, "y", "x")


class TestGetLabelDescendantsBatch:
    async def test_single_label_no_children(self, db_session: AsyncSession) -> None:
        """A label with no children returns a set containing only itself."""
        await ensure_tables(db_session)
        db_session.add(LabelCache(id="root", names="[]"))
        await db_session.flush()

        result = await get_label_descendants_batch(db_session, ["root"])
        assert result == {"root": {"root"}}

    async def test_single_label_with_children(self, db_session: AsyncSession) -> None:
        """A label and its direct children are all returned."""
        await ensure_tables(db_session)
        for lid in ["parent", "child1", "child2"]:
            db_session.add(LabelCache(id=lid, names="[]"))
        db_session.add(LabelParentCache(label_id="child1", parent_id="parent"))
        db_session.add(LabelParentCache(label_id="child2", parent_id="parent"))
        await db_session.flush()

        result = await get_label_descendants_batch(db_session, ["parent"])
        assert result == {"parent": {"parent", "child1", "child2"}}

    async def test_multiple_labels_independent(self, db_session: AsyncSession) -> None:
        """Two independent roots each get their own descendant set."""
        await ensure_tables(db_session)
        for lid in ["a", "b", "c", "d"]:
            db_session.add(LabelCache(id=lid, names="[]"))
        db_session.add(LabelParentCache(label_id="b", parent_id="a"))
        db_session.add(LabelParentCache(label_id="d", parent_id="c"))
        await db_session.flush()

        result = await get_label_descendants_batch(db_session, ["a", "c"])
        assert result == {"a": {"a", "b"}, "c": {"c", "d"}}

    async def test_multiple_labels_overlapping_descendants(self, db_session: AsyncSession) -> None:
        """When two seeds share descendants, each mapping is correct independently."""
        await ensure_tables(db_session)
        for lid in ["grandparent", "parent", "child"]:
            db_session.add(LabelCache(id=lid, names="[]"))
        db_session.add(LabelParentCache(label_id="parent", parent_id="grandparent"))
        db_session.add(LabelParentCache(label_id="child", parent_id="parent"))
        await db_session.flush()

        result = await get_label_descendants_batch(db_session, ["grandparent", "parent"])
        assert result["grandparent"] == {"grandparent", "parent", "child"}
        assert result["parent"] == {"parent", "child"}

    async def test_empty_input(self, db_session: AsyncSession) -> None:
        """Empty input returns an empty dict."""
        await ensure_tables(db_session)
        result = await get_label_descendants_batch(db_session, [])
        assert result == {}

    async def test_nonexistent_label(self, db_session: AsyncSession) -> None:
        """A label ID not in the DB still returns a set containing itself."""
        await ensure_tables(db_session)
        result = await get_label_descendants_batch(db_session, ["ghost"])
        assert result == {"ghost": {"ghost"}}

    async def test_deep_chain(self, db_session: AsyncSession) -> None:
        """Transitive descendants across multiple levels are included."""
        await ensure_tables(db_session)
        label_ids = ["a", "b", "c", "d", "e"]
        for lid in label_ids:
            db_session.add(LabelCache(id=lid, names="[]"))
        # chain: a <- b <- c <- d <- e
        for i in range(1, len(label_ids)):
            db_session.add(LabelParentCache(label_id=label_ids[i], parent_id=label_ids[i - 1]))
        await db_session.flush()

        result = await get_label_descendants_batch(db_session, ["a"])
        assert result == {"a": set(label_ids)}

    async def test_or_mode_union(self, db_session: AsyncSession) -> None:
        """Verifies that OR-mode post filtering can union results from the batch."""
        await ensure_tables(db_session)
        for lid in ["x", "y", "z"]:
            db_session.add(LabelCache(id=lid, names="[]"))
        db_session.add(LabelParentCache(label_id="y", parent_id="x"))
        await db_session.flush()

        result = await get_label_descendants_batch(db_session, ["x", "z"])
        all_ids: set[str] = set()
        for s in result.values():
            all_ids.update(s)
        assert all_ids == {"x", "y", "z"}
