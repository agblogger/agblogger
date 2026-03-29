"""Tests for cache rebuild resilience against crashes."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from backend.filesystem.content_manager import ContentManager
from backend.models.label import LabelCache, LabelParentCache
from backend.models.page import PageCache
from backend.models.post import PostCache
from backend.services.cache_service import ensure_tables, rebuild_cache

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class TestDuplicateImplicitLabel:
    async def test_multiple_labels_referencing_same_undefined_parent(
        self,
        db_session: AsyncSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        tmp_content_dir: Path,
    ) -> None:
        """Two labels sharing the same undefined parent must not crash.

        Previously, the code would try to INSERT duplicate LabelCache entries
        for the implicit parent, causing IntegrityError.
        """
        (tmp_content_dir / "labels.toml").write_text(
            "[labels]\n"
            '[labels.frontend]\nnames = ["frontend"]\nparent = "#web"\n'
            '[labels.backend]\nnames = ["backend"]\nparent = "#web"\n'
        )
        await ensure_tables(db_session)
        cm = ContentManager(tmp_content_dir)
        _post_count, _warnings = await rebuild_cache(db_session_factory, cm)

        # The implicit "web" label should exist exactly once
        result = await db_session.execute(select(LabelCache).where(LabelCache.id == "web"))
        web_labels = result.scalars().all()
        assert len(web_labels) == 1
        assert web_labels[0].is_implicit is True

        # Both edges should exist
        edge_result = await db_session.execute(select(LabelParentCache))
        edges = [(e.label_id, e.parent_id) for e in edge_result.scalars().all()]
        assert ("frontend", "web") in edges
        assert ("backend", "web") in edges

    async def test_three_labels_referencing_same_undefined_parent(
        self,
        db_session: AsyncSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        tmp_content_dir: Path,
    ) -> None:
        """Three labels sharing the same undefined parent must not crash."""
        (tmp_content_dir / "labels.toml").write_text(
            "[labels]\n"
            '[labels.a]\nnames = ["A"]\nparent = "#missing"\n'
            '[labels.b]\nnames = ["B"]\nparent = "#missing"\n'
            '[labels.c]\nnames = ["C"]\nparent = "#missing"\n'
        )
        await ensure_tables(db_session)
        cm = ContentManager(tmp_content_dir)
        _post_count, _warnings = await rebuild_cache(db_session_factory, cm)

        result = await db_session.execute(select(LabelCache).where(LabelCache.id == "missing"))
        assert len(result.scalars().all()) == 1


def _write_post(content_dir: Path, slug: str, title: str, body: str) -> None:
    """Write a minimal markdown post to the content directory."""
    post_path = content_dir / "posts" / slug / "index.md"
    post_path.parent.mkdir(parents=True, exist_ok=True)
    post_path.write_text(
        f"---\ntitle: {title}\ncreated_at: 2026-02-02 12:00:00+00\n---\n{body}\n",
        encoding="utf-8",
    )


class TestPandocFailureResilience:
    async def test_pandoc_failure_skips_post_without_crashing(
        self,
        db_session: AsyncSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        tmp_content_dir: Path,
    ) -> None:
        """A pandoc failure on one post must not prevent other posts from being indexed."""
        _write_post(tmp_content_dir, "good", "Good Post", "This is fine.")
        _write_post(tmp_content_dir, "bad", "Bad Post", "This will fail pandoc.")

        async def failing_render(markdown: str) -> str:
            if "will fail pandoc" in markdown:
                raise RuntimeError("Pandoc rendering failed")
            return f"<p>{markdown}</p>"

        await ensure_tables(db_session)
        cm = ContentManager(tmp_content_dir)

        with (
            patch(
                "backend.services.cache_service.render_markdown",
                side_effect=failing_render,
            ),
            patch(
                "backend.services.cache_service.render_markdown_excerpt",
                side_effect=failing_render,
            ),
        ):
            post_count, warnings = await rebuild_cache(db_session_factory, cm)

        # Good post should be indexed
        result = await db_session.execute(select(PostCache))
        posts = result.scalars().all()
        assert len(posts) == 1
        assert posts[0].title == "Good Post"

        # The bad post should produce a warning
        assert post_count == 1
        assert any("Bad Post" in w or "bad.md" in w for w in warnings)

    async def test_pandoc_not_installed_skips_all_posts_without_crashing(
        self,
        db_session: AsyncSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        tmp_content_dir: Path,
    ) -> None:
        """If pandoc is not installed, posts are skipped but the server still starts."""
        _write_post(tmp_content_dir, "post1", "First", "Content one.")
        _write_post(tmp_content_dir, "post2", "Second", "Content two.")

        async def always_fail(markdown: str) -> str:
            raise RuntimeError("Pandoc is not installed")

        await ensure_tables(db_session)
        cm = ContentManager(tmp_content_dir)

        with (
            patch(
                "backend.services.cache_service.render_markdown",
                side_effect=always_fail,
            ),
            patch(
                "backend.services.cache_service.render_markdown_excerpt",
                side_effect=always_fail,
            ),
        ):
            post_count, warnings = await rebuild_cache(db_session_factory, cm)

        assert post_count == 0
        assert len(warnings) == 2


class TestPageCacheRebuild:
    """Test that rebuild_cache populates PageCache for file-backed pages."""

    async def test_rebuild_caches_file_backed_pages(
        self,
        db_session: AsyncSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        tmp_path: Path,
    ) -> None:
        content_dir = tmp_path / "page_test_content"
        content_dir.mkdir()
        (content_dir / "posts").mkdir()
        (content_dir / "index.toml").write_text(
            '[site]\ntitle = "T"\ndescription = "D"\ntimezone = "UTC"\n\n'
            '[[pages]]\nid = "about"\ntitle = "About"\nfile = "about.md"\n\n'
            '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        )
        (content_dir / "labels.toml").write_text("[labels]\n")
        (content_dir / "about.md").write_text("# About\n\nHello.\n")
        cm = ContentManager(content_dir=content_dir)

        await ensure_tables(db_session)

        with patch(
            "backend.services.cache_service.render_markdown",
            new_callable=AsyncMock,
            return_value="<h1>About</h1>\n<p>Hello.</p>",
        ):
            await rebuild_cache(db_session_factory, cm)

        async with db_session_factory() as session:
            pages = (await session.execute(select(PageCache))).scalars().all()
            assert len(pages) == 1
            assert pages[0].page_id == "about"
            assert pages[0].title == "About"
            assert "<h1>About</h1>" in pages[0].rendered_html

    async def test_rebuild_skips_pages_without_file(
        self,
        db_session: AsyncSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        tmp_path: Path,
    ) -> None:
        content_dir = tmp_path / "page_test_content"
        content_dir.mkdir()
        (content_dir / "posts").mkdir()
        (content_dir / "index.toml").write_text(
            '[site]\ntitle = "T"\ndescription = "D"\ntimezone = "UTC"\n\n'
            '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        )
        (content_dir / "labels.toml").write_text("[labels]\n")
        cm = ContentManager(content_dir=content_dir)

        await ensure_tables(db_session)
        await rebuild_cache(db_session_factory, cm)

        async with db_session_factory() as session:
            pages = (await session.execute(select(PageCache))).scalars().all()
            assert len(pages) == 0

    async def test_rebuild_skips_page_with_missing_file(
        self,
        db_session: AsyncSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        tmp_path: Path,
    ) -> None:
        content_dir = tmp_path / "page_test_content"
        content_dir.mkdir()
        (content_dir / "posts").mkdir()
        (content_dir / "index.toml").write_text(
            '[site]\ntitle = "T"\ndescription = "D"\ntimezone = "UTC"\n\n'
            '[[pages]]\nid = "about"\ntitle = "About"\nfile = "about.md"\n'
        )
        (content_dir / "labels.toml").write_text("[labels]\n")
        # about.md intentionally not created
        cm = ContentManager(content_dir=content_dir)

        await ensure_tables(db_session)
        await rebuild_cache(db_session_factory, cm)

        async with db_session_factory() as session:
            pages = (await session.execute(select(PageCache))).scalars().all()
            assert len(pages) == 0


class TestRebuildCacheSessionIsolation:
    """rebuild_cache must use its own session to avoid committing the caller's transaction."""

    async def test_rebuild_cache_creates_own_session(
        self,
        db_session: AsyncSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        tmp_content_dir: Path,
    ) -> None:
        """rebuild_cache must create its own session and not touch the caller's.

        Verifies that rebuild_cache uses the session factory to create an
        independent session, so callers can hold uncommitted changes without
        having them prematurely committed by the cache rebuild.
        """
        await ensure_tables(db_session)
        cm = ContentManager(tmp_content_dir)

        # Create a tracking wrapper around the session factory
        call_count = 0
        real_factory = db_session_factory

        class TrackingFactory:
            """Wraps async_sessionmaker to count calls."""

            def __call__(self) -> AsyncSession:
                nonlocal call_count
                call_count += 1
                return real_factory()

        tracking = TrackingFactory()

        # Pass the tracking wrapper as if it were the session factory
        await rebuild_cache(tracking, cm)  # type: ignore[arg-type]

        # rebuild_cache must have created its own session via the factory
        assert call_count == 1, (
            f"Expected rebuild_cache to create exactly 1 session, got {call_count}"
        )


