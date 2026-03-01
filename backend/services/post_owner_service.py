"""Utilities for resolving stable post ownership."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from sqlalchemy import select

from backend.models.user import User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def build_owner_lookup(session: AsyncSession) -> tuple[set[str], dict[str, str]]:
    """Build username and unique-display-name lookup tables."""
    result = await session.execute(select(User.username, User.display_name))
    rows = list(result.all())

    usernames = {str(username) for username, _display_name in rows}
    display_name_counts = Counter(
        display_name
        for _username, display_name in rows
        if isinstance(display_name, str) and display_name
    )
    unique_display_names = {
        str(display_name): str(username)
        for username, display_name in rows
        if isinstance(display_name, str) and display_name and display_name_counts[display_name] == 1
    }
    return usernames, unique_display_names


def resolve_owner_username(
    *,
    author_username: str | None,
    author: str | None,
    usernames: set[str],
    unique_display_names: dict[str, str],
) -> str | None:
    """Resolve a stable owner username from stored ownership metadata."""
    if author_username and author_username in usernames:
        return author_username
    if author and author in usernames:
        return author
    if author and author in unique_display_names:
        return unique_display_names[author]
    return None
