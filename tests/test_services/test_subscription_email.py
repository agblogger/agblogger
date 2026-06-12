from __future__ import annotations

import html as _html

from hypothesis import given
from hypothesis import strategies as st

from backend.services.subscription_email import (
    build_broadcast_email,
    build_confirmation_email,
)


def test_confirmation_email_contains_confirm_link() -> None:
    html, text = build_confirmation_email(
        confirm_url="https://blog.example/subscribe/confirm?token=T",
        controller_name="Jane Blog",
    )
    assert "https://blog.example/subscribe/confirm?token=T" in html
    assert "https://blog.example/subscribe/confirm?token=T" in text
    assert "Jane Blog" in html
    assert "ignore" in text.lower()  # "if you didn't request this, ignore"


def test_broadcast_email_has_post_link_unsubscribe_and_footer() -> None:
    html, text = build_broadcast_email(
        post_url="https://blog.example/post/hello",
        post_title="Hello",
        post_html="<p>Body</p>",
        controller_name="Jane Blog",
        postal_address="1 Main St, Town",
    )
    assert "https://blog.example/post/hello" in html
    assert "<p>Body</p>" in html
    assert "{{{RESEND_UNSUBSCRIBE_URL}}}" in html  # Resend-managed unsubscribe
    assert "Jane Blog" in html and "1 Main St, Town" in html
    assert "Hello" in text


