"""Tests for the SEO service."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from backend.services.seo_service import (
    SeoContext,
    SeoImage,
    SeoPostItem,
    blogposting_ld,
    extract_first_image,
    render_page_markdown,
    render_post_list_html,
    render_post_list_markdown,
    render_seo_html,
    strip_html_tags,
    webpage_ld,
    website_ld,
)


class TestStripHtmlTags:
    def test_strips_basic_tags(self) -> None:
        assert strip_html_tags("<p>Hello</p>") == "Hello"

    def test_strips_nested_tags(self) -> None:
        assert strip_html_tags("<div><p>Hello <b>World</b></p></div>") == "Hello World"

    def test_strips_self_closing_tags(self) -> None:
        assert strip_html_tags("Hello<br/>World") == "Hello World"

    def test_decodes_html_entities(self) -> None:
        assert strip_html_tags("&amp; &lt; &gt; &quot;") == '& < > "'

    def test_decodes_numeric_entities(self) -> None:
        assert strip_html_tags("&#169; &#x27;") == "\u00a9 '"

    def test_empty_string(self) -> None:
        assert strip_html_tags("") == ""

    def test_plain_text_unchanged(self) -> None:
        assert strip_html_tags("Hello World") == "Hello World"

    def test_collapses_whitespace(self) -> None:
        assert strip_html_tags("Hello   \n\t  World") == "Hello World"

    def test_collapses_whitespace_from_tags(self) -> None:
        assert strip_html_tags("<p>Hello</p>  <p>World</p>") == "Hello World"

    def test_strips_leading_trailing_whitespace(self) -> None:
        assert strip_html_tags("  <p>Hello</p>  ") == "Hello"

    def test_tags_with_attributes(self) -> None:
        assert strip_html_tags('<a href="http://example.com">link</a>') == "link"


BASE_HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Blog</title>
</head>
<body><div id="root"></div></body>
</html>"""


def _make_ctx(**overrides: Any) -> SeoContext:
    defaults: dict[str, Any] = {
        "title": "My Post",
        "description": "A description",
        "canonical_url": "https://example.com/post/my-post",
    }
    defaults.update(overrides)
    image = defaults.pop("image", None)
    image_alt = defaults.pop("image_alt", None)
    if image is not None and not isinstance(image, SeoImage):
        defaults["image"] = SeoImage(url=image, alt=image_alt)
    elif image is not None:
        defaults["image"] = image
    return SeoContext(**defaults)


