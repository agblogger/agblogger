"""Tests for label DAG operations."""

from __future__ import annotations

import tomllib
from collections import defaultdict, deque
from typing import TYPE_CHECKING

from sqlalchemy import select

from backend.filesystem.content_manager import ContentManager
from backend.models.label import LabelCache, LabelParentCache
from backend.services.cache_service import ensure_tables, rebuild_cache
from backend.services.dag import break_cycles

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class TestLabelParsing:
    def test_parse_empty_labels_toml(self, tmp_content_dir: Path) -> None:
        labels_path = tmp_content_dir / "labels.toml"
        data = tomllib.loads(labels_path.read_text())
        assert "labels" in data
        assert data["labels"] == {}

    def test_parse_labels_toml_with_entries(self, tmp_path: Path) -> None:
        toml_content = """\
[labels]
  [labels.cs]
  names = ["computer science"]

  [labels.swe]
  names = ["software engineering", "programming"]
  parent = "#cs"
"""
        labels_path = tmp_path / "labels.toml"
        labels_path.write_text(toml_content)

        data = tomllib.loads(labels_path.read_text())
        assert "cs" in data["labels"]
        assert "swe" in data["labels"]
        assert data["labels"]["swe"]["parent"] == "#cs"
        assert "programming" in data["labels"]["swe"]["names"]


class TestBreakCycles:
    def test_no_cycles(self) -> None:
        edges = [("swe", "cs"), ("ai", "cs")]
        accepted, dropped = break_cycles(edges)
        assert set(accepted) == {("swe", "cs"), ("ai", "cs")}
        assert dropped == []

    def test_single_cycle(self) -> None:
        edges = [("a", "b"), ("b", "c"), ("c", "a")]
        accepted, dropped = break_cycles(edges)
        assert len(dropped) == 1
        assert _is_dag(accepted)

    def test_self_loop(self) -> None:
        edges = [("a", "a")]
        accepted, dropped = break_cycles(edges)
        assert accepted == []
        assert dropped == [("a", "a")]

    def test_multiple_cycles(self) -> None:
        edges = [("a", "b"), ("b", "a"), ("c", "d"), ("d", "c")]
        accepted, dropped = break_cycles(edges)
        assert len(dropped) == 2
        assert _is_dag(accepted)

    def test_diamond_no_cycle(self) -> None:
        edges = [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")]
        accepted, dropped = break_cycles(edges)
        assert set(accepted) == set(edges)
        assert dropped == []

    def test_diamond_with_cycle(self) -> None:
        edges = [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d"), ("d", "a")]
        accepted, dropped = break_cycles(edges)
        assert len(dropped) >= 1
        assert _is_dag(accepted)

    def test_empty(self) -> None:
        accepted, dropped = break_cycles([])
        assert accepted == []
        assert dropped == []


class TestCacheCycleEnforcement:
    async def test_rebuild_cache_drops_cyclic_edges(
        self,
        db_session: AsyncSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        tmp_content_dir: Path,
    ) -> None:
        (tmp_content_dir / "labels.toml").write_text(
            "[labels]\n"
            '[labels.a]\nnames = ["A"]\nparent = "#b"\n'
            '[labels.b]\nnames = ["B"]\nparent = "#c"\n'
            '[labels.c]\nnames = ["C"]\nparent = "#a"\n'
        )
        await ensure_tables(db_session)
        cm = ContentManager(tmp_content_dir)
        _post_count, warnings = await rebuild_cache(db_session_factory, cm)

        # All 3 labels should exist
        result = await db_session.execute(select(LabelCache))
        labels = {r.id for r in result.scalars().all()}
        assert labels == {"a", "b", "c"}

        # At least one edge should have been dropped to break the cycle
        edge_result = await db_session.execute(select(LabelParentCache))
        edges = [(e.label_id, e.parent_id) for e in edge_result.scalars().all()]
        assert len(edges) == 2  # 3 edges - 1 dropped = 2
        assert len(warnings) == 1

    async def test_rebuild_cache_no_warnings_when_no_cycles(
        self,
        db_session: AsyncSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        tmp_content_dir: Path,
    ) -> None:
        (tmp_content_dir / "labels.toml").write_text(
            '[labels]\n[labels.cs]\nnames = ["CS"]\n[labels.swe]\nnames = ["SWE"]\nparent = "#cs"\n'
        )
        await ensure_tables(db_session)
        cm = ContentManager(tmp_content_dir)
        _post_count, warnings = await rebuild_cache(db_session_factory, cm)
        assert warnings == []

        edge_result = await db_session.execute(select(LabelParentCache))
        edges = [(e.label_id, e.parent_id) for e in edge_result.scalars().all()]
        assert len(edges) == 1
        assert ("swe", "cs") in edges


class TestDeeplyNestedHierarchy:
    async def test_deeply_nested_hierarchy(
        self,
        db_session: AsyncSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        tmp_content_dir: Path,
    ) -> None:
        """A chain of 12 labels A→B→C→...→L should return all descendants of root."""
        # Build a chain: label_a ← label_b ← label_c ← ... ← label_l
        label_ids = [chr(ord("a") + i) for i in range(12)]  # a..l
        lines = ["[labels]\n"]
        for i, lid in enumerate(label_ids):
            lines.append(f'[labels.{lid}]\nnames = ["{lid.upper()}"]\n')
            if i > 0:
                lines.append(f'parent = "#{label_ids[i - 1]}"\n')
        (tmp_content_dir / "labels.toml").write_text("".join(lines))

        await ensure_tables(db_session)
        cm = ContentManager(tmp_content_dir)
        await rebuild_cache(db_session_factory, cm)

        from sqlalchemy import text

        # Query descendants of root label "a"
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
        result = await db_session.execute(stmt, {"label_id": "a"})
        descendant_ids = {r[0] for r in result.all()}

        # All 12 labels should be descendants (including root itself)
        assert descendant_ids == set(label_ids)


def _is_dag(edges: list[tuple[str, str]]) -> bool:
    """Verify edges form a DAG using Kahn's algorithm."""
    children: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = defaultdict(int)
    nodes: set[str] = set()
    for child, parent in edges:
        children[parent].append(child)
        in_degree[child] += 1
        nodes.add(child)
        nodes.add(parent)

    queue = deque(n for n in nodes if in_degree[n] == 0)
    count = 0
    while queue:
        node = queue.popleft()
        count += 1
        for c in children[node]:
            in_degree[c] -= 1
            if in_degree[c] == 0:
                queue.append(c)
    return count == len(nodes)
