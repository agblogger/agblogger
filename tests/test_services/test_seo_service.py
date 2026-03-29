"""Tests for the SEO service."""

from __future__ import annotations

from typing import Any

from backend.services.seo_service import (
    SeoContext,
    blogposting_ld,
    render_post_list_html,
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


class TestRenderSeoHtmlBody:
    def test_injects_rendered_body_inside_root(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(rendered_body="<h1>Hello</h1><p>World</p>"))
        assert "<h1>Hello</h1><p>World</p>" in result
        assert '<div id="root"><div style="' in result

    def test_body_has_inline_styles(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(rendered_body="<p>Hi</p>"))
        assert "max-width:42rem" in result
        assert "font-family:system-ui" in result

    def test_omits_body_when_none(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(rendered_body=None))
        assert '<div id="root"></div>' in result


class TestRenderSeoHtmlPreload:
    def test_injects_preload_script(self) -> None:
        data = {"posts": [{"title": "Hello"}], "total": 1}
        result = render_seo_html(BASE_HTML, _make_ctx(preload_data=data))
        assert '<script id="__initial_data__" type="application/json">' in result
        assert '"posts":[{"title":"Hello"}]' in result

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
        posts = [
            {"title": "First Post", "slug": "first", "date": "March 28, 2026", "excerpt": "Hello"},
            {
                "title": "Second Post",
                "slug": "second",
                "date": "March 27, 2026",
                "excerpt": "World",
            },
        ]
        result = render_post_list_html(posts, heading="My Blog")
        assert '<a href="/post/first"' in result
        assert "First Post" in result
        assert '<a href="/post/second"' in result
        assert "March 28, 2026" in result
        assert "Hello" in result

    def test_renders_heading(self) -> None:
        result = render_post_list_html([], heading="My Blog")
        assert "<h1" in result
        assert "My Blog" in result

    def test_empty_list(self) -> None:
        result = render_post_list_html([], heading="Blog")
        assert "<ul" in result
        assert "<li" not in result

    def test_escapes_html_in_title(self) -> None:
        posts = [{"title": "<script>XSS</script>", "slug": "x", "date": "D", "excerpt": "E"}]
        result = render_post_list_html(posts, heading="Blog")
        assert "<script>" not in result

    def test_escapes_html_in_excerpt(self) -> None:
        posts = [{"title": "T", "slug": "x", "date": "D", "excerpt": "<img onerror=alert(1)>"}]
        result = render_post_list_html(posts, heading="Blog")
        assert "onerror" not in result
