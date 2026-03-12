"""Tests for HTML sanitizer in pandoc renderer."""

from __future__ import annotations

from backend.config import Settings
from backend.pandoc.renderer import _sanitize_excerpt_html, _sanitize_html


class TestSanitizeAllowedTags:
    """Tests for tag allowlisting."""

    def test_allowed_tag_passes(self) -> None:
        result = _sanitize_html("<p>Hello</p>")
        assert result == "<p>Hello</p>"

    def test_script_tag_stripped(self) -> None:
        result = _sanitize_html("<script>alert('xss')</script>")
        assert "<script>" not in result
        assert "</script>" not in result

    def test_disallowed_tag_stripped(self) -> None:
        result = _sanitize_html("<iframe src='evil.com'></iframe>")
        assert "<iframe" not in result

    def test_void_tags_preserved(self) -> None:
        result = _sanitize_html("<br><hr><img src='photo.png'>")
        assert "<br>" in result
        assert "<hr>" in result
        assert "<img" in result


class TestTaskListCheckboxes:
    """Regression tests for task list checkbox rendering (Bug 3)."""

    def test_unchecked_checkbox_preserved(self) -> None:
        html = '<input type="checkbox" disabled>'
        result = _sanitize_html(html)
        assert '<input type="checkbox" disabled="disabled">' in result

    def test_checked_checkbox_preserved(self) -> None:
        html = '<input type="checkbox" checked disabled>'
        result = _sanitize_html(html)
        assert 'type="checkbox"' in result
        assert 'checked="checked"' in result
        assert 'disabled="disabled"' in result

    def test_input_is_void_tag(self) -> None:
        """Input tags should not generate closing tags."""
        html = '<input type="checkbox" disabled>'
        result = _sanitize_html(html)
        assert "</input>" not in result

    def test_dangerous_input_type_stripped(self) -> None:
        """Only type, checked, disabled are allowed on input."""
        html = '<input type="checkbox" onclick="alert(1)" name="evil">'
        result = _sanitize_html(html)
        assert "onclick" not in result
        assert "name" not in result


class TestTableAlignment:
    """Regression tests for table column alignment (Bug 7)."""

    def test_text_align_left_preserved(self) -> None:
        html = '<td style="text-align: left;">cell</td>'
        result = _sanitize_html(html)
        assert 'style="text-align: left;"' in result

    def test_text_align_center_preserved(self) -> None:
        html = '<th style="text-align: center;">header</th>'
        result = _sanitize_html(html)
        assert 'style="text-align: center;"' in result

    def test_text_align_right_preserved(self) -> None:
        html = '<td style="text-align: right;">cell</td>'
        result = _sanitize_html(html)
        assert 'style="text-align: right;"' in result

    def test_text_align_justify_preserved(self) -> None:
        html = '<td style="text-align: justify;">cell</td>'
        result = _sanitize_html(html)
        assert 'style="text-align: justify;"' in result

    def test_dangerous_style_stripped(self) -> None:
        html = '<td style="background: url(evil)">cell</td>'
        result = _sanitize_html(html)
        assert "style" not in result

    def test_style_on_non_table_stripped(self) -> None:
        """style is only allowed on td/th, not arbitrary tags."""
        html = '<p style="text-align: center;">text</p>'
        result = _sanitize_html(html)
        assert "style" not in result


