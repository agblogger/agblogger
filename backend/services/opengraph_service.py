"""Open Graph and Twitter Card meta tag injection for crawler-friendly HTML."""

from __future__ import annotations

import html
import re

_MAX_DESCRIPTION_LENGTH = 200


def strip_html_tags(text: str) -> str:
    """Strip HTML tags, decode entities, and collapse whitespace.

    - Replaces HTML tags with spaces (preserves word boundaries)
    - Decodes HTML entities (named and numeric)
    - Collapses runs of whitespace into a single space
    - Strips leading/trailing whitespace
    """
    # Replace HTML tags with spaces
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode HTML entities
    text = html.unescape(text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def inject_og_tags(
    base_html: str,
    *,
    title: str,
    description: str,
    url: str,
    site_name: str | None = None,
    author: str | None = None,
    published_time: str | None = None,
    modified_time: str | None = None,
) -> str:
    """Inject Open Graph and Twitter Card meta tags into HTML <head>.

    Replaces the existing <title> tag and inserts meta tags before </head>.
    All content values are HTML-escaped for safety. Descriptions longer than
    200 characters are truncated with an ellipsis.
    """
    # Truncate description if needed
    if len(description) > _MAX_DESCRIPTION_LENGTH:
        description = description[:_MAX_DESCRIPTION_LENGTH] + "..."

    # Escape all values
    esc_title = html.escape(title)
    esc_desc = html.escape(description)
    esc_url = html.escape(url)

    # Build required meta tags
    tags = [
        f'<meta property="og:title" content="{esc_title}">',
        f'<meta property="og:description" content="{esc_desc}">',
        f'<meta property="og:url" content="{esc_url}">',
        '<meta property="og:type" content="article">',
        '<meta name="twitter:card" content="summary">',
        f'<meta name="twitter:title" content="{esc_title}">',
        f'<meta name="twitter:description" content="{esc_desc}">',
    ]

    # Conditionally add optional tags
    if site_name:
        tags.append(f'<meta property="og:site_name" content="{html.escape(site_name)}">')
    if author is not None:
        tags.append(f'<meta property="article:author" content="{html.escape(author)}">')
    if published_time is not None:
        tags.append(
            f'<meta property="article:published_time" content="{html.escape(published_time)}">'
        )
    if modified_time is not None:
        tags.append(
            f'<meta property="article:modified_time" content="{html.escape(modified_time)}">'
        )

    meta_block = "\n".join(tags)

    # Replace <title>...</title> with the post title
    result = re.sub(r"<title>[^<]*</title>", f"<title>{esc_title}</title>", base_html)

    # Insert meta tags before </head>
    result = result.replace("</head>", f"{meta_block}\n</head>")

    return result