def test_confirmation_email_escapes_controller_name() -> None:
    html, _text = build_confirmation_email(
        confirm_url="https://blog.example/subscribe/confirm?token=T",
        controller_name="<script>alert(1)</script>",
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_broadcast_email_does_not_escape_post_html() -> None:
    html, _text = build_broadcast_email(
        post_url="https://blog.example/post/hello",
        post_title="Hello",
        post_html="<p>Hello <strong>world</strong></p>",
        controller_name="Jane Blog",
        postal_address="1 Main St, Town",
    )
    assert "<p>Hello <strong>world</strong></p>" in html


def test_broadcast_email_converts_root_relative_post_urls_to_absolute() -> None:
    html, _text = build_broadcast_email(
        post_url="https://blog.example/post/hello",
        post_title="Hello",
        post_html='<p><img src="/post/hello/image.png"><a href="/page/about">About</a></p>',
        controller_name="Jane Blog",
        postal_address="1 Main St, Town",
    )
    assert 'src="https://blog.example/post/hello/image.png"' in html
    assert 'href="https://blog.example/page/about"' in html


def test_broadcast_email_converts_fragment_links_to_online_post() -> None:
    html, _text = build_broadcast_email(
        post_url="https://blog.example/post/hello",
        post_title="Hello",
        post_html=(
            '<p>Claim<a href="#fn1" id="fnref1">1</a></p>'
            '<aside id="fn1">Footnote <a href="#fnref1">back</a></aside>'
        ),
        controller_name="Jane Blog",
        postal_address="1 Main St, Town",
    )
    assert 'href="https://blog.example/post/hello#fn1"' in html
    assert 'href="https://blog.example/post/hello#fnref1"' in html
    assert 'id="fnref1"' in html
    assert 'id="fn1"' in html


def test_broadcast_email_escapes_title_in_html() -> None:
    html, _text = build_broadcast_email(
        post_url="https://blog.example/post/hello",
        post_title="A & B <x>",
        post_html="<p>Body</p>",
        controller_name="Jane Blog",
        postal_address="1 Main St, Town",
    )
    assert "&amp;" in html
    assert "&lt;x&gt;" in html
    assert "<x>" not in html


def test_broadcast_email_neutralizes_javascript_post_url() -> None:
    html, _text = build_broadcast_email(
        post_url="javascript:alert(1)",
        post_title="Hello",
        post_html="<p>Body</p>",
        controller_name="Jane Blog",
        postal_address="1 Main St, Town",
    )
    assert 'href="javascript:' not in html
    assert 'href="#"' in html


def test_confirmation_email_neutralizes_javascript_url() -> None:
    html, _text = build_confirmation_email(
        confirm_url="javascript:alert(1)",
        controller_name="Jane Blog",
    )
    assert 'href="javascript:' not in html
    assert 'href="#"' in html


def test_broadcast_email_escapes_footer_fields() -> None:
    html, _text = build_broadcast_email(
        post_url="https://blog.example/post/hello",
        post_title="Hello",
        post_html="<p>Body</p>",
        controller_name="Jane Blog",
        postal_address="<script>bad</script>",
    )
    assert "&lt;script&gt;" in html
    assert "<script>" not in html


@given(name=st.text())
def test_confirmation_html_always_escapes_controller_name(name: str) -> None:
    html, _ = build_confirmation_email(confirm_url="https://blog.example/c", controller_name=name)
    assert _html.escape(name) in html


def _broadcast(post_html: str, *, title: str = "Hello") -> str:
    html, _text = build_broadcast_email(
        post_url="https://blog.example/post/hello",
        post_title=title,
        post_html=post_html,
        controller_name="Jane Blog",
        postal_address="1 Main St, Town",
    )
    return html


def test_broadcast_email_renders_inline_math_as_image() -> None:
    html = _broadcast('<p>Euler: <span class="math inline">e^{i\\pi}+1=0</span>.</p>')
    assert "latex.codecogs.com" in html
    assert "<img" in html
    # The Pandoc math span must be gone, replaced by the image.
    assert 'class="math inline"' not in html
    # Raw TeX is preserved as alt text so a blocked image still reads.
    assert 'alt="e^{i\\pi}+1=0"' in html


def test_broadcast_email_renders_display_math_centered() -> None:
    html = _broadcast('<p><span class="math display">\\int_0^1 x^2\\,dx</span></p>')
    assert "<img" in html
    # Block image with auto side-margins is centered and valid inside a <p>.
    assert "display:block" in html
    assert "margin:18px auto" in html
    assert 'class="math display"' not in html
    # No block element injected inside Pandoc's paragraph wrapper.
    assert "<p><div" not in html


def test_broadcast_email_math_url_encodes_decoded_tex() -> None:
    # Pandoc HTML-escapes "<" inside the span; it must be decoded before
    # URL-encoding for the image service (so "<" -> "%3C", not "&lt;").
    html = _broadcast('<span class="math inline">a &lt; b</span>')
    assert "%3C" in html  # URL-encoded "<" appears in the image src


def test_broadcast_email_header_precedes_title_and_content() -> None:
    html = _broadcast("<p>Body</p>", title="My Post")
    header_pos = html.index("View this post online")
    title_pos = html.index("My Post")
    body_pos = html.index("<p>Body</p>")
    # Header (post link + unsubscribe) comes first, then the title, then content.
    assert header_pos < title_pos < body_pos
    assert "{{{RESEND_UNSUBSCRIBE_URL}}}" in html[:body_pos]
    assert "https://blog.example/post/hello" in html[:body_pos]


def test_broadcast_email_shows_title_as_heading() -> None:
    html = _broadcast("<p>Body</p>", title="My Post")
    assert "<h1" in html
    heading = html[html.index("<h1") : html.index("</h1>")]
    assert "My Post" in heading


def test_broadcast_email_does_not_turn_prose_into_math_image() -> None:
    html = _broadcast("<p>No math here, just text.</p>")
    assert "latex.codecogs.com" not in html
    assert "No math here, just text." in html


# ── Task 9: Property-based URL invariants ─────────────────────────────────────


_SLUG_ALPHABET = st.characters(whitelist_categories=("Lu", "Ll", "Nd"), min_codepoint=32)


@given(st.text(alphabet=_SLUG_ALPHABET, min_size=1, max_size=50))
def test_absolute_post_urls_root_relative_becomes_absolute(slug: str) -> None:
    """Root-relative /foo URL in post HTML → made absolute in broadcast email."""
    path = f"/{slug}"
    html, _text = build_broadcast_email(
        post_url="https://blog.example/post/test",
        post_title="Test",
        post_html=f'<p><a href="{path}">link</a></p>',
        controller_name="Blog",
        postal_address="1 St",
    )
    # The root-relative link must be made absolute
    assert f'href="{path}"' not in html or f'href="https://blog.example{path}"' in html


def test_absolute_post_urls_protocol_relative_untouched() -> None:
    """Protocol-relative //foo URL → untouched in broadcast email."""
    html, _text = build_broadcast_email(
        post_url="https://blog.example/post/test",
        post_title="Test",
        post_html='<p><a href="//cdn.example.com/file.js">link</a></p>',
        controller_name="Blog",
        postal_address="1 St",
    )
    # Protocol-relative URLs should pass through unchanged
    assert 'href="//cdn.example.com/file.js"' in html


def test_absolute_post_urls_already_absolute_untouched() -> None:
    """Already-absolute https:// URL → untouched in broadcast email."""
    html, _text = build_broadcast_email(
        post_url="https://blog.example/post/test",
        post_title="Test",
        post_html='<p><a href="https://external.example.com/page">link</a></p>',
        controller_name="Blog",
        postal_address="1 St",
    )
    assert 'href="https://external.example.com/page"' in html


@given(st.text(min_size=0, max_size=200))
def test_build_broadcast_email_no_math_spans_survive(content: str) -> None:
    """No <span class="math ..."> should appear in the broadcast email output."""
    # Wrap arbitrary text in a paragraph — this is the expected input shape
    post_html = f"<p>{_html.escape(content)}</p>"
    html, _text = build_broadcast_email(
        post_url="https://blog.example/post/test",
        post_title="Test",
        post_html=post_html,
        controller_name="Blog",
        postal_address="1 St",
    )
    assert 'class="math inline"' not in html
    assert 'class="math display"' not in html