class TestRenderSeoHtml:
    def test_replaces_title_tag(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(title="Hello"))
        assert "<title>Hello</title>" in result
        assert "<title>Blog</title>" not in result

    def test_injects_meta_description(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(description="My desc"))
        assert '<meta name="description" content="My desc">' in result

    def test_injects_canonical_link(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(canonical_url="https://example.com/post/x"))
        assert '<link rel="canonical" href="https://example.com/post/x">' in result

    def test_injects_og_title(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(title="My Post"))
        assert '<meta property="og:title" content="My Post">' in result

    def test_injects_og_description(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(description="Desc"))
        assert '<meta property="og:description" content="Desc">' in result

    def test_injects_og_url(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(canonical_url="https://example.com/post/x"))
        assert '<meta property="og:url" content="https://example.com/post/x">' in result

    def test_og_type_defaults_to_website(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx())
        assert '<meta property="og:type" content="website">' in result

    def test_og_type_article(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(og_type="article"))
        assert '<meta property="og:type" content="article">' in result

    def test_injects_twitter_card(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx())
        assert '<meta name="twitter:card" content="summary">' in result

    def test_injects_twitter_title(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(title="TT"))
        assert '<meta name="twitter:title" content="TT">' in result

    def test_injects_twitter_description(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(description="TD"))
        assert '<meta name="twitter:description" content="TD">' in result

    def test_includes_site_name_when_provided(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(site_name="My Blog"))
        assert '<meta property="og:site_name" content="My Blog">' in result

    def test_omits_site_name_when_none(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(site_name=None))
        assert "og:site_name" not in result

    def test_includes_author_when_provided(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(author="Jane"))
        assert '<meta property="article:author" content="Jane">' in result

    def test_omits_author_when_none(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(author=None))
        assert "article:author" not in result

    def test_includes_published_time(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(published_time="2026-01-15T10:30:00+00:00"))
        assert 'article:published_time" content="2026-01-15T10:30:00+00:00"' in result

    def test_includes_modified_time(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(modified_time="2026-02-20T14:00:00+00:00"))
        assert 'article:modified_time" content="2026-02-20T14:00:00+00:00"' in result

    def test_omits_published_time_when_none(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx())
        assert "article:published_time" not in result

    def test_escapes_html_in_title(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(title='<script>alert("xss")</script>'))
        assert "<script>" not in result

    def test_escapes_html_in_description(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(description='<img src=x onerror="alert(1)">'))
        assert 'onerror="alert(1)"' not in result

    def test_truncates_long_description(self) -> None:
        long_desc = "a" * 300
        result = render_seo_html(BASE_HTML, _make_ctx(description=long_desc))
        assert "a" * 197 + "..." in result
        assert "a" * 198 + "..." not in result

    def test_does_not_truncate_200_char_description(self) -> None:
        desc = "a" * 200
        result = render_seo_html(BASE_HTML, _make_ctx(description=desc))
        assert desc in result
        assert desc + "..." not in result

    def test_tags_inserted_before_head_close(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx())
        head_close_pos = result.index("</head>")
        og_title_pos = result.index("og:title")
        assert og_title_pos < head_close_pos

    def test_preserves_rest_of_html(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx())
        assert '<meta charset="utf-8">' in result
        assert "<!DOCTYPE html>" in result

    def test_title_with_backslash_sequences_not_interpreted_as_backreferences(self) -> None:
        """Regression: re.sub must not interpret \\1 etc. in the replacement."""
        result = render_seo_html(BASE_HTML, _make_ctx(title=r"Price is \1 off"))
        assert r"<title>Price is \1 off</title>" in result

    def test_title_with_null_backslash_no_silent_corruption(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(title=r"Sale \0 today"))
        assert r"<title>Sale \0 today</title>" in result

    def test_og_tags_appear_before_any_script_tag_in_head(self) -> None:
        # Several Open Graph parsers (Facebook's Sharing Debugger in particular)
        # stop scanning the <head> at the first <script> tag and report
        # "the document returned no data" when the og: tags follow it. The SPA
        # base HTML loads the bundle from a <script type="module"> early in
        # <head>, so SEO injection MUST place og: tags before that script.
        spa_head = (
            "<!DOCTYPE html>\n"
            "<html>\n"
            "<head>\n"
            '<meta charset="utf-8">\n'
            "<title>Blog</title>\n"
            '<script type="module" src="/bundle.js"></script>\n'
            '<link rel="stylesheet" href="/bundle.css">\n'
            "</head>\n"
            '<body><div id="root"></div></body>\n'
            "</html>"
        )
        result = render_seo_html(spa_head, _make_ctx())
        head_section = result[result.index("<head>") : result.index("</head>")]
        assert 'property="og:title"' in head_section
        og_idx = head_section.index('property="og:title"')
        script_idx = head_section.index("<script")
        assert og_idx < script_idx, (
            "og:title must appear before any <script> in <head> — "
            "OG parsers that stop at <script> would otherwise see no metadata"
        )


class TestRenderSeoHtmlImageDimensions:
    def test_emits_og_image_width_and_height_when_provided(self) -> None:
        ctx = _make_ctx(
            image=SeoImage(
                url="https://example.com/img.png",
                alt="alt",
                width=1200,
                height=630,
                mime_type="image/png",
            )
        )
        result = render_seo_html(BASE_HTML, ctx)
        assert '<meta property="og:image:width" content="1200">' in result
        assert '<meta property="og:image:height" content="630">' in result
        assert '<meta property="og:image:type" content="image/png">' in result

    def test_omits_dimension_tags_when_dimensions_missing(self) -> None:
        ctx = _make_ctx(image=SeoImage(url="https://example.com/img.png", alt="alt"))
        result = render_seo_html(BASE_HTML, ctx)
        assert "og:image:width" not in result
        assert "og:image:height" not in result
        assert "og:image:type" not in result

    def test_emits_mime_type_alone_when_no_dimensions(self) -> None:
        ctx = _make_ctx(
            image=SeoImage(url="https://example.com/img.png", alt="alt", mime_type="image/png")
        )
        result = render_seo_html(BASE_HTML, ctx)
        assert "og:image:width" not in result
        assert '<meta property="og:image:type" content="image/png">' in result


