from __future__ import annotations

import asyncio
import html as _html

from hypothesis import given
from hypothesis import strategies as st

from backend.services.subscription_email import (
    MathMeasurer,
    build_broadcast_email,
    build_confirmation_email,
)


async def _fixed_measure(_url: str) -> tuple[int, int] | None:
    """Pretend every formula's high-DPI source is 90x27px, displayed 30x9 (a third)."""
    return (90, 27)


async def _no_measure(_url: str) -> tuple[int, int] | None:
    """Simulate a measurement failure so the unsized fallback path is exercised."""
    return None


def _build(
    *,
    post_url: str,
    post_title: str,
    post_html: str,
    controller_name: str,
    postal_address: str,
    measure_math: MathMeasurer | None = None,
) -> tuple[str, str]:
    """Drive the async broadcast builder from sync tests."""
    return asyncio.run(
        build_broadcast_email(
            post_url=post_url,
            post_title=post_title,
            post_html=post_html,
            controller_name=controller_name,
            postal_address=postal_address,
            measure_math=measure_math,
        )
    )


def _broadcast(
    post_html: str, *, title: str = "Hello", measure: MathMeasurer = _fixed_measure
) -> str:
    html, _text = _build(
        post_url="https://blog.example/post/hello",
        post_title=title,
        post_html=post_html,
        controller_name="Jane Blog",
        postal_address="1 Main St, Town",
        measure_math=measure,
    )
    return html


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
    html, text = _build(
        post_url="https://blog.example/post/hello",
        post_title="Hello",
        post_html="<p>Body</p>",
        controller_name="Jane Blog",
        postal_address="1 Main St, Town",
    )
    assert "https://blog.example/post/hello" in html
    assert "Body" in html
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
    html, _text = _build(
        post_url="https://blog.example/post/hello",
        post_title="Hello",
        post_html="<p>Hello <strong>world</strong></p>",
        controller_name="Jane Blog",
        postal_address="1 Main St, Town",
    )
    # Post HTML tags are inlined/styled, not escaped.
    assert "<strong>world</strong>" in html


def test_broadcast_email_converts_root_relative_post_urls_to_absolute() -> None:
    html, _text = _build(
        post_url="https://blog.example/post/hello",
        post_title="Hello",
        post_html='<p><img src="/post/hello/image.png"><a href="/page/about">About</a></p>',
        controller_name="Jane Blog",
        postal_address="1 Main St, Town",
    )
    assert 'src="https://blog.example/post/hello/image.png"' in html
    assert 'href="https://blog.example/page/about"' in html