class TestSafeUrls:
    """Tests for URL safety validation in href/src attributes."""

    def test_javascript_href_stripped(self) -> None:
        html = '<a href="javascript:alert(1)">click</a>'
        result = _sanitize_html(html)
        assert "javascript" not in result

    def test_data_src_stripped(self) -> None:
        html = '<img src="data:text/html,<script>alert(1)</script>">'
        result = _sanitize_html(html)
        assert "data:" not in result

    def test_https_href_preserved(self) -> None:
        html = '<a href="https://example.com">link</a>'
        result = _sanitize_html(html)
        assert 'href="https://example.com"' in result

    def test_mailto_href_preserved(self) -> None:
        html = '<a href="mailto:user@example.com">email</a>'
        result = _sanitize_html(html)
        assert 'href="mailto:user@example.com"' in result

    def test_vbscript_href_stripped(self) -> None:
        result = _sanitize_html("<a href=\"vbscript:MsgBox('xss')\">click</a>")
        assert "vbscript" not in result
        assert "<a>" in result

    def test_mixed_case_javascript_stripped(self) -> None:
        result = _sanitize_html('<a href="JaVaScRiPt:alert(1)">click</a>')
        assert "href" not in result
        assert "<a>" in result

    def test_entity_encoded_javascript_stripped(self) -> None:
        result = _sanitize_html('<a href="java&#115;cript:alert(1)">click</a>')
        assert "href" not in result
        assert "<a>" in result

    def test_tab_in_protocol_stripped(self) -> None:
        result = _sanitize_html('<a href="java\tscript:alert(1)">click</a>')
        assert "href" not in result
        assert "<a>" in result


class TestIdAttribute:
    """Tests for id attribute validation."""

    def test_safe_id_preserved(self) -> None:
        html = '<h2 id="my-heading">Title</h2>'
        result = _sanitize_html(html)
        assert 'id="my-heading"' in result

    def test_unsafe_id_stripped(self) -> None:
        html = '<h2 id="has spaces">Title</h2>'
        result = _sanitize_html(html)
        assert "id=" not in result


class TestDetailsTag:
    """Tests for details/summary tag support."""

    def test_details_tag_preserved(self) -> None:
        html = "<details><summary>Click me</summary><p>Hidden content</p></details>"
        result = _sanitize_html(html)
        assert "<details>" in result
        assert "<summary>" in result
        assert "</details>" in result
        assert "</summary>" in result
        assert "Hidden content" in result

    def test_details_open_attribute_preserved(self) -> None:
        html = "<details open><summary>Open</summary><p>Visible</p></details>"
        result = _sanitize_html(html)
        assert 'open="open"' in result

    def test_details_disallowed_attribute_stripped(self) -> None:
        html = '<details onclick="alert(1)"><summary>Click</summary></details>'
        result = _sanitize_html(html)
        assert "onclick" not in result
        assert "<details>" in result


class TestMarkTag:
    """Regression: <mark> tag must pass through sanitizer for ==highlight== syntax."""

    def test_mark_tag_preserved(self) -> None:
        result = _sanitize_html("<p>This is <mark>highlighted</mark> text.</p>")
        assert "<mark>" in result
        assert "</mark>" in result
        assert "highlighted" in result

    def test_mark_tag_no_attributes_allowed(self) -> None:
        """mark tag should only allow global attrs (class, id), not arbitrary ones."""
        result = _sanitize_html('<mark onclick="alert(1)">text</mark>')
        assert "onclick" not in result
        assert "<mark>" in result


class TestEntityHandling:
    """Tests for HTML entity handling."""

    def test_entity_ref_preserved(self) -> None:
        result = _sanitize_html("&amp;")
        assert result == "&amp;"

    def test_char_ref_preserved(self) -> None:
        result = _sanitize_html("&#60;")
        assert result == "&#60;"

    def test_data_escaped(self) -> None:
        result = _sanitize_html("<p><script></p>")
        # The <script> tag is stripped, not its text content
        assert "<script>" not in result


class TestExcerptSanitizer:
    """Tests for excerpt-specific sanitization policy."""

    def test_excerpt_strips_img_tag(self) -> None:
        html = '<p>Hello <strong>world</strong> <img src="https://evil.example/a.png" alt="x"></p>'
        result = _sanitize_excerpt_html(html)
        assert "<strong>world</strong>" in result
        assert "<img" not in result

    def test_excerpt_strips_input_tag(self) -> None:
        result = _sanitize_excerpt_html('<p><input type="checkbox" checked disabled></p>')
        assert "<input" not in result