class TestRenderSeoHtmlFbAppId:
    def test_emits_fb_app_id_when_set(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(fb_app_id="1234567890"))
        assert '<meta property="fb:app_id" content="1234567890">' in result

    def test_omits_fb_app_id_when_none(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(fb_app_id=None))
        assert "fb:app_id" not in result

    def test_omits_fb_app_id_when_empty_string(self) -> None:
        # Defensive: callers map empty config string to None, but if an empty
        # string slips through, don't render an empty content attribute.
        result = render_seo_html(BASE_HTML, _make_ctx(fb_app_id=""))
        assert "fb:app_id" not in result


class TestSeoImageInvariants:
    def test_rejects_width_without_height(self) -> None:
        with pytest.raises(ValueError, match="both be set or both be None"):
            SeoImage(url="https://example.com/x.png", width=100)

    def test_rejects_height_without_width(self) -> None:
        with pytest.raises(ValueError, match="both be set or both be None"):
            SeoImage(url="https://example.com/x.png", height=100)


class TestRenderSeoHtmlJsonLd:
    def test_injects_json_ld_script(self) -> None:
        ld = {"@context": "https://schema.org", "@type": "WebSite", "name": "Test"}
        result = render_seo_html(BASE_HTML, _make_ctx(json_ld=ld))
        assert '<script type="application/ld+json">' in result
        assert '"@type":"WebSite"' in result

    def test_json_ld_before_head_close(self) -> None:
        ld = {"@context": "https://schema.org", "@type": "WebSite", "name": "Test"}
        result = render_seo_html(BASE_HTML, _make_ctx(json_ld=ld))
        head_close = result.index("</head>")
        ld_pos = result.index("application/ld+json")
        assert ld_pos < head_close

    def test_omits_json_ld_when_none(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(json_ld=None))
        assert "application/ld+json" not in result

    def test_json_ld_escapes_script_closing_tag(self) -> None:
        ld = {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": "</script><script>alert(1)",
        }
        result = render_seo_html(BASE_HTML, _make_ctx(json_ld=ld))
        assert "</script><script>" not in result
        assert "<\\/script>" in result


class TestRenderSeoHtmlBody:
    def test_injects_rendered_body_inside_root(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(rendered_body="<h1>Hello</h1><p>World</p>"))
        assert "<h1>Hello</h1><p>World</p>" in result
        assert '<div id="root"><div class="server-shell">' in result

    def test_body_uses_css_classes_instead_of_inline_styles(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(rendered_body="<p>Hi</p>"))
        assert 'class="server-shell"' in result
        assert 'style="' not in result

    def test_omits_body_when_none(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(rendered_body=None))
        assert '<div id="root"></div>' in result


class TestRenderSeoHtmlPreload:
    def test_injects_preload_script(self) -> None:
        data = {"posts": [{"title": "Hello"}], "total": 1}
        result = render_seo_html(BASE_HTML, _make_ctx(preload_data=data))
        assert (
            '<script id="__initial_data__" data-agblogger-preload type="application/json">'
            in result
        )
        assert '"posts":[{"title":"Hello"}]' in result

    def test_preload_script_uses_server_owned_marker(self) -> None:
        data = {"posts": [{"title": "Hello"}], "total": 1}
        result = render_seo_html(BASE_HTML, _make_ctx(preload_data=data))
        assert "data-agblogger-preload" in result

    def test_preload_before_body_close(self) -> None:
        data = {"key": "value"}
        result = render_seo_html(BASE_HTML, _make_ctx(preload_data=data))
        body_close = result.index("</body>")
        preload_pos = result.index("__initial_data__")
        assert preload_pos < body_close

    def test_omits_preload_when_none(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(preload_data=None))
        assert "__initial_data__" not in result

    def test_preload_escapes_script_closing_tag(self) -> None:
        data = {"html": "</script><script>alert(1)"}
        result = render_seo_html(BASE_HTML, _make_ctx(preload_data=data))
        assert "</script><script>" not in result
        assert "<\\/script>" in result


