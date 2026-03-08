"""Tests for Open Graph tag injection service."""

from __future__ import annotations

from backend.services.opengraph_service import inject_og_tags, strip_html_tags


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
<title>AgBlogger</title>
</head>
<body><div id="root"></div></body>
</html>"""


class TestInjectOgTags:
    def test_injects_og_title(self) -> None:
        result = inject_og_tags(
            BASE_HTML,
            title="My Post",
            description="A description",
            url="https://example.com/post/1",
        )
        assert '<meta property="og:title" content="My Post"' in result

    def test_injects_og_description(self) -> None:
        result = inject_og_tags(
            BASE_HTML,
            title="My Post",
            description="A description",
            url="https://example.com/post/1",
        )
        assert '<meta property="og:description" content="A description"' in result

    def test_injects_og_url(self) -> None:
        result = inject_og_tags(
            BASE_HTML,
            title="My Post",
            description="A description",
            url="https://example.com/post/1",
        )
        assert '<meta property="og:url" content="https://example.com/post/1"' in result

    def test_injects_og_type_article(self) -> None:
        result = inject_og_tags(
            BASE_HTML,
            title="My Post",
            description="A description",
            url="https://example.com/post/1",
        )
        assert '<meta property="og:type" content="article"' in result

    def test_injects_twitter_card(self) -> None:
        result = inject_og_tags(
            BASE_HTML,
            title="My Post",
            description="A description",
            url="https://example.com/post/1",
        )
        assert '<meta name="twitter:card" content="summary"' in result

    def test_injects_twitter_title(self) -> None:
        result = inject_og_tags(
            BASE_HTML,
            title="My Post",
            description="A description",
            url="https://example.com/post/1",
        )
        assert '<meta name="twitter:title" content="My Post"' in result

    def test_injects_twitter_description(self) -> None:
        result = inject_og_tags(
            BASE_HTML,
            title="My Post",
            description="A description",
            url="https://example.com/post/1",
        )
        assert '<meta name="twitter:description" content="A description"' in result

    def test_updates_title_tag(self) -> None:
        result = inject_og_tags(
            BASE_HTML,
            title="My Post",
            description="A description",
            url="https://example.com/post/1",
        )
        assert "<title>My Post</title>" in result
        assert "<title>AgBlogger</title>" not in result

    def test_escapes_html_in_title(self) -> None:
        result = inject_og_tags(
            BASE_HTML,
            title='<script>alert("xss")</script>',
            description="A description",
            url="https://example.com/post/1",
        )
        assert "<script>" not in result
        assert "&#x27;" in result or "&lt;script&gt;" in result

    def test_escapes_html_in_description(self) -> None:
        result = inject_og_tags(
            BASE_HTML,
            title="My Post",
            description='<img src=x onerror="alert(1)">',
            url="https://example.com/post/1",
        )
        assert 'onerror="alert(1)"' not in result

    def test_truncates_long_description(self) -> None:
        long_desc = "a" * 300
        result = inject_og_tags(
            BASE_HTML,
            title="My Post",
            description=long_desc,
            url="https://example.com/post/1",
        )
        # Should contain truncated description (200 chars + "...")
        assert "a" * 200 + "..." in result
        assert "a" * 201 not in result

    def test_does_not_truncate_short_description(self) -> None:
        desc = "a" * 200
        result = inject_og_tags(
            BASE_HTML,
            title="My Post",
            description=desc,
            url="https://example.com/post/1",
        )
        assert desc in result
        assert desc + "..." not in result

    def test_includes_site_name_when_provided(self) -> None:
        result = inject_og_tags(
            BASE_HTML,
            title="My Post",
            description="A description",
            url="https://example.com/post/1",
            site_name="My Blog",
        )
        assert '<meta property="og:site_name" content="My Blog"' in result

    def test_omits_site_name_when_empty(self) -> None:
        result = inject_og_tags(
            BASE_HTML,
            title="My Post",
            description="A description",
            url="https://example.com/post/1",
            site_name="",
        )
        assert "og:site_name" not in result

    def test_omits_site_name_when_none(self) -> None:
        result = inject_og_tags(
            BASE_HTML,
            title="My Post",
            description="A description",
            url="https://example.com/post/1",
            site_name=None,
        )
        assert "og:site_name" not in result

    def test_includes_author_when_provided(self) -> None:
        result = inject_og_tags(
            BASE_HTML,
            title="My Post",
            description="A description",
            url="https://example.com/post/1",
            author="John Doe",
        )
        assert '<meta property="article:author" content="John Doe"' in result

    def test_omits_author_when_none(self) -> None:
        result = inject_og_tags(
            BASE_HTML,
            title="My Post",
            description="A description",
            url="https://example.com/post/1",
            author=None,
        )
        assert "article:author" not in result

    def test_includes_published_time(self) -> None:
        result = inject_og_tags(
            BASE_HTML,
            title="My Post",
            description="A description",
            url="https://example.com/post/1",
            published_time="2026-01-15T10:30:00+00:00",
        )
        assert (
            '<meta property="article:published_time" content="2026-01-15T10:30:00+00:00"' in result
        )

    def test_omits_published_time_when_none(self) -> None:
        result = inject_og_tags(
            BASE_HTML,
            title="My Post",
            description="A description",
            url="https://example.com/post/1",
            published_time=None,
        )
        assert "article:published_time" not in result

    def test_includes_modified_time(self) -> None:
        result = inject_og_tags(
            BASE_HTML,
            title="My Post",
            description="A description",
            url="https://example.com/post/1",
            modified_time="2026-02-20T14:00:00+00:00",
        )
        assert (
            '<meta property="article:modified_time" content="2026-02-20T14:00:00+00:00"' in result
        )

    def test_omits_modified_time_when_none(self) -> None:
        result = inject_og_tags(
            BASE_HTML,
            title="My Post",
            description="A description",
            url="https://example.com/post/1",
            modified_time=None,
        )
        assert "article:modified_time" not in result

    def test_preserves_rest_of_html(self) -> None:
        result = inject_og_tags(
            BASE_HTML,
            title="My Post",
            description="A description",
            url="https://example.com/post/1",
        )
        assert '<meta charset="utf-8">' in result
        assert '<div id="root"></div>' in result
        assert "<!DOCTYPE html>" in result

    def test_all_tags_injected_together(self) -> None:
        result = inject_og_tags(
            BASE_HTML,
            title="Full Post",
            description="Full description",
            url="https://example.com/post/1",
            site_name="My Blog",
            author="Jane",
            published_time="2026-01-01T00:00:00+00:00",
            modified_time="2026-02-01T00:00:00+00:00",
        )
        assert "og:title" in result
        assert "og:description" in result
        assert "og:url" in result
        assert "og:type" in result
        assert "og:site_name" in result
        assert "twitter:card" in result
        assert "twitter:title" in result
        assert "twitter:description" in result
        assert "article:author" in result
        assert "article:published_time" in result
        assert "article:modified_time" in result

    def test_tags_inserted_before_head_close(self) -> None:
        result = inject_og_tags(
            BASE_HTML,
            title="My Post",
            description="A description",
            url="https://example.com/post/1",
        )
        head_close_pos = result.index("</head>")
        og_title_pos = result.index("og:title")
        assert og_title_pos < head_close_pos
