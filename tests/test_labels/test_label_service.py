"""Tests for label service cycle detection and batch descendant queries."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.models.base import CacheBase, DurableBase
from backend.models.label import LabelCache, LabelParentCache, PostLabelCache
from backend.models.post import PostCache
from backend.services.cache_service import ensure_tables
from backend.services.label_service import get_label_descendants_batch, would_create_cycle
from backend.services.post_service import list_posts

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine


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

    async def test_diamond_dag_no_duplicates(self, db_session: AsyncSession) -> None:
        """Diamond-shaped DAG: querying both parents returns child exactly once.

        Structure:
            grandparent
           /           \\
        parent-a    parent-b
           \\           /
             child

        When both parent-a and parent-b are seeds, child is reachable via two
        paths.  UNION (not UNION ALL) in the CTE ensures child appears only once
        in each parent's descendant set.
        """
        await ensure_tables(db_session)
        for lid in ["grandparent", "parent-a", "parent-b", "child"]:
            db_session.add(LabelCache(id=lid, names="[]"))
        # parent-a and parent-b are children of grandparent
        db_session.add(LabelParentCache(label_id="parent-a", parent_id="grandparent"))
        db_session.add(LabelParentCache(label_id="parent-b", parent_id="grandparent"))
        # child has two parents: parent-a and parent-b (diamond)
        db_session.add(LabelParentCache(label_id="child", parent_id="parent-a"))
        db_session.add(LabelParentCache(label_id="child", parent_id="parent-b"))
        await db_session.flush()

        # Query both parents simultaneously — child must appear exactly once per parent set
        result = await get_label_descendants_batch(db_session, ["parent-a", "parent-b"])

        assert result["parent-a"] == {"parent-a", "child"}
        assert result["parent-b"] == {"parent-b", "child"}

        # Verify no duplicates by checking the sets are exactly the expected size
        assert len(result["parent-a"]) == 2
        assert len(result["parent-b"]) == 2


# ---------------------------------------------------------------------------
# Fixtures for list_posts tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def post_db_engine(tmp_path: Path) -> AsyncGenerator[AsyncEngine]:
    """In-memory SQLite engine with all tables for post_service tests."""
    db_path = tmp_path / "test_label_list_posts.db"
    from sqlalchemy import text

    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(DurableBase.metadata.create_all)
        await conn.run_sync(CacheBase.metadata.create_all)
    async with eng.begin() as conn:
        await conn.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5("
                "title, content, content='posts_cache', content_rowid='id')"
            )
        )
    yield eng
    await eng.dispose()


@pytest.fixture
async def post_session(post_db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    """Session for the post_service test database."""
    factory = async_sessionmaker(post_db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess


def _make_post(file_path: str, title: str) -> PostCache:
    now = datetime.now(UTC)
    return PostCache(
        file_path=file_path,
        title=title,
        author=None,
        created_at=now,
        modified_at=now,
        is_draft=False,
        content_hash="abc",
        rendered_excerpt=None,
        rendered_html="<p>test</p>",
    )


class TestListPostsIncludeDescendantsDefault:
    """list_posts include_descendants default must be False (exact-match behaviour)."""

    async def test_default_is_exact_match_no_descendant_expansion(
        self, post_session: AsyncSession
    ) -> None:
        """Calling list_posts without include_descendants should not expand descendants.

        Setup: parent label 'tech' with child label 'python'.
        Post A is tagged with 'tech' only.
        Post B is tagged with 'python' only.

        Filtering by label='python' without specifying include_descendants should
        return only Post B (exact match), NOT Post A.  If the default were True,
        descendants of 'python' would be expanded but 'tech' would appear via the
        parent path from Post A only if queried under 'tech' — so the interesting
        direction is: querying 'tech' should NOT pull in Post B when the default
        is False (no descendant expansion from 'tech' to 'python').
        """
        # Create labels: tech (parent) <- python (child)
        post_session.add(LabelCache(id="tech", names=json.dumps(["Tech"])))
        post_session.add(LabelCache(id="python", names=json.dumps(["Python"])))
        post_session.add(LabelParentCache(label_id="python", parent_id="tech"))
        await post_session.flush()

        # Post A: tagged 'tech' only
        post_a = _make_post("posts/post-a/index.md", "Post A")
        post_session.add(post_a)
        await post_session.flush()
        post_session.add(PostLabelCache(post_id=post_a.id, label_id="tech"))

        # Post B: tagged 'python' only
        post_b = _make_post("posts/post-b/index.md", "Post B")
        post_session.add(post_b)
        await post_session.flush()
        post_session.add(PostLabelCache(post_id=post_b.id, label_id="python"))

        await post_session.flush()

        # Query by 'tech' WITHOUT specifying include_descendants (should use default=False)
        # With default=False: only posts tagged directly with 'tech' → Post A only
        # With default=True: 'tech' descendants include 'python', so Post B would also appear
        result = await list_posts(post_session, label="tech")

        titles = [p.title for p in result.posts]
        assert "Post A" in titles, "Post A (tagged 'tech') should appear in exact-match query"
        assert "Post B" not in titles, (
            "Post B (tagged 'python', a child of 'tech') must NOT appear when "
            "include_descendants defaults to False"
        )