class TestJsonLdHelpers:
    def test_blogposting_ld_basic(self) -> None:
        result = blogposting_ld(
            headline="My Post",
            description="A description",
            url="https://example.com/post/x",
            date_published="2026-03-28T12:00:00+00:00",
            date_modified="2026-03-28T14:00:00+00:00",
            author_name="Jane",
            publisher_name="My Blog",
        )
        assert result["@context"] == "https://schema.org"
        assert result["@type"] == "BlogPosting"
        assert result["headline"] == "My Post"
        assert result["author"] == {"@type": "Person", "name": "Jane"}
        assert result["publisher"] == {"@type": "Organization", "name": "My Blog"}

    def test_blogposting_ld_no_author(self) -> None:
        result = blogposting_ld(
            headline="Post",
            description="Desc",
            url="https://example.com/post/x",
            date_published="2026-03-28T12:00:00+00:00",
            date_modified="2026-03-28T14:00:00+00:00",
            author_name=None,
            publisher_name="Blog",
        )
        assert "author" not in result

    def test_webpage_ld(self) -> None:
        result = webpage_ld(
            name="About", description="About page", url="https://example.com/page/about"
        )
        assert result["@context"] == "https://schema.org"
        assert result["@type"] == "WebPage"
        assert result["name"] == "About"

    def test_website_ld(self) -> None:
        result = website_ld(name="My Blog", description="A blog", url="https://example.com/")
        assert result["@context"] == "https://schema.org"
        assert result["@type"] == "WebSite"
        assert result["name"] == "My Blog"


class TestRenderPostListHtml:
    def test_renders_post_links(self) -> None:
        posts: list[SeoPostItem] = [
            {
                "id": "1",
                "title": "First Post",
                "slug": "first",
                "date": "March 28, 2026",
                "excerpt": "Hello",
            },
            {
                "id": "2",
                "title": "Second Post",
                "slug": "second",
                "date": "March 27, 2026",
                "excerpt": "World",
            },
        ]
        result = render_post_list_html(posts, heading="My Blog")
        assert 'href="/post/first"' in result
        assert "First Post" in result
        assert 'href="/post/second"' in result
        assert "March 28, 2026" in result

    def test_renders_heading(self) -> None:
        result = render_post_list_html([], heading="My Blog")
        assert "<h1" in result
        assert "My Blog" in result

    def test_empty_list(self) -> None:
        result = render_post_list_html([], heading="Blog")
        assert "<ul" in result
        assert "<li" not in result

    def test_escapes_html_in_title(self) -> None:
        posts: list[SeoPostItem] = [
            {"id": "1", "title": "<script>XSS</script>", "slug": "x", "date": "D", "excerpt": "E"}
        ]
        result = render_post_list_html(posts, heading="Blog")
        assert "<script>" not in result

    def test_escapes_html_in_excerpt(self) -> None:
        posts: list[SeoPostItem] = [
            {
                "id": "1",
                "title": "T",
                "slug": "x",
                "date": "D",
                "excerpt": "<img onerror=alert(1)>",
            }
        ]
        result = render_post_list_html(posts, heading="Blog")
        assert "onerror" not in result

    def test_includes_data_id_attribute(self) -> None:
        posts: list[SeoPostItem] = [
            {"id": "42", "title": "T", "slug": "s", "date": "D", "excerpt": "E"}
        ]
        result = render_post_list_html(posts, heading="Blog")
        assert 'data-id="42"' in result

    def test_includes_data_excerpt_marker(self) -> None:
        posts: list[SeoPostItem] = [
            {"id": "1", "title": "T", "slug": "s", "date": "D", "excerpt": "My excerpt text"}
        ]
        result = render_post_list_html(posts, heading="Blog")
        assert "data-excerpt" in result
        assert "My excerpt text" in result

    def test_uses_css_classes_instead_of_inline_styles(self) -> None:
        posts: list[SeoPostItem] = [
            {"id": "1", "title": "T", "slug": "s", "date": "D", "excerpt": "My excerpt text"}
        ]
        result = render_post_list_html(posts, heading="Blog")
        assert 'class="server-list-heading"' in result
        assert 'class="server-list"' in result
        assert 'class="server-list-item"' in result
        assert 'class="server-link"' in result
        assert 'class="server-date"' in result
        assert 'class="server-excerpt"' in result
        assert 'style="' not in result

    def test_accepts_seo_post_item_typed_dicts(self) -> None:
        """render_post_list_html must work with properly typed SeoPostItem dicts."""
        posts: list[SeoPostItem] = [
            {
                "id": "10",
                "title": "Typed Post",
                "slug": "typed-post",
                "date": "2026-01-01",
                "excerpt": "Typed excerpt",
            },
        ]
        result = render_post_list_html(posts, heading="Typed Blog")
        assert "Typed Post" in result
        assert 'href="/post/typed-post"' in result