class TestPagePandocFailureResilience:
    """Pandoc failure for a page should not crash rebuild_cache."""

    async def test_pandoc_failure_skips_page_without_crashing(
        self,
        db_session: AsyncSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        tmp_path: Path,
    ) -> None:
        content_dir = tmp_path / "page_pandoc_test"
        content_dir.mkdir()
        (content_dir / "posts").mkdir()
        (content_dir / "index.toml").write_text(
            '[site]\ntitle = "T"\ndescription = "D"\ntimezone = "UTC"\n\n'
            '[[pages]]\nid = "good"\ntitle = "Good"\nfile = "good.md"\n\n'
            '[[pages]]\nid = "bad"\ntitle = "Bad"\nfile = "bad.md"\n'
        )
        (content_dir / "labels.toml").write_text("[labels]\n")
        (content_dir / "good.md").write_text("# Good\n\nGood page.\n")
        (content_dir / "bad.md").write_text("# Bad\n\nBad page.\n")
        cm = ContentManager(content_dir=content_dir)

        await ensure_tables(db_session)

        async def failing_render(markdown: str) -> str:
            if "Bad page" in markdown:
                raise RuntimeError("Pandoc failed")
            return f"<p>{markdown}</p>"

        with patch(
            "backend.services.cache_service.render_markdown",
            side_effect=failing_render,
        ):
            await rebuild_cache(db_session_factory, cm)

        async with db_session_factory() as session:
            pages = (await session.execute(select(PageCache))).scalars().all()
            assert len(pages) == 1
            assert pages[0].page_id == "good"