class TestYouTubeIframe:
    """Tests for YouTube iframe embed support."""

    def test_youtube_embed_allowed(self) -> None:
        html = '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>'
        result = _sanitize_html(html)
        assert "<iframe" in result
        assert 'src="https://www.youtube.com/embed/dQw4w9WgXcQ"' in result
        assert "</iframe>" in result

    def test_youtube_nocookie_allowed(self) -> None:
        html = '<iframe src="https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"></iframe>'
        result = _sanitize_html(html)
        assert "<iframe" in result
        assert 'src="https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"' in result

    def test_youtube_shorts_allowed(self) -> None:
        html = '<iframe src="https://www.youtube.com/shorts/dQw4w9WgXcQ"></iframe>'
        result = _sanitize_html(html)
        assert "<iframe" in result
        assert 'src="https://www.youtube.com/shorts/dQw4w9WgXcQ"' in result

    def test_youtube_without_www_stripped(self) -> None:
        """Bare youtube.com (without www.) is stripped to match CSP frame-src."""
        html = '<iframe src="https://youtube.com/embed/dQw4w9WgXcQ"></iframe>'
        result = _sanitize_html(html)
        assert "<iframe" not in result

    def test_youtube_with_query_params_allowed(self) -> None:
        html = (
            '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ?start=30&autoplay=1"></iframe>'
        )
        result = _sanitize_html(html)
        assert "<iframe" in result
        assert "start=30" in result

    def test_non_youtube_iframe_stripped(self) -> None:
        html = '<iframe src="https://evil.com/page"></iframe>'
        result = _sanitize_html(html)
        assert "<iframe" not in result
        assert "</iframe>" not in result

    def test_iframe_without_src_stripped(self) -> None:
        html = "<iframe></iframe>"
        result = _sanitize_html(html)
        assert "<iframe" not in result

    def test_iframe_javascript_src_stripped(self) -> None:
        html = '<iframe src="javascript:alert(1)"></iframe>'
        result = _sanitize_html(html)
        assert "<iframe" not in result

    def test_iframe_data_src_stripped(self) -> None:
        html = '<iframe src="data:text/html,<script>alert(1)</script>"></iframe>'
        result = _sanitize_html(html)
        assert "<iframe" not in result

    def test_youtube_http_stripped(self) -> None:
        """Only HTTPS allowed, not HTTP."""
        html = '<iframe src="http://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>'
        result = _sanitize_html(html)
        assert "<iframe" not in result

    def test_sandbox_attribute_forced(self) -> None:
        html = '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>'
        result = _sanitize_html(html)
        assert 'sandbox="allow-scripts allow-same-origin allow-popups"' in result

    def test_allowfullscreen_forced(self) -> None:
        html = '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>'
        result = _sanitize_html(html)
        assert "allowfullscreen" in result

    def test_referrerpolicy_forced(self) -> None:
        html = '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>'
        result = _sanitize_html(html)
        assert 'referrerpolicy="no-referrer"' in result

    def test_loading_lazy_forced(self) -> None:
        html = '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>'
        result = _sanitize_html(html)
        assert 'loading="lazy"' in result

    def test_width_height_stripped(self) -> None:
        html = (
            '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"'
            ' width="560" height="315"></iframe>'
        )
        result = _sanitize_html(html)
        assert "<iframe" in result
        assert "width" not in result
        assert "height" not in result

    def test_onload_stripped(self) -> None:
        html = '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ" onload="alert(1)"></iframe>'
        result = _sanitize_html(html)
        assert "<iframe" in result
        assert "onload" not in result

    def test_youtube_path_traversal_stripped(self) -> None:
        html = '<iframe src="https://www.youtube.com/embed/../evil"></iframe>'
        result = _sanitize_html(html)
        assert "<iframe" not in result

    def test_youtube_extra_path_stripped(self) -> None:
        html = '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ/evil"></iframe>'
        result = _sanitize_html(html)
        assert "<iframe" not in result

    def test_youtube_subdomain_attack_stripped(self) -> None:
        html = '<iframe src="https://evil.youtube.com/embed/dQw4w9WgXcQ"></iframe>'
        result = _sanitize_html(html)
        assert "<iframe" not in result

    def test_existing_iframe_test_still_passes(self) -> None:
        """Non-YouTube iframes are still stripped (regression for existing test)."""
        result = _sanitize_html("<iframe src='evil.com'></iframe>")
        assert "<iframe" not in result

    def test_stripped_iframe_shows_notification(self) -> None:
        """Stripped iframes emit a user-visible notification instead of silent removal."""
        html = '<iframe src="https://evil.com/page"></iframe>'
        result = _sanitize_html(html)
        assert "Iframe not allowed" in result
        assert "<em>" in result

    def test_stripped_iframe_without_src_shows_notification(self) -> None:
        html = "<iframe></iframe>"
        result = _sanitize_html(html)
        assert "Iframe not allowed" in result

    def test_user_sandbox_cannot_override_forced(self) -> None:
        """User-supplied sandbox cannot widen permissions."""
        html = (
            '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"'
            ' sandbox="allow-top-navigation allow-forms"></iframe>'
        )
        result = _sanitize_html(html)
        assert "allow-top-navigation" not in result
        assert "allow-forms" not in result
        assert 'sandbox="allow-scripts allow-same-origin allow-popups"' in result

    def test_mixed_valid_and_invalid_iframes(self) -> None:
        """Valid YouTube iframe preserved, non-YouTube stripped with notification."""
        html = (
            '<iframe src="https://evil.com/page"></iframe>'
            '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>'
        )
        result = _sanitize_html(html)
        assert result.count("<iframe") == 1
        assert result.count("</iframe>") == 1
        assert "evil.com" not in result
        assert "youtube.com" in result
        assert "Iframe not allowed" in result

    def test_multiple_valid_iframes(self) -> None:
        html = (
            '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>'
            '<iframe src="https://www.youtube.com/embed/abcdefghijk"></iframe>'
        )
        result = _sanitize_html(html)
        assert result.count("<iframe") == 2
        assert result.count("</iframe>") == 2

    def test_self_closing_youtube_iframe_allowed(self) -> None:
        """XHTML-style self-closing iframe should be handled like a regular iframe."""
        html = '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ" />'
        result = _sanitize_html(html)
        assert "<iframe" in result
        assert 'src="https://www.youtube.com/embed/dQw4w9WgXcQ"' in result

    def test_self_closing_non_youtube_iframe_shows_notification(self) -> None:
        html = '<iframe src="https://evil.com/page" />'
        result = _sanitize_html(html)
        assert "<iframe" not in result
        assert "Iframe not allowed" in result

    def test_youtube_nocookie_shorts_stripped(self) -> None:
        """youtube-nocookie.com only supports /embed/, not /shorts/."""
        html = '<iframe src="https://www.youtube-nocookie.com/shorts/dQw4w9WgXcQ"></iframe>'
        result = _sanitize_html(html)
        assert "<iframe" not in result

    def test_youtube_url_with_fragment_stripped(self) -> None:
        """URL fragments are not matched by the regex."""
        html = '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ#t=30"></iframe>'
        result = _sanitize_html(html)
        assert "<iframe" not in result

    def test_youtube_short_video_id_stripped(self) -> None:
        """Video ID must be exactly 11 characters."""
        html = '<iframe src="https://www.youtube.com/embed/dQw4w9WgXc"></iframe>'
        result = _sanitize_html(html)
        assert "<iframe" not in result

    def test_youtube_long_video_id_stripped(self) -> None:
        """Video ID must be exactly 11 characters."""
        html = '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQx"></iframe>'
        result = _sanitize_html(html)
        assert "<iframe" not in result

    def test_youtube_nocookie_without_www_stripped(self) -> None:
        """Bare youtube-nocookie.com (without www.) is stripped to match CSP."""
        html = '<iframe src="https://youtube-nocookie.com/embed/dQw4w9WgXcQ"></iframe>'
        result = _sanitize_html(html)
        assert "<iframe" not in result


class TestContentSecurityPolicy:
    """Tests for CSP YouTube frame-src directive."""

    def test_csp_includes_frame_src_for_youtube(self) -> None:
        settings = Settings()
        assert "frame-src" in settings.content_security_policy
        assert "https://www.youtube.com" in settings.content_security_policy
        assert "https://www.youtube-nocookie.com" in settings.content_security_policy