class TestSeoContextImmutability:
    """SeoContext must be frozen so callers cannot accidentally mutate shared instances."""

    def test_frozen_raises_on_assignment(self) -> None:
        """Assigning to a field of a frozen SeoContext must raise FrozenInstanceError."""
        from dataclasses import FrozenInstanceError

        ctx = SeoContext(
            title="My Post",
            description="A description",
            canonical_url="https://example.com/post/my-post",
        )
        with pytest.raises(FrozenInstanceError):
            ctx.title = "mutated"  # type: ignore[misc]

    def test_frozen_og_type_cannot_be_changed(self) -> None:
        """og_type field of a frozen SeoContext must raise FrozenInstanceError on assignment."""
        from dataclasses import FrozenInstanceError

        ctx = SeoContext(
            title="Post",
            description="Desc",
            canonical_url="https://example.com/post/x",
            og_type="article",
        )
        with pytest.raises(FrozenInstanceError):
            ctx.og_type = "website"  # type: ignore[misc]


class TestSeoContextJsonLdValidation:
    """SeoContext must reject json_ld dicts that lack @context or @type."""

    def test_accepts_valid_json_ld_with_context_and_type(self) -> None:
        ctx = SeoContext(
            title="Post",
            description="Desc",
            canonical_url="https://example.com/post/x",
            json_ld={"@context": "https://schema.org", "@type": "WebPage"},
        )
        assert ctx.json_ld is not None
        assert ctx.json_ld["@type"] == "WebPage"

    def test_accepts_none_json_ld(self) -> None:
        ctx = SeoContext(
            title="Post",
            description="Desc",
            canonical_url="https://example.com/post/x",
            json_ld=None,
        )
        assert ctx.json_ld is None

    def test_rejects_json_ld_missing_context(self) -> None:
        with pytest.raises(ValueError, match="@context"):
            SeoContext(
                title="Post",
                description="Desc",
                canonical_url="https://example.com/post/x",
                json_ld={"@type": "WebPage", "name": "Test"},
            )

    def test_rejects_json_ld_missing_type(self) -> None:
        with pytest.raises(ValueError, match="@type"):
            SeoContext(
                title="Post",
                description="Desc",
                canonical_url="https://example.com/post/x",
                json_ld={"@context": "https://schema.org", "name": "Test"},
            )

    def test_rejects_json_ld_missing_both(self) -> None:
        with pytest.raises(ValueError, match=r"@context|@type"):
            SeoContext(
                title="Post",
                description="Desc",
                canonical_url="https://example.com/post/x",
                json_ld={"name": "Test", "url": "https://example.com"},
            )


