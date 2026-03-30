"""SEO enrichment service: meta tags, structured data, and pre-rendered content injection."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

_MAX_DESCRIPTION_LENGTH = 200

_PRE_RENDER_STYLE = (
    "max-width:42rem;margin:0 auto;padding:2rem 1rem;"
    "font-family:system-ui,sans-serif;line-height:1.7;color:#1a1a1a"
)
_PRELOAD_MARKER_ATTR = "data-agblogger-preload"


def strip_html_tags(text: str) -> str:
    """Strip HTML tags, decode entities, and collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class SeoPostItem(TypedDict):
    """Typed dict for a single post entry in render_post_list_html."""

    id: str
    title: str
    slug: str
    date: str
    excerpt: str


@dataclass(frozen=True)
class SeoContext:
    """All SEO metadata for a single page response."""

    title: str
    description: str
    canonical_url: str
    og_type: Literal["website", "article"] = "website"
    site_name: str | None = None
    author: str | None = None
    published_time: str | None = None
    modified_time: str | None = None
    json_ld: dict[str, Any] | None = None
    rendered_body: str | None = None
    preload_data: dict[str, Any] | None = None


def render_seo_html(base_html: str, ctx: SeoContext) -> str:
    """Inject SEO meta tags, structured data, and pre-rendered content into base HTML."""
    description = ctx.description
    if len(description) > _MAX_DESCRIPTION_LENGTH:
        description = description[: _MAX_DESCRIPTION_LENGTH - 3] + "..."

    esc_title = html.escape(ctx.title)
    esc_desc = html.escape(description)
    esc_url = html.escape(ctx.canonical_url)

    head_tags = [
        f'<meta name="description" content="{esc_desc}">',
        f'<link rel="canonical" href="{esc_url}">',
        f'<meta property="og:title" content="{esc_title}">',
        f'<meta property="og:description" content="{esc_desc}">',
        f'<meta property="og:url" content="{esc_url}">',
        f'<meta property="og:type" content="{html.escape(ctx.og_type)}">',
        '<meta name="twitter:card" content="summary">',
        f'<meta name="twitter:title" content="{esc_title}">',
        f'<meta name="twitter:description" content="{esc_desc}">',
    ]

    if ctx.site_name:
        head_tags.append(f'<meta property="og:site_name" content="{html.escape(ctx.site_name)}">')
    if ctx.author is not None:
        head_tags.append(f'<meta property="article:author" content="{html.escape(ctx.author)}">')
    if ctx.published_time is not None:
        head_tags.append(
            f'<meta property="article:published_time" content="{html.escape(ctx.published_time)}">'
        )
    if ctx.modified_time is not None:
        head_tags.append(
            f'<meta property="article:modified_time" content="{html.escape(ctx.modified_time)}">'
        )

    if ctx.json_ld is not None:
        ld_json = json.dumps(ctx.json_ld, ensure_ascii=False, separators=(",", ":"))
        ld_json = ld_json.replace("</", "<\\/")
        head_tags.append(f'<script type="application/ld+json">{ld_json}</script>')

    head_block = "\n".join(head_tags)

    # Use a lambda so the replacement string is never interpreted for backreferences.
    title_tag = f"<title>{esc_title}</title>"
    result = re.sub(r"<title>[^<]*</title>", lambda _: title_tag, base_html)
    result = result.replace("</head>", f"{head_block}\n</head>")

    if ctx.rendered_body is not None:
        result = result.replace(
            '<div id="root"></div>',
            f'<div id="root"><div style="{_PRE_RENDER_STYLE}">{ctx.rendered_body}</div></div>',
        )

    if ctx.preload_data is not None:
        preload_json = json.dumps(ctx.preload_data, ensure_ascii=False, separators=(",", ":"))
        esc_preload = preload_json.replace("</", "<\\/")
        preload_tag = (
            f'<script id="__initial_data__" {_PRELOAD_MARKER_ATTR} type="application/json">'
            f"{esc_preload}</script>"
        )
        result = result.replace("</body>", f"{preload_tag}\n</body>")

    return result


def blogposting_ld(
    *,
    headline: str,
    description: str,
    url: str,
    date_published: str,
    date_modified: str,
    author_name: str | None,
    publisher_name: str,
) -> dict[str, Any]:
    """Build a schema.org BlogPosting JSON-LD dict."""
    ld: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": headline,
        "description": description,
        "url": url,
        "datePublished": date_published,
        "dateModified": date_modified,
        "publisher": {"@type": "Organization", "name": publisher_name},
    }
    if author_name is not None:
        ld["author"] = {"@type": "Person", "name": author_name}
    return ld


def webpage_ld(*, name: str, description: str, url: str) -> dict[str, Any]:
    """Build a schema.org WebPage JSON-LD dict."""
    return {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": name,
        "description": description,
        "url": url,
    }


def website_ld(*, name: str, description: str, url: str) -> dict[str, Any]:
    """Build a schema.org WebSite JSON-LD dict."""
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": name,
        "description": description,
        "url": url,
    }


def render_post_list_html(
    posts: list[SeoPostItem],
    *,
    heading: str,
) -> str:
    """Render a simple HTML post list for server-side pre-rendering.

    Each post dict must have keys: id, title, slug, date, excerpt.
    """
    esc_heading = html.escape(heading)
    items = []
    for post in posts:
        esc_id = html.escape(str(post["id"]))
        esc_title = html.escape(strip_html_tags(post["title"]))
        esc_slug = html.escape(post["slug"])
        esc_date = html.escape(post["date"])
        esc_excerpt = html.escape(strip_html_tags(post["excerpt"]))
        items.append(
            f'<li data-id="{esc_id}" style="margin-bottom:1.5rem">'
            f'<a href="/post/{esc_slug}" style="font-size:1.25rem;color:#1a1a1a;'
            f'text-decoration:none">{esc_title}</a>'
            f'<p style="color:#666;font-size:0.875rem;margin:0.25rem 0">{esc_date}</p>'
            f'<div data-excerpt><p style="color:#444;font-size:0.95rem;margin:0">'
            f"{esc_excerpt}</p></div>"
            f"</li>"
        )
    list_html = "\n".join(items)
    return (
        f'<h1 style="font-size:2.25rem;line-height:1.2;margin-bottom:1.5rem">{esc_heading}</h1>'
        f'<ul style="list-style:none;padding:0">{list_html}</ul>'
    )
