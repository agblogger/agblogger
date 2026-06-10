"""Text processing utilities."""

from __future__ import annotations

import re


def count_words(body: str) -> int:
    """Count prose words in a markdown body.

    Strips fenced code blocks and inline code before counting so that
    code tokens do not inflate the reading-time estimate.
    """
    body = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
    body = re.sub(r"`[^`\n]*`", "", body)
    return len(body.split())