class TestRenderPageMarkdown:
    def test_renders_yaml_frontmatter(self) -> None:
        ctx = _make_ctx(title="My Post", canonical_url="https://example.com/post/x")
        result = render_page_markdown(ctx)
        assert result.startswith("---\n")
        assert 'title: "My Post"' in result
        assert 'url: "https://example.com/post/x"' in result

    def test_includes_description_in_frontmatter(self) -> None:
        ctx = _make_ctx(description="A description")
        result = render_page_markdown(ctx)
        assert 'description: "A description"' in result

    def test_optional_fields_included_when_set(self) -> None:
        ctx = _make_ctx(
            site_name="My Blog",
            author="Jane",
            published_time="2026-01-01T00:00:00+00:00",
            modified_time="2026-01-02T00:00:00+00:00",
        )
        result = render_page_markdown(ctx)
        assert 'site_name: "My Blog"' in result
        assert 'author: "Jane"' in result
        assert 'published_time: "2026-01-01T00:00:00+00:00"' in result
        assert 'modified_time: "2026-01-02T00:00:00+00:00"' in result

    def test_optional_fields_omitted_when_none(self) -> None:
        ctx = _make_ctx()
        result = render_page_markdown(ctx)
        assert "site_name" not in result
        assert "author" not in result
        assert "published_time" not in result
        assert "modified_time" not in result

    def test_uses_markdown_body_when_provided(self) -> None:
        ctx = _make_ctx(markdown_body="# Hello\n\nBody content.")
        result = render_page_markdown(ctx)
        assert "# Hello\n\nBody content." in result

    def test_falls_back_to_title_and_description_when_body_is_none(self) -> None:
        ctx = _make_ctx(title="My Post", description="A description", markdown_body=None)
        result = render_page_markdown(ctx)
        assert "# My Post" in result
        assert "A description" in result

    def test_falls_back_when_body_is_empty_string(self) -> None:
        ctx = _make_ctx(title="My Post", description="Desc", markdown_body="")
        result = render_page_markdown(ctx)
        assert "# My Post" in result

    def test_falls_back_when_body_is_whitespace_only(self) -> None:
        ctx = _make_ctx(title="My Post", description="Desc", markdown_body="   \n  ")
        result = render_page_markdown(ctx)
        assert "# My Post" in result

    def test_yaml_scalar_quotes_special_chars(self) -> None:
        ctx = _make_ctx(title='Post with "quotes"')
        result = render_page_markdown(ctx)
        assert '"Post with \\"quotes\\""' in result

    def test_yaml_scalar_handles_non_ascii(self) -> None:
        ctx = _make_ctx(title="Ünïcödé title")
        result = render_page_markdown(ctx)
        assert "Ünïcödé title" in result

    def test_output_ends_with_newline(self) -> None:
        ctx = _make_ctx()
        result = render_page_markdown(ctx)
        assert result.endswith("\n")

    def test_frontmatter_closed_before_body(self) -> None:
        ctx = _make_ctx(markdown_body="Body here.")
        result = render_page_markdown(ctx)
        front_end = result.index("---\n\n")
        assert front_end > 0


