"""Database cache regeneration from filesystem."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from sqlalchemy import delete, text

from backend.filesystem.content_manager import ContentManager, hash_content
from backend.models.label import LabelCache, LabelParentCache, PostLabelCache
from backend.models.post import PostCache
from backend.pandoc.renderer import render_markdown, render_markdown_excerpt, rewrite_relative_urls
from backend.services.dag import break_cycles
from backend.services.label_service import ensure_label_cache_entry

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def rebuild_cache(
    session: AsyncSession, content_manager: ContentManager
) -> tuple[int, list[str]]:
    """Rebuild all cache tables from filesystem.

    Returns a tuple of (post_count, warnings) where warnings contains messages
    about any cyclic label edges that were dropped.
    """
    # Clear existing cache
    await session.execute(delete(PostLabelCache))
    await session.execute(delete(LabelParentCache))
    await session.execute(delete(PostCache))
    await session.execute(delete(LabelCache))

    # Drop and recreate FTS table
    await session.execute(text("DROP TABLE IF EXISTS posts_fts"))
    await session.execute(
        text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5("
            "title, content, content='posts_cache', content_rowid='id')"
        )
    )

    # Load labels from config
    labels_config = content_manager.labels
    for label_id, label_def in labels_config.items():
        label = LabelCache(
            id=label_id,
            names=json.dumps(label_def.names),
            is_implicit=False,
        )
        session.add(label)

    await session.flush()

    # Collect all edges and run cycle detection
    all_edges: list[tuple[str, str]] = []
    implicit_created: set[str] = set()
    for label_id, label_def in labels_config.items():
        for parent_id in label_def.parents:
            # Ensure parent label exists in DB
            if parent_id not in labels_config and parent_id not in implicit_created:
                parent_label = LabelCache(id=parent_id, names="[]", is_implicit=True)
                session.add(parent_label)
                await session.flush()
                implicit_created.add(parent_id)
            all_edges.append((label_id, parent_id))

    accepted_edges, dropped_edges = break_cycles(all_edges)
    warnings: list[str] = []
    for child, parent in dropped_edges:
        msg = f"Cycle detected: dropped edge #{child} \u2192 #{parent}"
        logger.warning(msg)
        warnings.append(msg)

    for label_id, parent_id in accepted_edges:
        edge = LabelParentCache(label_id=label_id, parent_id=parent_id)
        session.add(edge)

    await session.flush()

    # Scan and index posts
    posts = content_manager.scan_posts()
    post_count = 0

    for post_data in posts:
        content_h = hash_content(post_data.raw_content)

        # Render HTML — skip this post if rendering fails
        try:
            rendered_html = await render_markdown(post_data.content)
            rendered_excerpt = await render_markdown_excerpt(
                content_manager.get_markdown_excerpt(post_data)
            )
        except RuntimeError as exc:
            msg = f"Skipping post {post_data.file_path!r} ({post_data.title}): {exc}"
            logger.warning(msg)
            warnings.append(msg)
            continue
        rendered_html = rewrite_relative_urls(rendered_html, post_data.file_path)
        rendered_excerpt = rewrite_relative_urls(rendered_excerpt, post_data.file_path)

        post = PostCache(
            file_path=post_data.file_path,
            title=post_data.title,
            author=post_data.author,
            created_at=post_data.created_at,
            modified_at=post_data.modified_at,
            is_draft=post_data.is_draft,
            content_hash=content_h,
            rendered_excerpt=rendered_excerpt,
            rendered_html=rendered_html,
        )
        session.add(post)
        await session.flush()

        # Index in FTS
        await session.execute(
            text("INSERT INTO posts_fts(rowid, title, content) VALUES (:rowid, :title, :content)"),
            {
                "rowid": post.id,
                "title": post_data.title,
                "content": post_data.content,
            },
        )

        # Add label associations
        for label_id in post_data.labels:
            await ensure_label_cache_entry(session, label_id)
            session.add(PostLabelCache(post_id=post.id, label_id=label_id))

        post_count += 1

    await session.commit()
    logger.info("Cache rebuilt: %d posts indexed", post_count)
    return post_count, warnings


async def ensure_tables(session: AsyncSession) -> None:
    """Create all tables if they don't exist (for development)."""
    from backend.models.base import Base

    conn = await session.connection()
    await conn.run_sync(Base.metadata.create_all)

    # Create FTS table
    await session.execute(
        text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5("
            "title, content, content='posts_cache', content_rowid='id')"
        )
    )
    await session.commit()
