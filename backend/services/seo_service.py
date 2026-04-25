"""SEO enrichment service: meta tags, structured data, and pre-rendered content injection."""

from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

logger = logging.getLogger(__name__)

_MAX_DESCRIPTION_LENGTH = 200

_PRELOAD_MARKER_ATTR = "data-agblogger-preload"


def strip_html_tags(text: str) -> str:
    """Strip HTML tags, decode entities, and collapse whitespace."""
    # Replace tags with spaces (not empty string) to preserve word boundaries
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class SeoPostItem(TypedDict):
    """Post entry shape used for SEO pre-rendering."""

    id: str
    title: str
    slug: str
    date: str
    excerpt: str


@dataclass(frozen=True)
class SeoImage:
    """Open Graph image with optional alt text.

    ``url`` must be an absolute URL (http:// or https://) so social platforms
    can fetch the thumbnail without resolving against the page URL. Grouping
    ``url`` and ``alt`` makes the (image, image_alt) coupling structural rather
    than convention.
    """

    url: str
    alt: str | None = None

    def __post_init__(self) -> None:
        if not self.url.startswith(("http://", "https://")):
            msg = f"SeoImage.url must be an absolute http(s) URL, got: {self.url!r}"
            raise ValueError(msg)


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
    image: SeoImage | None = None
    json_ld: dict[str, Any] | None = None
    rendered_body: str | None = None
    markdown_body: str | None = None
    preload_data: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.json_ld is not None and (
            "@context" not in self.json_ld or "@type" not in self.json_ld
        ):
            raise ValueError("json_ld must contain @context and @type keys")


_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(
    r"""(?P<name>[a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)')"""
)


def extract_first_image(html_text: str) -> tuple[str, str | None] | None:
    """Return (src, alt) for the first <img> with a non-empty src, or None.

    Callers use the result to pick an og:image URL from rendered post HTML.
    The caller falls back to the configured site image when no inline image
    is found or when its src cannot be made into a safe absolute URL.
    """
    for match in _IMG_TAG_RE.finditer(html_text):
        attrs: dict[str, str] = {}
        for attr_match in _ATTR_RE.finditer(match.group(0)):
            name = attr_match.group("name").lower()
            value = attr_match.group("dq")
            if value is None:
                value = attr_match.group("sq") or ""
            attrs[name] = value
        src = attrs.get("src", "").strip()
        if not src:
            continue
        alt_raw = attrs.get("alt")
        alt = alt_raw.strip() if alt_raw is not None and alt_raw.strip() else None
        return src, alt
    return None


def render_seo_html(base_html: str, ctx: SeoContext) -> str:
    """Inject SEO meta tags, structured data, and pre-rendered content into base HTML."""
    description = ctx.description
    if len(description) > _MAX_DESCRIPTION_LENGTH:
        description = description[: _MAX_DESCRIPTION_LENGTH - 3] + "..."

    esc_title = html.escape(ctx.title)
    esc_desc = html.escape(description)
    esc_url = html.escape(ctx.canonical_url)

    twitter_card = "summary_large_image" if ctx.image is not None else "summary"

    head_tags = [
        f'<meta name="description" content="{esc_desc}">',
        f'<link rel="canonical" href="{esc_url}">',
        f'<meta property="og:title" content="{esc_title}">',
        f'<meta property="og:description" content="{esc_desc}">',
        f'<meta property="og:url" content="{esc_url}">',
        f'<meta property="og:type" content="{html.escape(ctx.og_type)}">',
        f'<meta name="twitter:card" content="{twitter_card}">',
        f'<meta name="twitter:title" content="{esc_title}">',
        f'<meta name="twitter:description" content="{esc_desc}">',
    ]

    if ctx.image is not None:
        esc_image = html.escape(ctx.image.url)
        head_tags.append(f'<meta property="og:image" content="{esc_image}">')
        head_tags.append(f'<meta name="twitter:image" content="{esc_image}">')
        if ctx.image.alt:
            esc_image_alt = html.escape(ctx.image.alt)
            head_tags.append(f'<meta property="og:image:alt" content="{esc_image_alt}">')
            head_tags.append(f'<meta name="twitter:image:alt" content="{esc_image_alt}">')

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
            f'<div id="root"><div class="server-shell">{ctx.rendered_body}</div></div>',
        )

    if ctx.preload_data is not None:
        preload_json = json.dumps(ctx.preload_data, ensure_ascii=False, separators=(",", ":"))
        esc_preload = preload_json.replace("</", "<\\/")
        preload_tag = (
            f'<script id="__initial_data__" {_PRELOAD_MARKER_ATTR} type="application/json">'
            f"{esc_preload}</script>"
        )
        result = result.replace("</body>", f"{preload_tag}\n</body>")

    if "</head>" not in base_html:
        logger.warning("SEO injection skipped: </head> marker not found in base HTML")
    if '<div id="root"></div>' not in base_html and ctx.rendered_body is not None:
        logger.warning('SEO injection skipped: <div id="root"></div> marker not found in base HTML')
    if "</body>" not in base_html and ctx.preload_data is not None:
        logger.warning("SEO injection skipped: </body> marker not found in base HTML")

    return result