class TestRenderPostListMarkdown:
    def _make_posts(self) -> list[SeoPostItem]:
        return [
            {
                "id": "1",
                "title": "First Post",
                "slug": "first",
                "date": "March 28, 2026",
                "excerpt": "Hello",
            },
            {
                "id": "2",
                "title": "Second Post",
                "slug": "second",
                "date": "March 27, 2026",
                "excerpt": "World",
            },
        ]

    def test_renders_heading(self) -> None:
        result = render_post_list_markdown([], heading="My Blog")
        assert "# My Blog" in result

    def test_renders_post_links(self) -> None:
        result = render_post_list_markdown(self._make_posts(), heading="Blog")
        assert "[First Post](/post/first)" in result
        assert "[Second Post](/post/second)" in result

    def test_includes_dates(self) -> None:
        result = render_post_list_markdown(self._make_posts(), heading="Blog")
        assert "March 28, 2026" in result

    def test_includes_excerpts(self) -> None:
        result = render_post_list_markdown(self._make_posts(), heading="Blog")
        assert "Hello" in result
        assert "World" in result

    def test_empty_list_renders_heading_only(self) -> None:
        result = render_post_list_markdown([], heading="Blog")
        assert "# Blog" in result
        assert "##" not in result

    def test_strips_html_tags_from_title(self) -> None:
        posts: list[SeoPostItem] = [
            {"id": "1", "title": "<b>Bold Title</b>", "slug": "x", "date": "D", "excerpt": "E"}
        ]
        result = render_post_list_markdown(posts, heading="Blog")
        assert "<b>" not in result
        assert "Bold Title" in result

    def test_strips_html_tags_from_excerpt(self) -> None:
        posts: list[SeoPostItem] = [
            {"id": "1", "title": "T", "slug": "x", "date": "D", "excerpt": "<p>Clean</p>"}
        ]
        result = render_post_list_markdown(posts, heading="Blog")
        assert "<p>" not in result
        assert "Clean" in result

    def test_omits_excerpt_section_when_empty(self) -> None:
        posts: list[SeoPostItem] = [
            {"id": "1", "title": "T", "slug": "x", "date": "D", "excerpt": ""}
        ]
        result = render_post_list_markdown(posts, heading="Blog")
        assert result.count("\n\n\n") == 0

    def test_output_ends_with_newline(self) -> None:
        result = render_post_list_markdown(self._make_posts(), heading="Blog")
        assert result.endswith("\n")