def test_broadcast_email_converts_fragment_links_to_online_post() -> None:
    html, _text = _build(
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
    html, _text = _build(
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
    html, _text = _build(
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
    html, _text = _build(
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


def test_broadcast_email_renders_math_at_high_resolution() -> None:
    # Math images are requested at a high DPI so they stay sharp on the
    # high-density screens where most email is read. The DPI directive is
    # URL-encoded into the image src: "\dpi{360} " -> "%5Cdpi%7B360%7D".
    inline = _broadcast('<span class="math inline">e^{i\\pi}+1=0</span>')
    display = _broadcast('<span class="math display">\\int_0^1 x^2\\,dx</span>')
    assert "%5Cdpi%7B360%7D" in inline
    assert "%5Cdpi%7B360%7D" in display


def test_broadcast_email_inline_math_sized_to_measured_dimensions() -> None:
    # The high-DPI source (measured 90x27) is displayed at 1/3 = 30x9 so it
    # matches surrounding text rather than rendering at its natural size.
    html = _broadcast('<p>Euler: <span class="math inline">e^{i\\pi}+1=0</span>.</p>')
    assert 'width="30"' in html
    assert 'height="9"' in html


def test_broadcast_email_display_math_sized_and_responsive() -> None:
    html = _broadcast('<p><span class="math display">\\int_0^1 x^2\\,dx</span></p>')
    assert 'width="30"' in html
    assert 'height="9"' in html
    # Responsive cap so a wide equation never overflows a narrow screen.
    assert "max-width:100%" in html
    assert "height:auto" in html


def test_broadcast_email_math_falls_back_to_unsized_image_when_measurement_fails() -> None:
    # If we can't measure the image we render a correctly-sized (display-DPI)
    # image with no explicit dimensions rather than risk a giant high-DPI image.
    html = _broadcast('<span class="math inline">x</span>', measure=_no_measure)
    assert "%5Cdpi%7B120%7D" in html
    assert "%5Cdpi%7B360%7D" not in html
    assert 'width="' not in html  # no explicit dimensions on the fallback image


def test_broadcast_email_measures_each_distinct_formula_once() -> None:
    seen: list[str] = []

    async def _counting(url: str) -> tuple[int, int] | None:
        seen.append(url)
        return (90, 27)

    _broadcast(
        '<span class="math inline">x</span><span class="math inline">x</span>'
        '<span class="math display">y</span>',
        measure=_counting,
    )
    assert len(seen) == 2  # "x" measured once despite appearing twice, plus "y"


def test_broadcast_email_does_not_turn_prose_into_math_image() -> None:
    html = _broadcast("<p>No math here, just text.</p>")
    assert "latex.codecogs.com" not in html
    assert "No math here, just text." in html


def test_broadcast_email_header_precedes_title_and_content() -> None:
    html = _broadcast("<p>Body</p>", title="My Post")
    header_pos = html.index("View this post online")
    title_pos = html.index("My Post")
    body_pos = html.index("Body")
    # Header (post link + unsubscribe) comes first, then the title, then content.
    assert header_pos < title_pos < body_pos
    assert "{{{RESEND_UNSUBSCRIBE_URL}}}" in html[:body_pos]
    assert "https://blog.example/post/hello" in html[:body_pos]


def test_broadcast_email_shows_title_as_heading() -> None:
    html = _broadcast("<p>Body</p>", title="My Post")
    assert "<h1" in html
    heading = html[html.index("<h1") : html.index("</h1>")]
    assert "My Post" in heading


# ── Post-body styling (inlined web .prose styles) ─────────────────────────────


def test_broadcast_email_body_matches_web_font_size() -> None:
    html = _broadcast("<p>Body</p>")
    assert "font-size:17px" in html
    assert "line-height:1.75" in html


def test_broadcast_email_footnotes_rendered_smaller() -> None:
    html = _broadcast('<section class="footnotes"><hr><ol><li>note</li></ol></section>')
    assert 'class="footnotes"' in html
    assert "font-size:0.85em" in html


def test_broadcast_email_styles_code_blocks() -> None:
    html = _broadcast("<pre><code>print(1)</code></pre>")
    assert "#1e1e2e" in html  # dark code-block background
    assert "monospace" in html


def test_broadcast_email_styles_inline_code() -> None:
    html = _broadcast("<p>Use <code>x</code> here.</p>")
    assert "background:#ede8e1" in html  # inline-code chip background


def test_broadcast_email_code_inside_pre_not_chip_styled() -> None:
    html = _broadcast("<pre><code>x</code></pre>")
    # <code> inside <pre> must not get the inline-code chip background.
    assert "background:#ede8e1" not in html


def test_broadcast_email_code_block_has_syntax_highlight_colors() -> None:
    # Pandoc highlight token spans inside a code block get their Catppuccin
    # colors inlined, since CSS classes don't survive in email.
    html = _broadcast(
        '<pre class="sourceCode"><code>'
        '<span class="kw">def</span> f(): <span class="st">"hi"</span>'
        "</code></pre>"
    )
    assert "color:#cba6f7" in html  # keyword (mauve)
    assert "color:#a6e3a1" in html  # string (green)


def test_broadcast_email_highlight_classes_only_apply_inside_code_blocks() -> None:
    # A token-like class outside a <pre> must not be recolored as syntax.
    html = _broadcast('<p><span class="kw">not code</span></p>')
    assert "color:#cba6f7" not in html


def test_broadcast_email_renders_note_callout_with_label() -> None:
    html = _broadcast('<div class="note"><p>Heads up.</p></div>')
    assert "#8a857e" in html  # callout accent / label color
    assert ">Note</div>" in html  # injected label (web uses a ::before pseudo-element)


def test_broadcast_email_headings_use_serif_display_font() -> None:
    html = _broadcast("<h2>Section</h2>")
    assert '<h2 style="font-family:Georgia' in html


def test_broadcast_email_body_links_use_accent_color() -> None:
    html = _broadcast('<p><a href="https://x.example/">link</a></p>')
    assert "color:#c44b2b" in html


# ── Property-based URL invariants ─────────────────────────────────────────────


_SLUG_ALPHABET = st.characters(whitelist_categories=("Lu", "Ll", "Nd"), min_codepoint=32)


@given(st.text(alphabet=_SLUG_ALPHABET, min_size=1, max_size=50))
def test_absolute_post_urls_root_relative_becomes_absolute(slug: str) -> None:
    """Root-relative /foo URL in post HTML → made absolute in broadcast email."""
    path = f"/{slug}"
    html, _text = _build(
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
    html, _text = _build(
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
    html, _text = _build(
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
    html, _text = _build(
        post_url="https://blog.example/post/test",
        post_title="Test",
        post_html=post_html,
        controller_name="Blog",
        postal_address="1 St",
    )
    assert 'class="math inline"' not in html
    assert 'class="math display"' not in html


def test_broadcast_email_youtube_embed_iframe_replaced_with_thumbnail() -> None:
    html = _broadcast(
        '<p>Before</p><iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe><p>After</p>'
    )
    assert "<iframe" not in html
    assert "img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg" in html
    assert "youtube.com/watch?v=dQw4w9WgXcQ" in html
    assert "Watch on YouTube" in html
    assert "Before" in html
    assert "After" in html


def test_broadcast_email_youtube_shorts_iframe_replaced_with_thumbnail() -> None:
    html = _broadcast('<iframe src="https://www.youtube.com/shorts/dQw4w9WgXcQ"></iframe>')
    assert "<iframe" not in html
    assert "img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg" in html
    assert "youtube.com/watch?v=dQw4w9WgXcQ" in html


def test_broadcast_email_youtube_nocookie_iframe_replaced_with_thumbnail() -> None:
    html = _broadcast('<iframe src="https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"></iframe>')
    assert "<iframe" not in html
    assert "img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg" in html
    assert "youtube.com/watch?v=dQw4w9WgXcQ" in html


def test_broadcast_email_youtube_iframe_with_query_params_uses_correct_video_id() -> None:
    html = _broadcast('<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ?start=30"></iframe>')
    assert "<iframe" not in html
    assert "img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg" in html
    assert "youtube.com/watch?v=dQw4w9WgXcQ" in html


def test_broadcast_email_multiple_youtube_iframes_each_replaced() -> None:
    html = _broadcast(
        '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>'
        '<iframe src="https://www.youtube.com/embed/AAAAAAAAAAA"></iframe>'
    )
    assert "<iframe" not in html
    assert html.count("img.youtube.com/vi/") == 2
    assert "img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg" in html
    assert "img.youtube.com/vi/AAAAAAAAAAA/hqdefault.jpg" in html


def test_broadcast_email_iframe_without_src_silently_dropped() -> None:
    html = _broadcast("<p>Before</p><iframe></iframe><p>After</p>")
    assert "<iframe" not in html
    assert "youtube" not in html
    assert "Before" in html
    assert "After" in html


def test_broadcast_email_surrounding_content_unaffected_by_iframe_replacement() -> None:
    html = _broadcast(
        "<h2>Section</h2>"
        '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>'
        "<p>Continue reading.</p>"
    )
    assert "Section" in html
    assert "Continue reading." in html
    assert "img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg" in html