def _yaml_scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_page_markdown(ctx: SeoContext) -> str:
    """Render agent-friendly markdown for a page response.

    When ctx.markdown_body is absent or empty, falls back to a title-and-description summary.
    """
    frontmatter = [
        "---",
        f"title: {_yaml_scalar(ctx.title)}",
        f"url: {_yaml_scalar(ctx.canonical_url)}",
        f"description: {_yaml_scalar(ctx.description)}",
    ]
    if ctx.site_name is not None:
        frontmatter.append(f"site_name: {_yaml_scalar(ctx.site_name)}")
    if ctx.author is not None:
        frontmatter.append(f"author: {_yaml_scalar(ctx.author)}")
    if ctx.published_time is not None:
        frontmatter.append(f"published_time: {_yaml_scalar(ctx.published_time)}")
    if ctx.modified_time is not None:
        frontmatter.append(f"modified_time: {_yaml_scalar(ctx.modified_time)}")
    frontmatter.append("---")

    if ctx.markdown_body is not None and ctx.markdown_body.strip():
        body = ctx.markdown_body.strip()
    else:
        body = f"# {ctx.title}\n\n{ctx.description}".strip()

    return "\n".join(frontmatter) + "\n\n" + body + "\n"


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
    """Render a simple HTML post list for server-side pre-rendering."""
    esc_heading = html.escape(heading)
    items = []
    for post in posts:
        esc_id = html.escape(str(post["id"]))
        esc_title = html.escape(strip_html_tags(post["title"]))
        esc_slug = html.escape(post["slug"])
        esc_date = html.escape(post["date"])
        esc_excerpt = html.escape(strip_html_tags(post["excerpt"]))
        items.append(
            f'<li class="server-list-item" data-id="{esc_id}">'
            f'<a class="server-link" href="/post/{esc_slug}">{esc_title}</a>'
            f'<p class="server-date">{esc_date}</p>'
            f'<div class="server-excerpt" data-excerpt><p>'
            f"{esc_excerpt}</p></div>"
            f"</li>"
        )
    list_html = "\n".join(items)
    return (
        f'<h1 class="server-list-heading">{esc_heading}</h1>'
        f'<ul class="server-list">{list_html}</ul>'
    )


def render_post_list_markdown(
    posts: list[SeoPostItem],
    *,
    heading: str,
) -> str:
    """Render a simple markdown post list for agent responses."""
    sections = [f"# {heading}"]
    for post in posts:
        title = strip_html_tags(post["title"])
        slug = post["slug"]
        date = post["date"]
        excerpt = strip_html_tags(post["excerpt"])
        sections.append(f"## [{title}](/post/{slug})")
        sections.append(f"Published: {date}")
        if excerpt:
            sections.append("")
            sections.append(excerpt)
    return "\n\n".join(sections) + "\n"