class TestRenderSeoHtmlMissingMarkers:
    """render_seo_html should log warnings when expected HTML markers are absent."""

    def test_warns_when_head_close_missing(self, caplog: pytest.LogCaptureFixture) -> None:
        html_no_head = '<!DOCTYPE html><html><body><div id="root"></div></body></html>'
        with caplog.at_level(logging.WARNING, logger="backend.services.seo_service"):
            render_seo_html(html_no_head, _make_ctx())
        assert any("</head>" in r.message for r in caplog.records)

    def test_warns_when_root_div_missing_and_rendered_body_set(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        html_no_root = "<!DOCTYPE html><html><head></head><body></body></html>"
        with caplog.at_level(logging.WARNING, logger="backend.services.seo_service"):
            render_seo_html(html_no_root, _make_ctx(rendered_body="<p>content</p>"))
        assert any("root" in r.message for r in caplog.records)

    def test_no_root_warning_when_rendered_body_is_none(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        html_no_root = "<!DOCTYPE html><html><head></head><body></body></html>"
        with caplog.at_level(logging.WARNING, logger="backend.services.seo_service"):
            render_seo_html(html_no_root, _make_ctx(rendered_body=None))
        assert not any("root" in r.message for r in caplog.records)

    def test_warns_when_body_close_missing_and_preload_set(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        html_no_body_close = '<!DOCTYPE html><html><head></head><body><div id="root"></div></body'
        with caplog.at_level(logging.WARNING, logger="backend.services.seo_service"):
            render_seo_html(html_no_body_close, _make_ctx(preload_data={"key": "val"}))
        assert any("</body>" in r.message for r in caplog.records)

    def test_no_body_close_warning_when_preload_is_none(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        html_no_body_close = '<!DOCTYPE html><html><head></head><body><div id="root"></div>'
        with caplog.at_level(logging.WARNING, logger="backend.services.seo_service"):
            render_seo_html(html_no_body_close, _make_ctx(preload_data=None))
        assert not any("</body>" in r.message for r in caplog.records)


class TestExtractFirstImage:
    """extract_first_image returns the (src, alt) of the first <img> tag, or None."""

    def test_returns_none_when_no_images(self) -> None:
        assert extract_first_image("<p>Just text</p>") is None

    def test_returns_none_for_empty_string(self) -> None:
        assert extract_first_image("") is None

    def test_extracts_src_with_double_quotes(self) -> None:
        result = extract_first_image('<img src="/foo.png" alt="Foo">')
        assert result is not None
        src, alt = result
        assert src == "/foo.png"
        assert alt == "Foo"

    def test_extracts_src_with_single_quotes(self) -> None:
        result = extract_first_image("<img src='/foo.png' alt='Foo'>")
        assert result is not None
        src, alt = result
        assert src == "/foo.png"
        assert alt == "Foo"

    def test_returns_alt_none_when_no_alt(self) -> None:
        result = extract_first_image('<img src="/foo.png">')
        assert result is not None
        src, alt = result
        assert src == "/foo.png"
        assert alt is None

    def test_picks_first_image_when_multiple(self) -> None:
        html = '<img src="/a.png" alt="A"> text <img src="/b.png" alt="B">'
        result = extract_first_image(html)
        assert result is not None
        src, alt = result
        assert src == "/a.png"
        assert alt == "A"

    def test_handles_self_closing_img(self) -> None:
        result = extract_first_image('<img src="/foo.png" alt="Foo" />')
        assert result is not None
        src, alt = result
        assert src == "/foo.png"
        assert alt == "Foo"

    def test_handles_attribute_order_alt_first(self) -> None:
        result = extract_first_image('<img alt="Foo" src="/foo.png">')
        assert result is not None
        src, alt = result
        assert src == "/foo.png"
        assert alt == "Foo"

    def test_returns_none_for_empty_src(self) -> None:
        assert extract_first_image('<img src="" alt="x">') is None

    def test_skips_image_with_no_src_attribute(self) -> None:
        html = '<img alt="No src"><img src="/real.png" alt="Real">'
        result = extract_first_image(html)
        assert result is not None
        src, alt = result
        assert src == "/real.png"
        assert alt == "Real"


class TestSeoImage:
    """SeoImage enforces the absolute-URL invariant at construction."""

    def test_accepts_https_url(self) -> None:
        img = SeoImage(url="https://example.com/a.png", alt="Alt")
        assert img.url == "https://example.com/a.png"
        assert img.alt == "Alt"

    def test_accepts_http_url(self) -> None:
        assert SeoImage(url="http://example.com/a.png").alt is None

    @pytest.mark.parametrize(
        "url",
        ["", "/relative.png", "//cdn/x.png", "data:image/png;base64,abc", "javascript:0"],
    )
    def test_rejects_non_absolute_url(self, url: str) -> None:
        with pytest.raises(ValueError, match="absolute http"):
            SeoImage(url=url)


class TestRenderSeoHtmlOgImage:
    """render_seo_html emits og:image and twitter:image when og_image is set."""

    def test_emits_og_image_when_set(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(image="https://ex.com/a.png"))
        assert '<meta property="og:image" content="https://ex.com/a.png">' in result

    def test_emits_twitter_image_when_set(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(image="https://ex.com/a.png"))
        assert '<meta name="twitter:image" content="https://ex.com/a.png">' in result

    def test_upgrades_twitter_card_to_large_image_when_og_image_set(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(image="https://ex.com/a.png"))
        assert '<meta name="twitter:card" content="summary_large_image">' in result
        assert '<meta name="twitter:card" content="summary">' not in result

    def test_keeps_summary_card_when_no_og_image(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(image=None))
        assert '<meta name="twitter:card" content="summary">' in result

    def test_omits_og_image_when_none(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(image=None))
        assert "og:image" not in result
        assert "twitter:image" not in result

    def test_emits_og_image_alt_when_set(self) -> None:
        result = render_seo_html(
            BASE_HTML, _make_ctx(image="https://ex.com/a.png", image_alt="A diagram")
        )
        assert '<meta property="og:image:alt" content="A diagram">' in result
        assert '<meta name="twitter:image:alt" content="A diagram">' in result

    def test_omits_og_image_alt_when_none(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(image="https://ex.com/a.png", image_alt=None))
        assert "og:image:alt" not in result
        assert "twitter:image:alt" not in result

    def test_escapes_og_image_url(self) -> None:
        result = render_seo_html(
            BASE_HTML, _make_ctx(image='https://ex.com/a.png?q="><script>x</script>')
        )
        assert "<script>" not in result

    def test_escapes_og_image_alt(self) -> None:
        result = render_seo_html(
            BASE_HTML,
            _make_ctx(image="https://ex.com/a.png", image_alt='"><script>x</script>'),
        )
        assert "<script>" not in result
