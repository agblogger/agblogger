"""Tests for relative URL rewriting in rendered HTML."""

from __future__ import annotations

from backend.pandoc.renderer import rewrite_relative_urls


class TestRewriteRelativeUrls:
    """Tests for rewrite_relative_urls()."""

    def test_rewrite_img_src_relative(self) -> None:
        """Relative img src is rewritten to absolute /post/<slug>/ path."""
        html = '<img src="photo.png">'
        result = rewrite_relative_urls(html, "posts/2026-02-20-my-post/index.md")
        assert result == '<img src="/post/2026-02-20-my-post/photo.png">'

    def test_rewrite_img_src_dot_slash_prefix(self) -> None:
        """Relative img src with ./ prefix is rewritten correctly."""
        html = '<img src="./photo.png">'
        result = rewrite_relative_urls(html, "posts/2026-02-20-my-post/index.md")
        assert result == '<img src="/post/2026-02-20-my-post/photo.png">'

    def test_skip_absolute_url_https(self) -> None:
        """Absolute https:// URLs are left unchanged."""
        html = '<img src="https://example.com/photo.png">'
        result = rewrite_relative_urls(html, "posts/hello/index.md")
        assert result == '<img src="https://example.com/photo.png">'

    def test_skip_absolute_url_http(self) -> None:
        """Absolute http:// URLs are left unchanged."""
        html = '<a href="http://example.com">'
        result = rewrite_relative_urls(html, "posts/hello/index.md")
        assert result == '<a href="http://example.com">'

    def test_skip_data_uri(self) -> None:
        """data: URIs are left unchanged."""
        html = '<img src="data:image/png;base64,abc123">'
        result = rewrite_relative_urls(html, "posts/hello/index.md")
        assert result == '<img src="data:image/png;base64,abc123">'

    def test_skip_fragment(self) -> None:
        """Fragment-only links (#section) are left unchanged."""
        html = '<a href="#section">'
        result = rewrite_relative_urls(html, "posts/hello/index.md")
        assert result == '<a href="#section">'

    def test_skip_absolute_path(self) -> None:
        """Absolute paths starting with / are left unchanged."""
        html = '<a href="/about">'
        result = rewrite_relative_urls(html, "posts/hello/index.md")
        assert result == '<a href="/about">'

    def test_skip_mailto(self) -> None:
        """mailto: links are left unchanged."""
        html = '<a href="mailto:user@example.com">'
        result = rewrite_relative_urls(html, "posts/hello/index.md")
        assert result == '<a href="mailto:user@example.com">'

    def test_skip_tel(self) -> None:
        """tel: links are left unchanged."""
        html = '<a href="tel:+1234567890">'
        result = rewrite_relative_urls(html, "posts/hello/index.md")
        assert result == '<a href="tel:+1234567890">'

    def test_rewrite_href_relative(self) -> None:
        """Relative href in anchor is rewritten to absolute path."""
        html = '<a href="doc.pdf">'
        result = rewrite_relative_urls(html, "posts/2026-02-20-my-post/index.md")
        assert result == '<a href="/post/2026-02-20-my-post/doc.pdf">'

    def test_directory_backed_post_uses_clean_post_asset_url(self) -> None:
        """Directory-backed posts get clean /post asset URLs."""
        html = '<img src="photo.png">'
        result = rewrite_relative_urls(html, "posts/hello/index.md")
        assert result == '<img src="/post/hello/photo.png">'

    def test_multiple_attributes(self) -> None:
        """Multiple src/href attributes in the same HTML are all rewritten."""
        html = (
            '<img src="photo.png"> '
            '<a href="doc.pdf">link</a> '
            '<img src="https://cdn.example.com/img.jpg">'
        )
        result = rewrite_relative_urls(html, "posts/2026-02-20-my-post/index.md")
        assert result == (
            '<img src="/post/2026-02-20-my-post/photo.png"> '
            '<a href="/post/2026-02-20-my-post/doc.pdf">link</a> '
            '<img src="https://cdn.example.com/img.jpg">'
        )

    def test_subdirectory_relative_path(self) -> None:
        """Relative path referencing a subdirectory resolves correctly."""
        html = '<img src="images/photo.png">'
        result = rewrite_relative_urls(html, "posts/2026-02-20-my-post/index.md")
        assert result == '<img src="/post/2026-02-20-my-post/images/photo.png">'

    def test_parent_directory_relative_path(self) -> None:
        """Relative path with ../ resolves correctly via normpath."""
        html = '<img src="../shared/photo.png">'
        result = rewrite_relative_urls(html, "posts/2026-02-20-my-post/index.md")
        assert result == '<img src="/post/shared/photo.png">'

    def test_deep_traversal_left_unchanged(self) -> None:
        """Deep ../ traversal that escapes content root is left unchanged."""
        html = '<img src="../../../../etc/passwd">'
        result = rewrite_relative_urls(html, "posts/my-post/index.md")
        assert result == '<img src="../../../../etc/passwd">'

    def test_empty_html(self) -> None:
        """Empty HTML string returns empty."""
        result = rewrite_relative_urls("", "posts/hello/index.md")
        assert result == ""

    def test_rewrite_single_quoted_src(self) -> None:
        """Single-quoted img src is rewritten correctly."""
        html = "<img src='photo.png'>"
        result = rewrite_relative_urls(html, "posts/2026-02-20-my-post/index.md")
        assert result == "<img src='/post/2026-02-20-my-post/photo.png'>"

    def test_rewrite_single_quoted_href(self) -> None:
        """Single-quoted href is rewritten correctly."""
        html = "<a href='doc.pdf'>"
        result = rewrite_relative_urls(html, "posts/2026-02-20-my-post/index.md")
        assert result == "<a href='/post/2026-02-20-my-post/doc.pdf'>"

    def test_skip_single_quoted_absolute(self) -> None:
        """Single-quoted absolute URLs are left unchanged."""
        html = "<img src='https://example.com/img.png'>"
        result = rewrite_relative_urls(html, "posts/hello/index.md")
        assert result == "<img src='https://example.com/img.png'>"

    def test_self_referential_index_md_link(self) -> None:
        """Self-referential index.md link resolves to /post/<slug>."""
        html = '<a href="index.md">'
        result = rewrite_relative_urls(html, "posts/my-post/index.md")
        assert result == '<a href="/post/my-post">'

    def test_self_referential_dot_slash_index_md(self) -> None:
        """A link to ./index.md resolves to the clean post URL."""
        html = '<a href="./index.md">'
        result = rewrite_relative_urls(html, "posts/2026-02-20-my-post/index.md")
        assert result == '<a href="/post/2026-02-20-my-post">'

    def test_no_src_or_href(self) -> None:
        """HTML without src/href attributes is returned unchanged."""
        html = "<p>Hello world</p>"
        result = rewrite_relative_urls(html, "posts/hello/index.md")
        assert result == "<p>Hello world</p>"
